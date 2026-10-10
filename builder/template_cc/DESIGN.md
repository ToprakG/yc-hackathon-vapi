# Variant T-CC: design (Phase 0)

T-CC = A1 (extract → fixed template) + a Claude Code policy audit + a gated, judged prompt-patch loop.
Everything lives in `builder/template_cc/` and `tests/template_cc/`. Nothing under `builder/agentic/`,
`builder/common/`, `builder/eval/` or `builder/build.py` is touched.

## 1. Verified findings

### 1.1 Agent SDK (`.venv310`, claude-agent-sdk 0.2.165, CPython 3.10.20)

`import claude_agent_sdk` works. `SDK_NOTES.md` was checked against the installed `types.py` / `__init__.py`:

| Item | Where | Status |
|---|---|---|
| `tools=` base set of built-ins | `types.py:1974` | confirmed; `["Read","Glob","Grep","Write"]` removes Bash/Web/Task |
| `allowed_tools` (auto-approve only) | `types.py:1985` | confirmed |
| `permission_mode="dontAsk"` | `types.py:26`, doc at `:2032` "deny if not pre-approved" | confirmed |
| `max_budget_usd` | `types.py:2056` → `error_max_budget_usd` result | confirmed |
| `max_turns`, `setting_sources`, `system_prompt` (a plain `str` replaces the preset) | `types.py` | confirmed via SDK_NOTES + source |
| `HookMatcher(matcher, hooks, timeout)` | `types.py:606` | confirmed; deny = `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": ...}}` |
| `tool(...)`, `create_sdk_mcp_server(...)` | `__init__.py:251`, `:491` | confirmed; names seen as `mcp__<server>__<tool>` |
| Timeout | SDK_NOTES "Shutdown and timeouts" | use `anyio.fail_after` around the consumer, then SIGTERM/SIGKILL the leftovers in `_ACTIVE_CHILDREN` (same as A-agent) |

### 1.2 `agentforge.llm` under `.venv310` → **port**

`import agentforge.llm` fails: `No module named 'dotenv'` (`agentforge/config.py`). `.venv310` also has **no
`anthropic`, `openai`, `httpx` or `rich`**, and no `pip` to add them (pydantic 2.14 and pytest 9.1 are present).
So `builder/template_cc/llm.py` ports the contract onto **stdlib `urllib`**:
`call_llm(system, user, model, json_schema, temperature, max_tokens, effort)`; `split_model` uses the same `provider:model`
convention; Anthropic Messages API and OpenAI chat-completions over HTTPS; the same retry/backoff (429/5xx), same
`parse_json` and `unwrap_schema_echo`; the token usage and cost from the response go to the trace. `.env` is read with a small
stdlib loader (an exported var always wins). There is no `agentforge` import anywhere in the delivered builder.

### 1.3 Decision model (`vendor/build-the-builder`, commit `36ab492`, cloned read-only, `vendor/` gitignored)

The repo is **a copy of the kit plus extra judge tools**. These kit files are byte-identical: `freya.py`, `docs/*.md`,
`tools/openapi.json`, `tools/score.py`, `public-test-set.json`, `briefs/*`. `tools/run_cases.py` differs only by a
`--judges` flag that runs Judge C. Extra files: `tools/{decide,judges,judge_call,checks,serialize_call,envfile,fetch_transcripts}.py`,
`tools/driver/*` (a chat driver + mock bank), `seed/*` (their own seed builder), `results/` (60 saved transcripts,
`thresholds.json`, run logs).

| Question | Answer |
|---|---|
| Entry point | `tools/decide.py: decide(text: str, questions: list[dict], model="gpt-6-luna", timeout=90) -> dict`. Also `has_decision_key() -> bool`, `class DecisionsError(RuntimeError)` with `.status`. `judges.judge_c(messages, case, thresholds=None, model=True)` is the transcript wrapper on top of it. |
| Input | `text`: **any free text** (Judge C passes a rendered transcript + FACTS block). `questions`: `[{"name": str, "type": "predicate", "instructions": str}]`; **all questions go in one request**. |
| Output | `{"answers": [{"name", "type", "probability"}], "model", "provider"}`. `probability` = P(yes), 0..1. `type == "refusal"` → no probability. **No evidence text.** |
| Pass rule | `p >= threshold`; `results/thresholds.json` = `{"global": 0.5, "family": {}}`. |
| Model / keys | `POST https://api.openai.com/v1/decisions`, model `gpt-6-luna`, `OPENAI_API_KEY`. On 401/402/429/5xx it falls back to `POST https://openrouter.ai/api/alpha/decisions`, model `openai/gpt-6-luna-decisions`, `OPENROUTER_API_KEY`. `envfile.load_env()` reads `vendor/build-the-builder/.env` (absent; the process env wins anyway). |
| Deps / Python | stdlib only (`json, os, urllib`); imports `from envfile import load_env`. **Imports cleanly under 3.10** (checked, no network). |
| Batching / voting | Batches all named questions in one POST. No voting, no temperature parameter. |
| Calibration | `thresholds.json` (0.5 global), 60 transcripts + `judge_call.py --audit` (coded checks vs Freya). **No agreement numbers shipped.** |

**How T-CC calls it: in process**, through `ToprakDecisionJudge`. It loads `decide.py` and `envfile.py` with
`importlib.util.spec_from_file_location` under private module names (`_tcc_vendor_decide`). For the duration of the import it adds
`vendor/build-the-builder/tools` to `sys.path` and registers a private `envfile` alias, then restores `sys.path` and removes the alias.
This leaves no generic `decide`/`envfile`/`checks` names in `sys.modules`. The patch-judging framing goes into `text`, which is
fully supported. No wrapping limitation applies, because `decide` is not transcript-specific. The questions in §4.7 become
`predicate` questions in one batched call per patch. A "no"-pass question passes when `p < threshold`. The threshold
(0.5) and `model` are exposed through `--models` (`judge_threshold`, `judge_model`). `evidence` in our verdict = `"p=0.83"`
(the vendor gives none). `LocalDecisionJudge` (one call per question, temperature 0, `DECISION_MODEL`, JSON
`{answer, evidence}`, optional 3-vote) runs only when the vendor repo is missing or `has_decision_key()` is false, with a
loud trace line.

### 1.4 A-agent tools used read-only

- `builder.agentic.tools.openapi_summary.summarize(spec: dict) -> dict` / `load(path) -> dict` →
  `{"base_url", "title", "tools": {name: {method, path, url, summary, request, required, response, statuses}}, "missing_kit_tools"}`;
  `render(summary, max_chars=14000) -> str` for prompts.
- `builder.agentic.tools.lint.lint(wf, api_summary, call_vars=None, unused_tools=()) -> {"errors": [...], "warnings": [...]}`
  (`policy_hints(policy)` gives `call_vars, unused_tools` from `policy.call_variables` / `policy.unused_tools`).
- `builder.agentic.tools.snippets.run_snippet(wf, node_id, variables=None, kind="code"|"pre_hook"|"post_hook", tool=None, result=None, timeout=10) -> {"vars_written", "stdout", "exception", ...}`.
- `builder.agentic.tools.validate.validate(wf, name="dry-run") -> dict` (skips without `FREYA_API_KEY`).

The A-agent skill references (`call-architecture.md`, `freya-cookbook.md`, `policy-schema.md`, `self-check.md`) were
read. The compiler below implements the same stage menu and pitfalls, so both variants carry the same domain knowledge.

## 2. Conflicts and decisions you need to OK

1. **The close form: node vs lifecycle.** §4.3 asks for a close `api_request` node followed by `end_call`. The kit
   (`tools-and-code.md` "Lifecycle tools") and the A-agent cookbook recommend `close_call` as a workflow-level
   `alwaysRunsAt: ["end_of_call"]` tool, because it is the **only form that closes a call when the customer hangs up**
   mid-call. With the node form, a hang-up gives no `close_call`, and the case fails its records. Both forms
   together would close twice. **My recommendation: the lifecycle form**, with values baked from `close_*` vars that the
   `close_compute` code node and the hooks keep current, and a pre-hook that drops absent fields. Pessimistic defaults are set in
   `setup`. The goodbye is then said by a passthrough tts node before `end_call`. The compiler supports both (`--close-form node|lifecycle`); I need you to pick the default.
2. **Which tools are model-facing.** §4.3 lists `create_promise`, `add_note`, `transfer_to_agent` and
   `schedule_callback` as model-facing. I propose making **`transfer_to_agent` and `add_note` engine-run**
   (`api_request` nodes with baked `queue` / `product_id` / `reason`), reached by routes. The queue and the note reason
   are fully decided by state, so baking them removes a whole class of wrong-enum and forgotten-note failures, and makes
   notes-before/no-notes-around-transfer a graph property. `create_promise` and `schedule_callback` stay model-facing,
   because their values come from speech. Their pre-hooks normalise the values.
3. **Policy schema additions.** The canonical `sentences` are paraphrases ("a digital assistant calling from
   X; the call is recorded"), not speakable lines, and `attempt1` is free text. Neither can be compiled. I keep every
   canonical key (so `builder/eval/score_policy.py` still scores us) and **add**:
   `lines` (speakable sentences, each `{text, verbatim: bool, _source}`), `attempt_plan` (structured, from a generic enum),
   `retries`, `ask_limits`, `weekday_words`, `call_variables`, `unused_tools`, `extra_rules`, `_source`, `_overrides`. See §3.
4. **The decision model in the delivered builder.** `vendor/` is gitignored on purpose, so a fresh checkout of our repo
   (the final rerun) has no vendor judge. It then runs `LocalDecisionJudge`, or no judge if `DECISION_MODEL` has no key.
   `TEST_PLAN.md` (line 45) also says the delivered builder must not depend on the decision model until external
   calls are confirmed allowed. With `--audit on` as the default, the judge runs on every build. Proposed rule: if no judge
   can run, audit patches are **not applied** (only logged). The build never blocks on the judge.
5. **The testbed generator needs in-memory monkeypatches.** `assemble.build` hard-codes `PREFIX[cfg["id"]]` and
   `plan_for` keyed on kit/fake ids. `cases.identity_values` / `wrong_value` / `QNAME` know only six identity field
   names. The adapter patches these **attributes in memory** (`assemble.PREFIX`, `assemble.plan_for`, and wrappers for unknown
   identity fields). It never edits the files. See §6.
6. Small facts that differ from the prompt:
   - `builder/build.py`, `builder/common/{io,trace}.py` and `builder/eval/score_policy.py` **already exist and are committed** by A-agent.
   - `agentforge/README.md` does not exist.
   - `examples/pattern_demo*` is referenced by the A-agent cookbook but lives in their skill folder.

   None of this changes the plan.

## 3. Policy schema (`policy.schema.json`)

The canonical testbed keys and types, unchanged: `bank, language, address, identity{questions,max_wrong,swap_hint},
callback{start,end,same_day}, outcome_map, queue_map, note_map, close_rule{kind,order?}, notes_on_restructuring,
product_types{*:{enum,label,floor_field,last4_field}}, account_fields, product_id_format, tools{...modes...},
sentences{opening,promise_confirmation,ai,scam,failed_id}, forbidden_before_verify, multi_product, max_products,
attempt1, holidays, bands[]`. Additions (all generic, with enum vocabularies defined by us and no brief values):

| Key | Shape | Used by |
|---|---|---|
| `call_variables` | list[str] | lint, `test_variables`, tts placeholders |
| `unused_tools` | list[str] | lint |
| `lines` | `{key: {text, verbatim, _source}}`. Keys from a fixed vocabulary: `opening`, `right_party_question`, `ask_again`, `deceased`, `debt_intro`, `first_ask`, `first_ask_multi`, `confirm_question`, `promise_confirmation`, `ai`, `scam`, `failed_id`, `already_paid`, `change_promise`, `cannot_record`, `no_info`, `id_reason`, `hardship_sympathy`, `goodbye` | tts lines and prompt sections. `verbatim: true` lines are spoken via tts unchanged; others are the extractor's sentence, faithful to the brief |
| `attempt_plan` | list per attempt: `{date: "end_of_week_roll"\|"deadline"\|"today"\|"next_business_day", amount: "full_or_floor"\|"full"\|"floor", cap_at_deadline: bool}`, plus `per_band: {band_name: n}` | facts code |
| `weekday_words` | `{next: "following_week"\|"next_occurrence", this: "current_week"\|"next_occurrence"}` | date table |
| `retries` | `{verify_identity, get_account, create_promise, schedule_callback, close_call}`: extra attempts after a failure (int) | hooks, api nodes |
| `ask_limits` | `{right_party: int, id_decline: int, callback_reask: int, vague_date: int, stop_talking: int, human_offer: int}` | graph |
| `routes` | per side route `{enabled, close_key, transfer: canonical queue key or null, note: canonical note key or null, before_verify: bool}` for `hardship, dispute, already_paid, restructuring, human, stop_talking` | graph |
| `extra_rules` | `[{statement, brief_quote, stage}]`, where stage ∈ `opening, third_party, identity, debt, negotiate, close, global` | locked "brief rules" section of that stage |
| `_source` | `{json_pointer: quote}` | `policy_check`, audit, judge |
| `_overrides` | `[{key, old, new, source}]` | trace, audit question `override_respected` |

**Conservative defaults** (applied by `policy_check` when a value stays invalid after the one fix round; each is logged):

| Value | Default |
|---|---|
| `max_wrong` | 2 |
| holidays | `[]` |
| bands | one band, 1..∞, `deadline_business_days` 5, 1 attempt |
| callback window | `same_day: false`, `start <= end` swapped |
| a missing `outcome_map` key | that route's stage closes on the nearest existing key (e.g. `nr_no_callback` → `nr_unclear`); a missing `queue_map` key disables the transfer route |
| unknown `attempt_plan` | `[{"date": "deadline", "amount": "full_or_floor"}]` |
| retries | 1 for reads, 1 for `create_promise`, 0 for other writes |
| a quote not found | the field is kept, flagged `unverified` in `_source`, and the audit is told |

## 4. Compiler node graph (`compiler/graph.py`)

Notation: `[conv]` conversation, `[api]` passthrough api_request, `[code]` passthrough code, `[end]` end_call.
`→` = deterministic transition (`equals` on an extracted enum or a hook-written string, or a counter), listed in order;
the last transition of every passthrough node is `always`.

```
setup [code, initial]           now/today/time; callback window (ISO days + spoken text, hours, "later than now");
                                close defaults = nr_unclear; every var a prompt/condition reads gets a fallback
  → opening
opening [conv]                  on_enter tts: lines.opening (+ recording notice) + lines.right_party_question with
                                {{<address vars>}}; first-entry-only. extract who ∈ {customer, someone_else,
                                wrong_number, deceased, unclear, question}
  → identity (who=customer) | third_party | mark:nr_wrong_number | deceased_say | opening_ask2 (unclear)
opening_ask2 [conv]             (only if ask_limits.right_party ≥ 2) tts lines.ask_again; same extraction
  → identity | third_party | mark:nr_wrong_number | deceased_say | mark:nr_unclear
deceased_say [conv, passthrough] tts lines.deceased verbatim → mark:nr_deceased
third_party [conv]              tools: schedule_callback (model-facing; date/time or datetime per API; pre-hook
                                normalises to the API format). Facts: allowed days (ISO + words) and hours.
                                Post-hook: ok → cb_state=booked; fail → retries rule. extract tp ∈ {gives_time,
                                outside_window, no_time, wrong_number, deceased}
  → mark:nr_callback (cb_state=booked) | mark:nr_wrong_number | deceased_say
  → third_party_reask (tp=outside_window|no_time, once) → mark:nr_no_callback on the 2nd miss
identity [conv]                 tools: verify_identity (field enum = API enum ∩ policy questions; pre-hook
                                normalises per field kind: date → YYYY-MM-DD day-first, digits, year, code upper).
                                Post-hook writes id_state ∈ {next, retry, swap_retry, passed, failed} and
                                what_to_do_next from the API's own counters / hint fields when present, else from
                                a vars counter vs policy.max_wrong. extract idr ∈ {answering, declines, asks_purpose}
  → fetch_account (id_state=passed, or <tool>_response.data.<all_verified> true/True)
  → id_failed (id_state=failed) | identity_explain (idr=declines|asks_purpose)
identity_explain [conv]         lines.id_reason once; same tool + post-hook
  → fetch_account | id_failed | mark:nv_declined (2nd decline/purpose question)
id_failed [conv, passthrough]   tts lines.failed_id → mark:nv_failed
fetch_account [api]             get_account, maxRetries 0, node response_mapping data.<products field> → products_raw
  → fetch_account_retry (fetch_account_failure_count > 0, if retries.get_account ≥ 1) | facts
fetch_account_retry [api]       same call → service_error_say (failure) | facts
facts [code]                    per product (API order, 1..max_products, renamed fields, cents): band, deadline,
                                attempts, attempt-plan proposals, floor, past-due, spoken amounts/dates, a date table
                                (today + 21 days: weekday, business day?, ≤ deadline?, this/next weekday resolution),
                                facts_text, debt_statement, product_count, current_* for product 1, flags (strings)
  → state_debt
state_debt [conv, passthrough]  tts {{debt_statement}} + lines.first_ask[_multi] → negotiate
negotiate [conv]                facts_text + brief rules for this stage. tools: create_promise (model-facing;
                                product_id model-filled with a static enum built from product_id_format for
                                1..max_products, because several calls share one node entry and a baked value
                                would be frozen; pre-hook: amount → API unit with round(), date → YYYY-MM-DD,
                                product id checked against products_raw).
                                Post-hook: ok → promise count/state, what_to_do_next = say lines.promise_confirmation
                                verbatim; fail → retry per policy, then "say you could not record it" + state.
                                extract side ∈ {none, hardship, dispute, already_paid, restructuring, human,
                                stop_talking, product_done, product_refused_final}
  → product_loop (loop_flag=advance, multi only) | hardship | dispute_mark | paid_mark | restructuring_transfer
  → human_offer | stop_count | notes_loop (all products resolved, or single product resolved)
product_loop [code]             (multi) store per-product result, set current_* to next pending product, reset flag
  → negotiate | notes_loop
hardship [conv]                 lines.hardship_sympathy, offer support; extract accept ∈ {yes, no, names_terms}
  → transfer:support | negotiate (names_terms) | mark product hardship → product_loop/notes_loop
dispute_mark / paid_mark [code] per-product state (multi continues; single ends) → product_loop | notes_loop
human_offer [conv]              ask once whether you can help (ask_limits.human_offer); extract insist ∈ {insists, ok}
  → transfer:human | __back to negotiate / identity / opening (stored return target via code node)
stop_count [code]               increment; 2nd → mark:np_refused (after verify) / mark:nv_declined (before)
restructuring_transfer          → pre_transfer_notes (if notes_on_restructuring) → transfer:restructuring
transfer:<q> [api]              transfer_to_agent, queue baked from queue_map; post: close state tr_<q>
  → close_compute
pre_transfer_notes [code+api]   loop add_note(product, note_map[notes_on_restructuring]) for products w/o promise
notes_loop [code+api]           multi only: add_note per unpromised product with its canonical reason → close_compute
service_error_say [conv, passthrough] truthful line → mark:np_service_error
mark:<key> [code]               close_key = <canonical key> → close_compute
close_compute [code]            outcome/reason or code from state: transfer wins; else any promise → promise;
                                multi: all paid → paid, else close_rule (first_non_paid | priority order);
                                writes close_outcome/close_reason | close_code, goodbye_line
  → goodbye
goodbye [conv, passthrough]     tts {{goodbye_line}} (thanks + goodbye, before the close record)
  → close_call_node [api] (node form) → end [end, message_mode none]
     or → end directly (lifecycle form: close_call in top-level tools, alwaysRunsAt end_of_call)
```

Global nodes (`excluded_nodes` = every code/api/end node, `goodbye`, `deceased_say`, `id_failed`):
`g_ai` (tts `lines.ai`, `__previous__`), `g_scam` (tts `lines.scam`, `__previous__`), `g_human` → `human_offer`,
`g_no_info` (question the tools cannot answer → `lines.no_info`, `__previous__`, excluded pre-verification nodes where the
answer would leak), `g_change_promise` (after a recorded promise → `lines.change_promise`, `__previous__`).
`human_offer` returns through a stored `return_node` var routed by a small code node. `__previous__` is avoided
there, because the offer has its own turn.

System prompt sections: identity/language/tone (locked), forbidden words before verification (locked, also repeated in
every pre-verification node's task), honesty and tool discipline ("after every tool result speak or call the next tool;
one tool per message; follow what_to_do_next"; locked), and `global_rules` (unlocked, initially empty or extra_rules with
stage `global`).

Every conversation node gets `max_node_turns` with a `max_turn_transition` to its stage's safe ending, and
`on_enter_first_entry_only` where re-entered. Single-product briefs compile without `product_loop`, `notes_loop` and
`dispute/paid` continuation. Routes whose `outcome_map` key is null are not compiled.

## 5. Patch zones (`zones.py`)

A zone = `{id, location (JSON pointer + section), locked, max_chars, text}`. Composite fields (`task_message`,
`system_prompt`, a hook's message map) are re-rendered from their sections by `zones.apply`. That is the only write path.
`zones.json` is written next to the workflow.

| Zone id | Locked | max_chars | Content |
|---|---|---|---|
| `system/core`, `system/forbidden`, `system/honesty` | yes | – | compiled |
| `system/global_rules` | **no** | 1500 | extra global if/then rules |
| `node:<id>/task` | yes | – | the compiled job of the node |
| `node:<id>/facts` | yes | – | `{{facts_text}}` etc. |
| `node:<id>/brief_rules` | yes | – | `extra_rules` for that stage |
| `node:<id>/rules` | **no** | 1200 | extra if/then rules |
| `node:<id>/examples` | **no** | 600 | sample phrasing |
| `tts:<node>` | yes | – | every `on_enter` tts / verbatim line |
| `tool:<node>/<tool>/description` | **no** | 600 | model-facing tool description |
| `hook:<node>/<tool>/msg/<key>` | **no** | 300 | one `what_to_do_next` text; the hook code holds the map between `# MSG-BEGIN`/`# MSG-END` as a flat JSON object read with `json.loads`. Text with `{` `}` is refused |
| `transition:<node>/<i>/intent` | **no** | 300 | `matches_intent` descriptions (there are few; most routing is enum-based) |
| `extract:<node>/<var>/description` | **no** (proposed addition) | 300 | extraction field description; enum values stay locked |
| everything else: code, URLs, methods, enums, body fields, conditions, graph, `test_variables` | yes | – | |

Growth budget: total unlocked + locked model-facing text may grow at most 15% per iteration.

## 6. Testgen key mapping (`testgen.py`)

`assemble.build(cfg, seed)` reads (via `cases.py`, `engine.py`, `assemble.py`):
`id`, `address`, `identity.{questions,max_wrong,swap_hint}`, `callback.{start,end,same_day}`, `bands[]`, `holidays`,
`outcome_map`, `queue_map`, `note_map`, `close_rule.{kind,order}`, `notes_on_restructuring`, `product_types.*.{enum,label,floor_field,last4_field,floor_pct?}`,
`account_fields`, `product_id_format`, `forbidden_before_verify[0]`, `multi_product`, `max_products`,
`sentences.{ai,scam,failed_id}`, **`now_dates`**.

| Key | Source |
|---|---|
| all canonical keys above | copied from our `policy.json` |
| `id` | `"tcc"`. The adapter adds `assemble.PREFIX["tcc"] = "T"` in memory |
| `now_dates` (missing in exported configs) | synthesized: 5 business days in the anchor month (the brief's example `now`, else the month of its first holiday, else the next month): a day before a holiday, a Friday, the last business day of a week, a Monday, and one at `callback.end` minus 40 min. Each is a business day, chosen with a seeded RNG |
| `product_types.*.floor_pct` (missing) | optional. Set seeded in [0.15, 0.35] only for types with a `last4_field` (card-like), so other types keep the instalment-multiple floors |
| plan sizes | `assemble.plan_for` is replaced in memory with a budgeted plan (default 36 cases): every family whose outcome keys exist, plus `Multi-product` when `multi_product` |

**Brief-specific dependencies in the generator**, and what the adapter does:

| Dependency | Action |
|---|---|
| `plan_for` keys on `"brief-a"`, `"brief-b"`, `"f6-corvid-memo"` | replaced |
| `PREFIX[cfg["id"]]` | extended |
| `identity_values`, `wrong_value`, `QNAME` know 6 field names | unknown field names get a generic wrapper (kind inferred from the API description / name: date, digits(n), year, alnum). If inference fails, the Identity and Declined families are dropped and logged |
| `Cal.attempt1_date` hard-codes "last business day of this week, roll if today" (capped at the deadline in `Policy.attempt1`) | if `attempt_plan[0]` is not `end_of_week_roll`, the Dates and Refusal families are dropped and logged |
| `next_weekday` / `this_weekday` semantics fixed | if `weekday_words` differs, the "next/this weekday" variants are dropped (the variant id is filtered after generation) |
| `callback_ok` days = today (if `same_day`) + next business day | if the brief's window differs (not expressible), Third party is dropped |
| `SINGLE_OUTCOME` / `to_brief` index `outcome_map`/`note_map`/`queue_map` | families whose keys are null are not planned |

No other brief values are in `engine/cases/assemble`. The name/company lists in `cases.py` are persona data, which is fine.
The adapter imports exactly `engine`, `cases`, `assemble` by putting `testbed/generator` on `sys.path` for the import
(then removing it). It asserts `configs`, `briefs`, `toolapi`, `write`, `validate` are not in `sys.modules`, and opens no file.

## 7. Failure modes the analyzer cannot see

Testgen's expected results come from **our** policy. A policy error (a wrong deadline, a wrong enum) makes the agent and
the oracle agree on the wrong thing, so the self-test loop cannot find it. Only the audit (Claude Code re-reading the
brief against `policy.json`) can. That is why the audit runs before compile and before the loop.

## 8. What stays unverified until live runs

- The platform's behaviour for: `max_node_turns` counting across global-node detours, the lifecycle close with baked
  vars, a post-hook writing vars that a following transition reads in the same turn (doc: "seen on 10 October"), and
  enum-routed forks with `min_confidence` 0.6.
- Extraction quality, audit quality, patch quality, judge agreement, time per iteration, cost per build.
