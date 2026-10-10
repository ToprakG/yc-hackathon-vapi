"""EXTRACT: brief text + tool API summary -> policy.json in the canonical schema (two LLM passes, one fix round).

Pass 1 reads the brief and fills every key. Pass 2 checks every field against the brief, fixes errors and quotes the
source. `policy_check.check` then runs; violations go back to the model once as a fix request. Anything still invalid
gets the conservative default (policy_check.repair) and is logged.
"""

from __future__ import annotations

import json

from builder.template_cc import policy_check
from builder.template_cc.policy_check import (ATTEMPT_AMOUNTS, ATTEMPT_DATES, CANONICAL_NOTES, CANONICAL_OUTCOMES,
                                              CANONICAL_QUEUES, LINE_KEYS, SCHEMA)

RULES = f"""You read a bank's specification for an outbound collections phone call (a clean spec, or raw material:
mails, policy extracts, memos, code lists) and its tool API. You write policy.json: the facts a code generator needs
to build the call. Every value comes from the brief or the tool API. Never invent a value; never use an example value.

General rules
- Several brief parts are given in order: a later part, a later memo or a newer statement overrides an earlier one.
  Use the final value and record each override in "_overrides": [{{"key", "old", "new", "source"}}].
- Enum values (outcomes, reasons, codes, queues, note reasons, identity field values, product types) are copied exactly
  as the tool API spells them. Field names in "tools" and "account_fields" are the API's field names.
- "_source": map of JSON pointer (e.g. "/bands/0/deadline_business_days") -> an exact quote from the brief that states
  it. Quote short exact spans. Give a quote for every key the brief states.
- If the brief is silent, use null / [] / {{}} and say so in "extra_rules" with stage "global" only when it matters.

Keys
- bank, language (ISO code), address (how to address the customer with {{field}} placeholders from the call variables).
- call_variables: every call variable the brief lists.
- holidays: every listed non-business day as YYYY-MM-DD, sorted (convert odd formats).
- bands: [{{name, min_days, max_days, deadline_business_days, attempts}}] contiguous, in order.
- attempt1: the brief's rule for the first persuasion proposal in one sentence of your own words.
- attempt_plan: one object per persuasion attempt, in order: {{"date": one of {list(ATTEMPT_DATES)}, "amount": one of
  {list(ATTEMPT_AMOUNTS)}, "cap_at_deadline": bool}}. end_of_week_roll = last business day of this week, or of next
  week when today is that day; full_or_floor = the full amount, or the floor if the customer already said the full
  amount is too much.
- weekday_words: {{"next": "following_week"|"next_occurrence", "this": "current_week"|"next_occurrence"}}.
- identity: {{"questions": [API field values in asking order], "max_wrong": int, "swap_hint": bool (the API returns a
  hint the brief tells the agent to act on), "prompts": {{field: the question to ask}}, "kinds": {{field:
  "date"|"year"|"digits"|"code"|"text"}}}}.
- callback: {{"start": "HH:MM", "end": "HH:MM", "same_day": bool}}.
- outcome_map: canonical key -> [outcome, reason] (reason null when none) or [code, null] when close_call takes one
  code; null for a situation the brief does not have. Canonical keys: {", ".join(CANONICAL_OUTCOMES)}.
- queue_map: {{{", ".join(CANONICAL_QUEUES)}}} -> transfer queue value or null.
- note_map: {{{", ".join(CANONICAL_NOTES)}}} -> add_note reason value; {{}} when the brief never uses notes.
- close_rule: {{"kind": "first_non_paid"}} or {{"kind": "priority", "order": [canonical note keys]}} or {{"kind": "single"}}.
- notes_on_restructuring: canonical note key to note before a restructuring transfer, or null.
- product_types: canonical short key -> {{"enum": API type value, "label": how the agent names it ({{last4}} allowed),
  "floor_field": account field of the minimum amount, "last4_field": account field or null}}.
- account_fields: {{"product_id", "type", "past_due", "days_late"}} -> get_account field names.
- product_id_format: the id pattern, e.g. "x{{n}}".
- tools: {{"verify_identity": {{"field", "answer"}}, "create_promise": {{"product_id", "amount", "date",
  "amount_unit": "currency"|"cents"}}, "schedule_callback": {{"mode": "date_time", "date", "time"}} or {{"mode":
  "datetime", "datetime"}}, "close_call": {{"mode": "outcome_reason", "outcome", "reason"}} or {{"mode": "code",
  "code"}}, "transfer_to_agent": {{"queue"}}, "add_note": {{"product_id", "reason"}}}} (values are API field names).
- sentences: {{"opening", "promise_confirmation", "ai", "scam", "failed_id"}} short phrases as the brief states them.
- lines: speakable sentences the agent says, keyed by {", ".join(LINE_KEYS)}. Each {{"text", "verbatim": bool}}.
  verbatim=true only when the brief fixes the exact words (copy them exactly, with {{field}} placeholders for call
  variables); otherwise write one short spoken sentence that says exactly what the brief requires, nothing more.
  The only placeholders allowed in a line are call variables ({{field}}). Never put account values (product,
  amount, days late, dates) into a line: the code adds them.
  The opening line must contain everything the brief requires in the first sentence.
- forbidden_before_verify: words or topics not to say before identity is verified.
- multi_product (bool), max_products (int).
- retries: {{tool name: extra attempts after a failure}} as the brief or the API allows.
- ask_limits: {{"right_party", "id_decline", "callback_reask", "vague_date", "stop_talking", "human_offer"}} counts.
- unused_tools: tools the brief never uses.
- extra_rules: [{{"statement", "brief_quote", "stage": opening|third_party|identity|debt|negotiate|close|global}}]
  for every brief rule that the keys above do not capture. Short, concrete, in the brief's terms."""

PASS1 = RULES + "\n\nRead the whole brief. Fill every key."
PASS2 = RULES + """

You are given a draft policy.json. Check EVERY field against the brief and the tool API: values, enum spellings,
holiday dates, band limits, attempt counts, callback hours, which sentences are verbatim, overrides by later material.
Fix every error and add a quote to "_source" for each field you checked. Return the complete corrected policy.json."""
FIX = RULES + """

A deterministic checker found the violations listed below in policy.json. Fix each one using the brief and the tool
API (an enum value must be one the API lists; a quote must be copied exactly from the brief). Return the complete
corrected policy.json."""


def _user(brief: str, api_text: str, extra: str = "") -> str:
    return f"# Brief\n\n{brief}\n\n# Tool API (summary)\n\n{api_text}\n" + (f"\n{extra}\n" if extra else "")


def extract(brief: str, api, call_llm, model: str, trace, deadline: float | None = None, out_dir=None) -> dict:
    """Returns {"policy": final, "pass1": ..., "violations": [...], "repairs": [...]}."""
    api_text = api.render()
    p1 = call_llm(PASS1, _user(brief, api_text), model, json_schema=SCHEMA, temperature=0, max_tokens=16000,
                  effort="high", trace=trace, purpose="extract pass 1: brief -> policy.json", deadline=deadline)
    if out_dir:
        (out_dir / "policy.pass1.json").write_text(json.dumps(p1, indent=1, ensure_ascii=False), encoding="utf-8")
    p2 = call_llm(PASS2, _user(brief, api_text, "# Draft policy.json\n\n" + json.dumps(p1, ensure_ascii=False)), model,
                  json_schema=SCHEMA, temperature=0, max_tokens=16000, effort="high", trace=trace,
                  purpose="extract pass 2: check every field against the brief", deadline=deadline)
    policy = policy_check.complete(p2, api)
    violations = policy_check.check(policy, api, brief)
    trace.check("policy_check after pass 2", not violations, f"{len(violations)} violation(s)")
    first = list(violations)
    if violations:
        listing = "\n".join(f"- {v['path']}: {v['msg']}" for v in violations)
        fixed = call_llm(FIX, _user(brief, api_text, "# policy.json\n\n" + json.dumps(policy, ensure_ascii=False)
                                    + "\n\n# Violations\n\n" + listing), model, json_schema=SCHEMA, temperature=0,
                         max_tokens=16000, effort="high", trace=trace,
                         purpose=f"extract fix round: {len(violations)} policy_check violation(s)", deadline=deadline)
        policy = policy_check.complete(fixed, api)
        violations = policy_check.check(policy, api, brief)
        trace.check("policy_check after fix round", not violations, f"{len(violations)} violation(s)")
    repairs: list[str] = []
    if violations:
        policy, repairs = policy_check.repair(policy, violations, api)
        policy = policy_check.complete(policy, api)
        for r in repairs:
            trace.line(f"policy default: {r}")
        left = [v for v in policy_check.check(policy, api, brief) if not v["path"].startswith("/_source/")]
        trace.check("policy_check after defaults", not left, f"{len(left)} violation(s) left")
    return {"policy": policy, "pass1": p1, "violations": first, "repairs": repairs}
