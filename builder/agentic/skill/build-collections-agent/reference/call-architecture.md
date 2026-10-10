# Call architecture for a collections call

A menu of stages. Keep the stages the brief has, drop the ones it does not, and fill every value from the brief and
the tool API. Nothing here is a value: words in `<angle brackets>` are slots.

The scoring checks three things on every simulated call: the **bank records** (which tools were called, with which
values, in which order), **policy** (the brief's rules) and **honesty** (nothing claimed that did not happen). So the
design goal is: **every record and every number is decided by code or by a routed state, not by the model's memory.**

## Principles

1. **Deterministic first.** Dates, deadlines, amounts, attempt counts, callback windows, product order and the final
   outcome are computed in code nodes and hooks from `vars['now']` and the tool results. The model gets finished
   facts as text and picks from them.
2. **Route on tool results**, never on what the model claims. A post-hook turns each result into a string state.
3. **One stage per node** where a stage has strict rules (right party, identity, negotiation). Interrupts that can
   happen anywhere are global nodes.
4. **Say less.** One or two short sentences per turn; one question at a time.
5. **Honesty.** Say a record was made only after the tool returned success. Never invent figures, dates, terms or
   reasons. If something is unknown, say so.

## Stage 0: setup (code node, `initial_node`)

- Parse `now` (`parse_now`), the brief's holiday list, today's spoken date.
- Precompute what the early stages need: the callback window as text (today and/or the next business day, the hours,
  "later than now"), the allowed callback days as ISO dates.
- Set pessimistic defaults for the close state (`close_outcome`/`close_reason` or the single code) so a call that ends
  early still closes correctly: usually the brief's "not reached, unclear" row.
- Set every variable a later prompt or condition reads, with a fallback.

## Stage 1: opening and right-party check (conversation)

- `on_enter` **tts** with the brief's opening, word for word where the brief fixes it (disclosure that it is an
  automated or digital assistant, the bank's name, recording notice) and the right-party question with the brief's
  address form (e.g. `{{title}} {{last_name}}`).
- `system_prompt` + task: nothing about the reason for the call, the product, money or the forbidden words before
  verification. This holds for anyone on the line.
- Extract who answered as an enum: `customer`, `someone_else`, `wrong_number`, `deceased`, `unclear` (only the values
  the brief needs). Only the confirmations the brief lists count as `customer`.
- The brief's ask limit ("ask once more", "answer their question first, the next ask is the second"): a
  `max_node_turns` + `max_turn_transition` to the "unclear" ending, or an extracted counter.
- Robot/AI question and "is this a scam?" are global nodes with the brief's sentence, returning to `__previous__`.

## Stage 1b: someone else / wrong number / deceased

- Someone else: say nothing beyond the opening. Ask when the customer can be reached. Only times inside the computed
  window are bookable (day rule, hours both ends as the brief says, later than `now`). Book with
  `schedule_callback` in the API's format (separate date and time, or one datetime field). One retry ask, then the
  brief's "no callback" ending.
- Relatives may not answer security questions or hear account details, even when they offer to pay.
- Deceased: the brief's sentence verbatim, nothing else, then its ending. Wrong number: its ending.

## Stage 2: identity (conversation, tools: `verify_identity`)

- Ask the questions in the brief's order, one at a time. One `verify_identity` call per answer, with the API's field
  value for that question. Normalise the answer in a pre-hook to the format the brief/API asks for (dates as
  `YYYY-MM-DD`, numbers-only dates read day/month/year in the brief's convention, digits only, upper case, ...).
- A post-hook turns the result into `id_state` (`passed`, `retry`, `failed`) and a `what_to_do_next`:
  correct → next question; wrong → the brief's retry rule; a hint the API returns (e.g. a swapped day/month) → the
  brief's instruction for it, which may not count as a wrong answer; the last allowed wrong answer → `failed`. Use
  the API's own counters (e.g. answers left, all verified) rather than counting in the model.
- Declining: explain once why the questions are asked (the brief's wording); the brief's second refusal (often also
  "what is this about?" instead of an answer) → the "declined" ending.
- Failed: say only what the brief allows (e.g. where to go instead). No account details.
- Exclude this node from global nodes that would leak or derail (e.g. a "wants a person" interrupt may still apply if
  the brief says it applies before verification: then keep it).

## Stage 3: account (api_request, `get_account` in `pre_actions`)

- `response_mapping` of the product list to a variable (`data.<list field>`); route on `<node>_failure_count`.
- Retry only as the brief or the API's 5xx wording allows ("the call may be repeated"): `maxRetries` on this read, or a
  second api node. After the last failure: say it truthfully and take the brief's service-error ending.

## Stage 4: facts (code node)

Per product, in the API's order:
- Field names from the API (`account_fields`), product type → spoken label (with the last digits where the brief
  says), floor field per product type, past-due amount, days late.
- Band from days late, deadline = N-th business day after today, attempts allowed, the attempt-1 date by the brief's
  rule (e.g. last business day of this week, next week's when today is that day, never after the deadline), the
  attempt-2 proposal.
- A **date table** the model can look up instead of computing: for today and the next 2–3 weeks, each date with its
  weekday, whether it is a business day, whether it is within each product's deadline, and how "this <weekday>" and
  "next <weekday>" resolve under the brief's definition. Include the next business day after each weekend/holiday.
- Amounts in the brief's currency and format; cents converted with `round()` when the API wants minor units.
- Write: `facts_text` (finished, human-readable, used verbatim in prompts), `facts_json`, `product_count`, string flags.

## Stage 5: negotiation and promise (conversation)

Tools: `create_promise` (and `add_note`, `transfer_to_agent`, `schedule_callback` if the brief routes from here).
Implement the brief's flow, typically:
- State the debt: the brief's framing sentence, each product in one sentence (product, amount, days late).
- The brief's first question (e.g. whether the customer can pay today), full amount first, never "how much can you
  pay?" when the brief forbids it.
- A date or amount the customer proposes is not a refusal: check it against the date table and the floor.
  Weekend/holiday → next business day; after the deadline → offer the deadline; vague → ask once, then propose the
  deadline. Amount between floor and full → accept; below the floor → offer the floor once; too much → the floor once.
- Flat refusals use persuasion attempts, counted per product. Attempt proposals come from the facts. When attempts are
  used up: stop, do not repeat a refused offer, take the refusal ending.
- Read back what the brief lists (product, amount, date) with its confirmation question; call `create_promise` only on
  a clear yes. A changed value is re-checked and read back again.
- `create_promise` post-hook: on success count it, set the close state, and tell the model to say the brief's
  confirmation sentence verbatim; on failure apply the brief's retry rule, then the truthful failure line and the
  service-error state.
- Multi-product: state all products first; one "all today?" question; then product by product in API order, attempts
  per product; one date for everything that is past one product's deadline → that product on its own deadline, said in
  the read-back; read back all promises together, one confirmation, one `create_promise` per product. A code node that
  picks the next product (`current_*` variables) keeps the loop honest.
- Products without a promise get `add_note` with the brief's reason, if the brief uses notes, and only where it allows
  (some briefs forbid notes around transfers; some require one before a transfer).

## Stage 6: side routes (global nodes or branches)

Map each to the brief's handling, its sentence and its close row:
- hardship (illness, bereavement, job loss): sympathy sentence, no persuasion, offer the brief's team, transfer or not.
- dispute / not mine / closed long ago: no argument, no promise, note or close as the brief says.
- already paid: the brief's sentence about processing time, no promise.
- restructuring / new plan / lower instalments: no plan talk, transfer to the brief's queue; what happens to promises
  already recorded and those agreed but not recorded.
- wants a person: the brief's "ask once whether you can help first", then transfer; before or after verification.
- scam question, robot question, a question the tools cannot answer ("I do not have that information").
- refuses to talk (twice), before vs after verification → different endings.
- forbidden offers: no discounts, waivers, plans or terms the brief does not list.

## Stage 7: closing

- Thank and say goodbye **before** the close record when the brief asks it.
- The close record: exactly one, last, with the brief's outcome/reason (or code). Compute it deterministically:
  keep `close_*` state in vars from post-hooks and code nodes, and resolve the brief's precedence in the close tool's
  pre-hook: e.g. any recorded promise wins unless a transfer followed; a transfer reason wins over a promise; with no
  promise, all products paid → paid, else the brief's rule (first non-paid product's reason, or a priority order).
- Lifecycle form (`alwaysRunsAt: ["end_of_call"]`) guarantees exactly one close even when the customer hangs up.
- `end_call` nodes per ending; their `function.name` names the outcome.

## What to leave to the model

Only conversation: wording, empathy, answering questions from the facts, choosing among routed options. Never
arithmetic, calendar logic, enum spelling or the close outcome.
