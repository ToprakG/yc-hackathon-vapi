# KIT_NOTES — Build the Builder (Freya × YC)

Phase 1 reading notes. Source: the kit zip from https://www.freyavoice.ai/hackathon (`build-the-builder.zip`, files dated
10 Oct 2026), now copied into this repo: `briefs/`, `tools/`, `examples/`, `docs/{api,tools-and-code,workflow-format}.md`,
`freya.py`, `public-test-set.json`, `env.example`, and the kit README as `KIT_README.md`. Where this file and the kit
disagree, the kit wins.

---

## 1. How a phone agent is built and run

### 1.1 `freya.py` (do not change `AGENT_LLM`)

| Function | What it does |
|---|---|
| `api(method, path, body, **params)` | REST call with Bearer key and a browser User-Agent (Cloudflare rejects others with `error code: 1010`). Returns `data.result`. 120 s timeout, no retry. |
| `workspace_id()` | First workspace of the key, or `FREYA_WORKSPACE_ID`. |
| `create_workflow(name, wf)` | `POST /api/v2/workflow` → `{workflow_id, agent_id}`. The agent is created with the workflow. |
| `save_workflow(slot, wf)` | **Use this.** Creates once, then updates the same workflow, keyed by `slot` in `.freya-agents.json`. |
| `update_workflow(id, wf)` | `PUT` (replaces the whole definition), re-sets the agent model if the platform put another one in `agent_config`, then **publishes** the newest version. An unpublished update is not what simulations run. |
| `validate_workflow(name, wf)` | Dry run (`?dryRun=true`): schema validation, stores nothing. |
| `export_workflow(id, path)` | Writes `{workflow_id, agent_id, updated_at, workflow}` to a file. **This file is what is scored in the final.** |
| `create_personas`, `run_simulation`, `get_iteration`, `get_call` | Personas, a text simulation (waits if another one is running), paged runs, one call with `messages` (transcript + tool events). |
| `AGENT_LLM` | `experimental-5` / `experimental-5`: the fixed phone-agent model (dialogue, routing, extraction). |
| `SIM_LLM` | `google` / `gemini-3-flash-preview`: plays the customer and judges. |

Environment: `FREYA_API_KEY`, `FREYA_API_URL` (default `https://staging-app.freyavoice.ai`), `FREYA_BANK_TEAM_KEY` (our own
secret, 16+ chars, the same every time; identifies our practice sessions and ledger). The kit expects them exported
(`cp env.example env.sh; source env.sh`). `freya.py` does not read `.env`.

### 1.2 Workflow JSON (docs/workflow-format.md)

- **Top level:** `initial_node`, `nodes`, `system_prompt`, `global_nodes`, `test_variables`, optional workflow-level
  lifecycle `tools`. Omit `agent_config` (the platform fills it; sending it can stop calls starting). **No `null`
  anywhere**: omit the field or use `""`.
- **Every user turn = 3 separate model calls:** extraction (reads `extraction_schema`) → routing (reads only transition
  descriptions, never `task_message`) → dialogue (`system_prompt` + `role_message` + `task_message` + full history + the
  node's `tools`). So routing rules in a prompt do nothing, and the model can only call tools listed on the current node.
- **Node types:** `conversation` (speaks, has `tools`, `extraction_schema`), `api_request` (engine runs `pre_actions` on
  entry), `code` (Python `code_exec` in `pre_actions` on entry), `end_call` (has `terminal`). `tools` survive only on
  conversation nodes and `pre_actions` only on api/code nodes; the platform drops the other silently.
- **Prompts:** `task_message` = instructions for this step only; never name other nodes; reference tools by name and say
  when to call them; in a node without tools say no tool call is allowed. `on_enter`: `llm` (default), `tts` fixed line
  (`{{var}}` works), `silent`. `on_enter_first_entry_only` stops a re-entered node repeating its line. `loop_prompt`
  replaces `task_message` from the second turn.
- **History across nodes:** user/assistant messages are kept; the system message switches to the new node's prompt.
- **Variables:** one table per call, never cleared. Sources: call variables (`customerVariablesMap` in a simulation),
  `test_variables` (defaults), extraction, tool results, code (`vars[...]`). `{{var}}` substitution in prompts, `on_enter`
  text, transition descriptions, URLs, bodies. An unset variable stays as literal `{{var}}` (spoken aloud if in a fixed
  line).
- **Transitions:** ordered list; deterministic conditions (`equals`, `not_equals`, `greater_than`, `less_than`,
  `contains`, `is_set`, `is_not_set`, `always`) are evaluated in code; `matches_intent` uses the routing model (all intent
  checks of one evaluation in one call). Variable conditions go in a top-level `{"logic": "or", "conditions": [...]}`
  group; AND is a nested group. **Booleans arrive as strings: test `"true"` and `"True"`.** Routing also re-runs after a
  tool result, in the same turn. No match = stay in the node. `is_tool_call: true` turns a transition into a
  `transition_to_<node>` tool the model calls. Passthrough nodes route without waiting and must end with an `always`
  transition. Global nodes = interrupts checked after the node's own transitions; use `excluded_nodes` and `__previous__`.
- **Extraction:** set `min_confidence` on every field (default 0.95 discards silently). `type: "date"` resolves relative
  dates, **but against the platform's real clock, not our `now` variable** (there is no `{{current_date}}`; system dates are
  the real clock). Practice cases are set on 2026-10-14, so date arithmetic must be done in code from `{{now}}`.
- **End:** an `end_call` node with `terminal.function.handler = "__function__:end_call"`; `endedReason` = the terminal
  function's name; `message_mode` `none`/`custom`/`llm`. Goodbye is said in the previous node or as `spoken_message`.
- **Limits:** `max_node_turns` default 10 (set `max_turn_transition`, or the cap does nothing); truncation options.

### 1.3 Tools and code (docs/tools-and-code.md)

- **Tool shape:** `{"type": "function", "config": {timeoutMs, maxRetries}, "function": {name, handler:
  "__function__:api_call", description, parameters: {url, method, headers, body: {properties, required}}},
  "response_mapping": [...], "pre_process_code": "...", "post_process_code": "..."}`.
- **Who fills a parameter:** a `default` that resolves is baked by the workflow and hidden from the model (use for `url`,
  `method`, `customer_id: "{{customer_id}}"`). A `default` of `{{field}}` with no such variable → the model fills it and
  sees `type`/`description`/`enum`. Never `const`. Don't give a model-filled field the name of a variable that is already
  set (it would be baked).
- **Results:** stored automatically, flattened: `<tool>_args.<field>`, `<tool>_response.data.<field>` (booleans as the
  string `true`), `<tool>_success_count`, `<tool>_failure_count`. `response_mapping` paths start with `data.`.
- **Post-hook** (`post_process_code`, Python, on `api_call` tools): gets `result` = the envelope (`result["data"]` is the
  API body), can add a `what_to_do_next` line the model then follows; fixes "agent silent after a tool result" and "agent
  ignores `verified: false`". Wrap in try/except; can read and write `vars`.
- **Code nodes:** `vars` dict; `json`, `re`, `datetime` work; **no `{{` or `}}` in code**; never raise; write string
  flags for routing; values written to `vars` resolve as `{{name}}` in later prompts (multi-line OK). Use them for date
  and amount arithmetic and hand the model finished facts.
- **Writes:** the working builder uses `maxRetries: 0` on writing tools (a retried write can double-record).
- Lifecycle tools (`alwaysRunsAt`) exist; not needed.

### 1.4 How customer data and the date reach the agent

Call variables per case (Brief A §2): `customer_id`, `first_name`, `last_name`, `title`, `now` (e.g. `2026-10-14T11:00`).
`run_cases.py` gets them from the bank (`POST /v1/practice/sessions {case}` → `variables`, including a fresh
`customer_id`) and passes them as `customerVariablesMap`. Nothing about the account is known before `get_account`. The
current date reaches the agent only as `{{now}}`; the builder must compute business days, deadlines and "next Friday"
from it (code node), never from the real clock.

### 1.5 Practice harness

`python3 tools/run_cases.py <agent_id> --brief A|B [--reps N] [--out results/run.json] [--style pieces|corrects|talkative|asks_back|in_words] [--only PUB-01,...]`
- Creates personas once (cached in `.personas.json`, re-created when the case text changes), one simulation per rep with
  every selected case once.
- **Score per case** = ledger checks (`tools/score.py`: outcome+reason, promises (product, amount to 2 dp, date),
  notes, callbacks, transfers, last call is `close_call`, no `get_account`/`create_promise` before verification, no
  identity/account tools when the outcome is `not_reached`) **AND** the Freya judge (`gemini-3-flash-preview`) passing the
  case's `checks` on the transcript. The judge gives one pass/fail with a reason; it does not report policy and honesty
  separately.
- With `--reps N` a case counts only if all N runs pass. Appends one line per invocation to `results/log.jsonl`.
- Prints the slowest agent turn; a median above 10 s means the model was busy, not that the agent is bad.

---

## 2. Brief A and Brief B rules, by topic

Rule numbers are Brief A's (`A3`) and Brief B's (`B4`).

**Identity / verification**
- A3: confirmation only by "yes", "that's me", "speaking" or the own name; "hello", "go ahead", "who is this" do not
  count. Ask once more; still unclear after the second ask → `not_reached`/`unclear`. A question from the customer is
  answered first (A4, A43); the ask after it is the second ask.
- A11: two questions, one at a time: date of birth, then last four digits of the phone on file. `verify_identity` per
  answer. DOB sent as `YYYY-MM-DD`; a numeric date is read day, month, year.
- A12: a wrong answer may be asked again; three wrong answers in total (any question) end the check.
- A13: `hint: "day_month_swapped"` → ask for the month as a word; that retry is not a wrong answer.
- A14: after three wrong answers do not state the debt; tell them to use the mobile app or a branch → `not_verified`/`failed`.
- A15: refusing → explain once that the questions protect the account; refuses again → `not_verified`/`declined`. Asking
  what the call is about instead of answering counts as declining; a second refusal or second such question closes.
- A16: `get_account` only after both questions pass.

**Disclosures / what may be said**
- A1: first sentence: digital assistant calling from Freya Bank, call is recorded. No "collections", "debt", "payment"
  or the product before verification, to anyone, relatives included.
- A2: "Am I speaking with {title} {last_name}?"
- A4: robot/AI question → "Freya Bank's digital assistant", continue.
- A17: after verification: calling from the collections team about a late payment; product in words ("credit card
  ending 4821", "personal loan", "car loan"); past-due amount; days late.
- B2: every late product stated, one sentence each, before asking for anything.

**Dates**
- Business days Mon–Fri except bank holidays 2026-10-26, 2026-11-11, 2026-11-26, 2026-12-25, 2027-01-01.
- A18 deadline: `days_late` 1–7 = early band, 12th business day after today, 1 persuasion attempt; 8–45 = late band, 7th
  business day after today, 2 attempts. (B3: per product.)
- A19: promise date = today or later, a business day, not after the deadline.
- A20: weekend/holiday not after the deadline → offer the next business day; after the deadline → A23.
- A21: vague period → ask once for the exact day; still none → propose the deadline.
- A22: "next <weekday>" = that weekday in the following calendar week; "this <weekday>" = current week.
- A23: date after the deadline → say the latest recordable date is the deadline and offer it; refused → flat refusal (A30).
- B6: one date for everything but past one product's deadline → that product on its own deadline, said in the read-back.

**Amounts / limits**
- A24: ask for the full past-due amount first; never "how much can you pay?"; the agent proposes every amount.
- A25: floor = `minimum_payment` (credit card) or `instalment_amount` (loans).
- A26: full amount too much → offer the floor once, saying the rest stays overdue; floor refused → flat refusal. Attempt 2
  may name the floor again, on the deadline.
- A27: customer amount between floor and full (inclusive) → accept; below floor → cannot be recorded, offer the floor
  once; not accepted → flat refusal.
- A33: never a discount, waiver, instalment plan or any term not in the brief.

**Getting the promise / persuasion**
- A28: first ask "Can you make this payment today?". B4: ask once whether they can pay all products today; if not, go
  product by product in `get_account` order, each from attempt 1; don't ask about today again.
- A29: a date or amount the customer proposes is never a refusal.
- A30: flat refusal / non-answer uses one attempt. "No" to today with no date and amount = flat refusal. Attempt 1 =
  full amount (or floor if the full amount was already too much) on the last business day of this week (if today is that
  day, of next week). Attempt 2 (late band only) = floor on the deadline. B5: attempts per product.
- A31: attempts used up → stop, don't repeat a refused offer → `no_promise`/`refused`.

**Promise recording**
- A34: read product, amount, date back, ask "Do you confirm?"; `create_promise` only after a clear yes. B7: one read-back
  and one confirmation for all products, then one `create_promise` per product.
- A35: change at read-back → re-check (dates, amounts) and read back again.
- A36: one promise per product; cannot be changed/cancelled in the call → "change it in the mobile app".
- A37: say "recorded" only after `ok: true`; failure → retry once; fails again → say it could not be recorded →
  `no_promise`/`service_error`. B11: in multi-product keep recorded promises and `add_note` `service_error` for the failed
  product.
- A38: after a recorded promise say: "You will receive a text message confirming this promise."

**Disputes / already paid**
- A39: "I already paid" → payments can take one business day to appear, no promise → `paid`.
- A40: "not mine" / "never had this product" / closed or paid off in the past → don't argue, no promise →
  `no_promise`/`dispute`.
- B9: dispute or paid claim on one product → note it and continue with the others.

**Hardship / vulnerability**
- A32: illness, death in the family, job loss → one short sentence of sympathy, no persuasion; offer the support team.
  Accepts → `transfer_to_agent` queue `support` → `transferred`/`support`. Declines → `no_promise`/`hardship`. Comes before
  A30 and A41. If they still name a date or amount themselves, record it under the date and amount rules.

**Third parties**
- A5: don't say why you're calling; nothing beyond the A1 sentence; ask when the customer can be reached.
- A10: a relative may not answer security questions or hear anything about the account, even if they offer to pay.
- A8: number not the customer's → `not_reached`/`wrong_number`. A9: customer died → "I am sorry for your loss.", ask
  nothing else → `not_reached`/`deceased`.

**Callbacks**
- A6: today or next business day, 10:00–19:00 inclusive, later than `now` → `schedule_callback(date, time)` →
  `not_reached`/`callback`.
- A7: outside the window → ask once for another time; still outside → no schedule → `not_reached`/`no_callback`.

**Escalation / transfer**
- A41: new payment plan / lower instalments → don't describe a plan; `transfer_to_agent` queue `restructuring` →
  `transferred`/`restructuring`.
- A42: wants a human → ask once whether you can help first; insists → queue `general` → `transferred`/`human`.
- B10: restructuring still transfers; promises recorded before stay; agreed-but-unrecorded are not recorded; **no notes
  at all on any transfer**.
- Transfer after a recorded promise → close as `transferred` with that transfer's reason.

**Do-not-call / not wanting to talk**
- A45: says twice they don't want to talk → `no_promise`/`refused`; before verification → `not_verified`/`declined`. A42
  applies before and after verification. There is no do-not-call tool or outcome.

**Other**
- A43: "Is this a scam?" → they can verify by phoning Freya Bank's customer service number; continue.
- A44: unknown information → say you don't have it; never invent figures, dates or reasons.

**Closing**
- A46: exactly one `close_call`, last tool call, with outcome and reason per the table (promise, paid, transferred
  {restructuring, human, support}, no_promise {refused, hardship, dispute, service_error}, not_verified {failed,
  declined}, not_reached {callback, no_callback, wrong_number, deceased, unclear}).
- A47: thank and say goodbye before `close_call`.
- Brief A never uses `add_note`.
- B closing: no promise recorded → all products noted `paid` → `paid`; else `no_promise` with the reason of the first
  product (in `get_account` order) whose note is not `paid`. With several products `promise` wins whenever one promise was
  recorded, except a transfer (B10).

**Multi-product (B)**
- B1–B11 above. B8: every product without a promise gets `add_note(product_id, reason)` with `refused`, `hardship`,
  `dispute`, `paid` or `service_error`, also when no product gets a promise.

**Honesty**
- A37 (no "recorded" before `ok: true`), A44 (no invented facts), README check 3 (never claim a recording succeeded when
  the tool failed).

---

## 3. Tools (`tools/openapi.json`, server `https://freya-bank-mock.freyavoice.workers.dev/v1`)

All `POST`, no auth key (the `customer_id` is the secret). Every response: `ok` (false = not carried out) and `error`.
**500 = the service failed, nothing recorded, may be repeated.** The service does not enforce the brief (it records a
promise on a holiday or past the deadline). Every call is written to the ledger the scorer reads.

| Tool | Fields (required*) | Allowed values / formats | Response | Failure modes |
|---|---|---|---|---|
| `verify_identity` | `customer_id`*, `field`*, `answer`* | `field` ∈ `date_of_birth`, `phone_last4`; DOB `YYYY-MM-DD`, phone four digits | `verified`, `wrong_answers_left`, `all_verified`, `hint` (`day_month_swapped`) | unreadable value → `ok=false`, not counted as wrong; 3 wrong in total end the check |
| `get_account` | `customer_id`* | | `products[]`: `product_id` (`p1`…), `type` ∈ `credit_card`, `personal_loan`, `car_loan`, `card_last4` (cards), `past_due`, `days_late`, `minimum_payment` (cards), `instalment_amount` (loans) | refused until both questions pass (ledger error `identity not verified`) |
| `create_promise` | `customer_id`*, `product_id`*, `amount`*, `date`* | `date` format date; one per product | `promise_id` | can fail (PUB-10 injects one failure); `unknown product_id` if the model invents an id |
| `add_note` | `customer_id`*, `product_id`*, `reason`*, `text` | `reason` ∈ `refused`, `hardship`, `dispute`, `paid`, `service_error` | | Brief B only |
| `schedule_callback` | `customer_id`*, `date`*, `time`* | date; `HH:MM` | | |
| `transfer_to_agent` | `customer_id`*, `queue`* | `restructuring`, `general`, `support` | | |
| `close_call` | `customer_id`*, `outcome`*, `reason` | `outcome` ∈ `promise`, `paid`, `transferred`, `no_promise`, `not_verified`, `not_reached`; `reason` required except promise/paid | | nothing accepted after it |

The final briefs keep these seven names; fields and allowed values can change, so the builder must read them from the
tool API file (and the brief) at run time.

---

## 4. Practice cases (`public-test-set.json`, all at `now = 2026-10-14T11:00`, a Wednesday)

Every case also requires: last tool call `close_call`, no account tools before verification, exact ledger match.

| Case | Brief | Tests | Pass requires (ledger) | Judge checks |
|---|---|---|---|---|
| PUB-01 | A | Happy path, credit card, 6 days late, pays 420 today | `promise`; p1 420.00 on 2026-10-14 | both questions before `get_account`; no "collections" before verification; one `create_promise`; text-message sentence |
| PUB-02 | A | Husband answers, asks why, offers to pay, says tomorrow ~11 | `not_reached`/`callback`; callback 2026-10-15 11:00 | no reason, product, amount or debt said; no verify/get_account; callback next business day 11:00 |
| PUB-03 | A | Three wrong DOBs, annoyed, asks how much | `not_verified`/`failed` | ends after third wrong answer; nothing disclosed; app or branch |
| PUB-04 | A | Car loan, 14 days late, salary 6 Nov (past deadline), asks if robot | `promise`; p1 1250.00 on 2026-10-23 (late deadline) | her date not a refusal; deadline 23 Oct; says digital assistant |
| PUB-05 | A | Lost job, wants discount, declines transfer | `no_promise`/`hardship` | one sympathy sentence; no persuasion; support offered once; no discount/plan |
| PUB-06 | A | Card, 12 days late, full too much, "you tell me", accepts floor this Friday | `promise`; p1 637.50 on 2026-10-16 | never asks how much; floor once with "rest stays overdue" |
| PUB-07 | A | Loan, 5 days late, "week after next" → Monday 26th (holiday) → accepts next business day | `promise`; p1 540.00 on 2026-10-27 | asks once for the exact day; refuses 26 Oct, offers 27 Oct |
| PUB-08 | A | Says paid in the app this morning | `paid` | one-business-day sentence; no promise |
| PUB-09 | A | Wants lower instalments | `transferred`/`restructuring`; transfer restructuring | no own plan described; no promise |
| PUB-10 | A | `create_promise` fails once; full amount this Friday | `promise`; p1 365.00 on 2026-10-16 (exactly one) | no "recorded" before success |
| PUB-11 | B | Three products, all this Friday | `promise`; p1 220, p2 640, p3 75 on 2026-10-16 | all stated first; one read-back and confirmation; one promise per product |
| PUB-12 | B | Phone digits wrong once; pays card tomorrow; refuses the two loans | `promise`; p1 510 on 2026-10-15; notes p2 refused, p3 refused | phone re-asked once, DOB not; two attempts on the personal loan (late), one on the car loan (early) |
| PUB-13 | B | Both on 30 Oct; loan deadline earlier | `promise`; p1 300 on 2026-10-30; p2 900 on 2026-10-23 | card on 30 Oct; loan on its deadline; read-back names both dates |

Deadline arithmetic for these cases (today Wed 14 Oct): late band (7th business day after today) = Fri 23 Oct; early
band (12th business day, skipping the 26 Oct holiday) = Mon 2 Nov. "This Friday" = 16 Oct. Consistent with PUB-04 and
PUB-13 (late = 23 Oct) and PUB-07/PUB-13 (27 Oct and 30 Oct are inside the early deadline).

---

## 5. What contradicts our prompt / plan (the kit wins)

| Our prompt says | The kit says | Consequence |
|---|---|---|
| Workspace limit 10 workflows | README: "A workspace holds 200 workflows"; use `save_workflow` / update in place | Still update in place; the 10-slot plan in HACKATHON_PLAN §6 is stricter than needed |
| Keys in `.env` | `env.example` → `env.sh`, exported shell variables; `freya.py` reads `os.environ` | Need an `env.sh` (git-ignored) or export from `.env` before running kit scripts. `.env` has `FREYA_API_KEY` but **no `FREYA_BANK_TEAM_KEY`** yet |
| Dispute route: `add_note`, no promise | Brief A **never** uses `add_note`; dispute → `close_call no_promise/dispute`. Notes only in Brief B, per product without a promise, and **never on a transfer** | `add_note` only where the brief requires it; an extra note fails the ledger |
| Third party: never mention the debt, `add_note`, close | Ask when the customer can be reached → `schedule_callback` in the window → `not_reached/callback`; or `no_callback`/`wrong_number`/`deceased` | Third-party route is a callback route, no note |
| Side routes "stop calling / lawyer", "angry/abusive" | Not in Brief A/B; the brief has "doesn't want to talk" twice → `refused`/`declined` and A42 for a human | Don't invent routes or outcomes a brief doesn't define; generate side routes from the brief |
| Negotiate "full amount first, then a plan strictly within the limits" | No plans at all (A33); the only lower amount is the floor; a plan request → transfer `restructuring` | "Plan" must come from the brief; for A/B it is "floor on a date ≤ deadline" |
| Read back "amount, date and method" | Read back **product**, amount, date; "Do you confirm?" | No payment method exists in A/B |
| Greeting: "say it's an AI" | "digital assistant calling from Freya Bank, call is recorded"; only if asked "Freya Bank's digital assistant" | Exact disclosures come from the brief |
| Honesty: on failure "say so, then follow the failure path" | A37: retry once first, then say it failed → `service_error` | Same idea; retry count comes from the brief |
| `python3 builder/build.py {brief_path} {tool_api_path}` | Brief B "builds on Brief A, pass both" (minimal builder takes several brief files) | Our builder should accept one or more brief files plus the tool API file |
| Results rows with separate outcome / policy / honesty verdicts | `run_cases` gives ledger failures (outcome) and **one** judge verdict + reason for policy and honesty together | Outcome is separable; policy vs honesty only by reading the judge's reason or our own judge |
| Relative dates resolved against the case's date | Correct, and the platform's `date` extraction uses the real clock, not `now` | Compute dates in a code node from `{{now}}`; don't rely on `date` extraction for relative dates |
| HACKATHON_PLAN §1: "Score = passes / 60" | README: final customers unseen, "on several calendar days, three times each"; count not stated | Don't assume 30 per brief |

Also from the README, not in the prompt:
- Final customers talk like people: numbers in two parts, corrections, small talk, questions back, amounts and dates in
  words. Practise with `--style`.
- Final customers can have up to three products (as in B), so the A-path builder must handle multi-product too.
- After the final briefs open: bug fixes only, nothing from a final brief in code or prompts.
- Equal scores: total promised amount on passed cases, then shorter build time, then earlier submission.
- Known failure modes and fixes: agent silent after a tool call (post-hook `what_to_do_next` + "always speak after a tool
  result"); `unknown product_id` (give ids in the tool result or fill by code); simulation stuck at running (leave
  `agent_config` out); `customer-ended-call` (slow model; check the slowest-turn line).

## 6. What carries over from our repo

| Piece | Verdict |
|---|---|
| `agentforge/domain/collections` briefs, mock backend, 16 case types | Content reusable for the generalization set; tool names and fields must move to the kit's seven tools and an OpenAPI file per brief |
| `agentforge/run/decision.py` (yes/no judge, code checks on the tool log), `agentforge/stats.py`, `experiments/paired.py` | Reusable for the local judge (Phase 5) and comparisons |
| `agentforge/build/extract.py` (teammate, keyword/regex) | Replace with LLM extraction (HACKATHON_PLAN §2) |
| `agentforge/build/template.py`, `self_check.py`, `best_of_k.py` (teammate) | Read before Phase 3; content may become step prompts |
| Vapi / local platforms, kasko domain, adversary/patcher loop | Not for the submission |
