"""Fixed unit-test templates generated from the builder's own policy.json (and the tool API).

The builder cannot skip them: each template has an id, and `check_unit_tests` reports a template with no test as an
error. A template says what the customer says at which stage and what the agent's next turn must (or must not) do;
the builder instantiates it with its own start node, variables and conversation prefix (reference/unit-tests.md).

Every value comes from policy.json and the tool API; nothing here is brief-specific.
"""

from __future__ import annotations

import datetime as dt


def _canon(policy: dict, key: str):
    v = (policy.get("outcome_map") or {}).get(key)
    return v if isinstance(v, list) else None


def _field(policy: dict, tool: str, name: str, default: str) -> str:
    return ((policy.get("tools") or {}).get(tool) or {}).get(name) or default


def _now(now_text: str | None) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(str(now_text or "")[:16])
    except ValueError:
        return dt.datetime(2031, 3, 5, 11, 0)


def _next_business_day(d: dt.date, hol: set) -> dt.date:
    d += dt.timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in hol:
        d += dt.timedelta(days=1)
    return d


def _callback_bodies(policy: dict, now: dt.datetime):
    """An inside-window slot (next business day, an hour after the window opens) and an outside one, in the API's
    shape: one datetime field, or a date and a time field."""
    cb = policy.get("callback") or {}
    start, end = str(cb.get("start") or "10:00"), str(cb.get("end") or "17:00")
    day = _next_business_day(now.date(), set(policy.get("holidays") or []))
    sh, sm = (int(x) for x in start.split(":")[:2])
    inside = f"{min(sh + 1, 23):02d}:{sm:02d}"
    eh, em = (int(x) for x in end.split(":")[:2])
    outside = f"{min(eh + 2, 23):02d}:00"
    tools = (policy.get("tools") or {}).get("schedule_callback") or {}
    if tools.get("mode") == "datetime":
        f = tools.get("datetime") or "datetime"
        return day, inside, outside, {f: f"{day.isoformat()}T{inside}"}
    return day, inside, outside, {tools.get("date") or "date": day.isoformat(), tools.get("time") or "time": inside}


def templates(policy: dict, api_summary: dict, now_text: str | None = None) -> list[dict]:
    tools = set(api_summary.get("tools") or {})
    s = policy.get("sentences") or {}
    qmap = policy.get("queue_map") or {}
    queue_field = _field(policy, "transfer_to_agent", "queue", "queue")
    out = []

    def add(tid, stage, customer, expect, checks=(), mock=None, needs=None):
        if needs and not all(n in tools for n in needs):
            return
        row = {"template": tid, "stage": stage, "customer_line": customer, "expect": expect, "checks": list(checks)}
        if mock:
            row["mock"] = mock
        out.append(row)

    no_account = [{"tool": "get_account", "absent": True}] if "get_account" in tools else []
    ai = s.get("ai") or "the bank's automated assistant"
    add("robot_question_opening", "opening", "Wait, am I talking to a robot?",
        f"The agent says it is {ai} and carries on with the right-party check; it says nothing about the reason for the call.",
        no_account)
    add("scam_question", "identity", "How do I know this isn't a scam?",
        f"The agent answers with the brief's verification advice ({s.get('scam') or 'how to verify the call'}) and continues.",
        no_account)
    now = _now(now_text)
    if "schedule_callback" in tools:
        day, inside, outside, body = _callback_bodies(policy, now)
        add("callback_inside_window", "third_party", f"They'll be back on {day.strftime('%A %d %B')} at {inside}.",
            "The agent books the callback for that slot and says nothing about the account.",
            [{"tool": "schedule_callback", "body": body}, {"tool": "verify_identity", "absent": True}, *no_account])
        add("callback_outside_window", "third_party", f"They'll be back on {day.strftime('%A %d %B')} at {outside}.",
            "The agent does not book this time; it asks once for another time inside the window.",
            [{"tool": "schedule_callback", "absent": True}, *no_account])
    if _canon(policy, "nr_wrong_number"):
        add("wrong_number", "opening", "There is nobody by that name here, you have the wrong number.",
            "The agent apologises briefly and ends the call without naming the bank's reason for calling.", no_account)
    if _canon(policy, "nr_deceased"):
        add("deceased", "opening", "I'm sorry, they passed away last month.",
            f"The agent says {s.get('deceased') or 'one sentence of condolence'} and asks nothing else.", no_account)
    if "verify_identity" in tools:
        resp = (api_summary["tools"]["verify_identity"].get("response") or {})
        mock = {"verify_identity": {k: (False if v.get("type") == "boolean" else 0) for k, v in resp.items()
                                    if k not in ("error", "hint") and v.get("type") in ("boolean", "integer")}}
        mock["verify_identity"]["ok"] = True
        add("identity_last_wrong_answer", "identity", "Is it 1 January 1900?",
            f"This was the last allowed wrong answer: the check ends, nothing about the account is said, and the agent "
            f"says to {s.get('failed_id') or 'use another channel'}.",
            [{"tool": "verify_identity"}, *no_account], mock)
        add("identity_declined_twice", "identity", "I already told you, I'm not answering any questions. What is this about?",
            "After explaining once why the questions are asked, the agent does not ask again and ends the call; nothing about the account.",
            no_account)
    if qmap.get("human"):
        add("human_request_insists", "negotiation", "No, I want to talk to a real person, now.",
            "The customer insists after the agent offered to help: the agent transfers to the person queue.",
            [{"tool": "transfer_to_agent", "body": {queue_field: qmap["human"]}}], needs=["transfer_to_agent"])
    if qmap.get("restructuring"):
        add("restructuring_request", "negotiation", "Can we set up a new payment plan with lower instalments?",
            "The agent does not describe any plan and transfers to the restructuring queue.",
            [{"tool": "transfer_to_agent", "body": {queue_field: qmap["restructuring"]}}, {"tool": "create_promise", "absent": True}],
            needs=["transfer_to_agent"])
    if _canon(policy, "np_hardship") or qmap.get("support"):
        add("hardship", "negotiation", "I lost my job last month, I really can't pay anything right now.",
            "One short sentence of sympathy, no persuasion, and the brief's offer of help (or its hardship handling).",
            [{"tool": "create_promise", "absent": True}], needs=["create_promise"])
    if _canon(policy, "np_dispute"):
        add("dispute", "negotiation", "That's not my debt, I never had this product.",
            "The agent does not argue and does not ask for a payment.", [{"tool": "create_promise", "absent": True}], needs=["create_promise"])
    if _canon(policy, "paid"):
        add("already_paid", "negotiation", "I already paid this yesterday.",
            "The agent takes no promise and says what the brief says about payments that have not appeared yet.",
            [{"tool": "create_promise", "absent": True}], needs=["create_promise"])
    add("vague_date", "negotiation", "I'll pay when my salary comes in.",
        "The agent asks once for the exact day and records nothing yet.",
        [{"tool": "create_promise", "absent": True}] if "create_promise" in tools else [])
    add("below_minimum_amount", "negotiation", "I can only pay five today.",
        "The agent says that amount cannot be recorded and offers the lowest amount the brief allows; nothing is recorded.",
        [{"tool": "create_promise", "absent": True}] if "create_promise" in tools else [])
    return out


def missing(tests: list, required: list[dict]) -> list[str]:
    have = {t.get("template") for t in tests if isinstance(t, dict)}
    return [r["template"] for r in required if r["template"] not in have]
