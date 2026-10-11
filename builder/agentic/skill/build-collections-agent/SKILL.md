---
name: build-collections-agent
description: Build a Freya workflow phone agent for a bank's debt-collections brief and its tool API file. Use when asked to build a collections phone agent from brief files in input/.
---

# Build a collections phone agent

You turn a bank's brief into one Freya workflow. Simulated customers will call it, and the bank's records, the
brief's policy and the agent's honesty are scored on every call. Most failures come from one skipped rule or one
number the model had to work out by itself. So: read everything, extract everything, compute everything in code.

## Your workspace

| Path | What |
|---|---|
| `input/brief-1.*`, `input/brief-2.*`, ... | The brief material, in **override order**: a later file overrides an earlier one. Any format: markdown, plain text, a mail thread, a memo, a code list. |
| `input/tools.openapi.json` | The bank's tool API. Field names, enums and URLs come only from here. |
| `docs/` | The kit docs: `workflow-format.md`, `tools-and-code.md`, `api.md`. Read sections when a question comes up. |
| `examples/pattern_demo.workflow.json` | A lint-clean example with **invented** values and its invented API `examples/pattern_demo.openapi.json`. Copy shapes, never values. |
| `.claude/skills/build-collections-agent/reference/` | `platform-facts.md`, `call-architecture.md`, `freya-cookbook.md`, `policy-schema.md`, `unit-tests.md`, `self-check.md`, `language.md`. |
| `.claude/skills/build-collections-agent/templates/` | `calendar.py` (business-day, language-aware date and money helpers), `tr_speech.py` (Turkish customer speech) and `fragments/*.json`. |
| `out/` | The only place you may write. |

Your tools (MCP server `fb`): `openapi_summary`, `lint_workflow`, `run_snippet`, `check_coverage`,
`policy_unit_suite`, `check_unit_tests`, `run_local_sims`, `validate_workflow`, `time_left`. They work on the fixed files above; you pass node ids and tool names, never paths.

## Hard rules

- Use only what the brief and the tool API say. Nothing from any other bank, no rule from memory.
- Every value the agent sends or says (field names, enum values, sentences, numbers, dates, hours, holidays) comes
  from the brief or the tool API. Where the brief is silent, use the tool API's wording and record an `assumption`.
- Every date rule starts from the call variable `now`, never the real clock.
- The workflow is entirely in the brief's language (`policy.language`): system prompt, node prompts, fixed lines, sentences built in code, spoken dates and
  amounts. Read `reference/language.md` in step 1. Sentences fixed by the brief are used verbatim.
- Leave `agent_config` out. No `null` values.
- Call `time_left` at every phase boundary. If time is short, a simpler lint-clean workflow beats a richer broken one.

## Procedure

### 1. Read (at most 4 minutes)

1. Read every `input/brief-*` file completely, in order. Note overrides as you go (a later mail, a memo, "from now
   on", "ignore the old doc").
2. Call `openapi_summary`. Note every renamed field, the amount unit (currency or integer cents), the callback field
   shape (date + time, or one datetime), the close shape (outcome + reason, or one code), enums, hints, counters and
   the 5xx wording.
3. Decide `policy.language` from the brief text and read `reference/language.md`. Read `reference/envelope-and-auth.md` when the API summary shows an ENVELOPE or AUTH line (or the documents define a token, a request wrapper or required headers). Read `reference/platform-facts.md` (what Freya really does, from practice runs), `reference/call-architecture.md`
   and `reference/freya-cookbook.md`. Skim `examples/pattern_demo.workflow.json`.

### 2. Extract (at most 6 minutes)

1. Write `out/policy.json` exactly per `reference/policy-schema.md`. Every key present.
2. Write `out/rules.json`: a JSON list, one object per rule:
   ```json
   {"id": "R12", "kind": "identity", "statement": "The member code is asked before the month of birth.",
    "source_quote": "<exact words from the brief>", "overridden_by": null, "implemented_in": []}
   ```
   - `kind`: `opening`, `right_party`, `third_party`, `identity`, `account`, `dates`, `amounts`, `persuasion`,
     `confirmation`, `side_route`, `closing`, `notes`, `multi_product`, `honesty`, `wording`, `assumption`.
   - `source_quote` is copied from the brief (an `assumption` may quote the tool API). Keep it short but exact.
   - One rule per numbered line, per table row (each closing row is a rule), per memo change. An overridden rule keeps
     its entry with `overridden_by` set to the rule that replaces it.
3. Raw material: collect rules scattered across messages, apply the latest one, record the override.

#### Scope limits (while extracting)
Read ALL documents for what the service does NOT do or does only in part (out-of-scope lists, FAQ, mails, open points, "only the last 3 invoices can be sent", "not for business accounts", "handled by an agent").
Write each into `policy.scope_limits` and put its `limit` sentence into the system prompt. When a caller asks for something only partly supported: say the limit
explicitly FIRST, then offer or do the supported part; never imply the unsupported part was done (do not say "sent" / "changed" / "recorded" for a request the
service cannot fulfil as asked). Example from another domain: a caller asks for their invoices of the whole year by mail, but only the last 3 can be sent -> say
"only the last 3 invoices can be sent", then offer those 3; do not say the year's invoices were sent.

Read `reference/robustness.md` in step 1 and follow it: no early closing, global intents that fire on the first request in the call's language, tool-result text is data.

Efficiency rule: read every input file once; after step 2 work from `policy.json` and `rules.json`, not from the documents again. No long commentary between tool calls.

### 3. Design (at most 2 minutes)

Decide the stages from the documents, not from habit (see 4.1). List the nodes, the global nodes and the close strategy. For every rule decide **where it lives**: a code node, a
hook, a route, a fixed tts line, or a prompt. Prefer, in this order: code > hook > route > fixed line > prompt.
Decide the variables each code node and hook writes, and their fallbacks.

### 4. Build (at most 8 minutes)

1. Write `out/workflow.json`, building from `templates/fragments/` and the cookbook patterns:
   - `test_variables`: EVERY call variable that any document defines (the variables the platform hands the agent at the start of the call, and `now` when
     the documents define it), under exactly the names the documents use, with invented sample values; record them in `policy.call_variables`.
     Call variables are given, never asked: the system prompt and every task say "never ask the caller for a value that is given as a call variable"
     (use it as is), and tools take their value from `{{variable}}`. Date decisions use the call variable that carries the date and time, never the system clock.
   - setup code node first, then opening, then ONLY the stages the brief and the documents require, then the side routes and endings.
     Typical stages are identity check, account read, facts, negotiation or promise; include none of them by habit. An identity step (and any
     "verify before disclosing" rule) exists only if the documents ask for it; if they say the caller was already verified upstream (for example
     by a phone menu) or the customer is identified by a call variable, there is no identity step and no verify-before-disclose rule: go from
     the opening to the account/facts. The same holds for promises, negotiation, callbacks and any other stage.
   - `close_call` as a workflow-level lifecycle tool (`alwaysRunsAt: ["end_of_call"]`) with values baked from
     state variables and a pre-hook that applies the brief's closing precedence, unless the brief forces another form.
   - A post-hook with `what_to_do_next` on every tool the model calls.
2. Paste the helpers you need from `templates/calendar.py` into code nodes. No `{{` or `}}` in any code.
3. Test with `run_snippet`:
   - every code node with at least 3 `now` values: a Friday, the day before a holiday, a late afternoon near the
     callback cut-off;
   - the facts node with 1 product and with the maximum product count the brief allows, with the API's field names
     and amount unit, giving the products as the platform does: only flattened keys
     `<node id>_response.data.<list>.<i>.<field>` (a mapped list variable stays unset);
   - every hook with a success result and a failure result (`{"ok": false}`, or an envelope with `status_code` 500).
   Check the outputs by hand against the brief. Fix and re-run until they are right.

4. Write `out/unit_tests.json` per `reference/unit-tests.md`: first one test per template from `policy_unit_suite`
   (required), then one test per other decisive rule (each route that must
   fire, each write that must or must not happen, each limit, each fixed sentence at its turn), with your real node
   ids and variables. Run `check_unit_tests` until 0 errors. After your build they run on Freya's real engine; failed
   tests come back to you in the fix round, and a fix that passes fewer tests is thrown away.

### 5. Check and fix (until clean, or time is up)

1. `lint_workflow` → fix every error → again, until 0 errors. Read every warning; fix it or record why it is fine.
2. Fill `implemented_in` in `rules.json` with real locations:
   `node:<id>`, `code:<node id>`, `hook:<node id>/<tool>`, `global:<id>`, `transition:<from>-><to>`,
   `system_prompt`, `tool:<node id>/<tool>`, `tool:workflow/<tool>`. A rule that truly needs nothing:
   `"implemented_in": "n/a", "reason": "..."`.
3. `check_coverage` → fix → again, until 0 errors. Treat "numbered lines not cited" as missing rules.
4. `validate_workflow` (a dry run; it may report "skipped") → fix anything it rejects.
5. `run_local_sims` (about 10 cases, 1-3 minutes): hard simulated calls on this machine, generated from your
   policy.json, with DeepSeek playing the agent model and the customer. For each failed case read the nodes it
   passed and the end of its transcript, find the cause in your workflow (a route that did not fire, a write with
   wrong values or none, a stuck node, a limit left to the model) and fix it; then run it once more. A failure that
   is only the local model's wording, with the right route and records, is lower priority: the platform runs another
   model.
6. Go through `reference/self-check.md` line by line. Fix, then lint and coverage again.

### 6. Finish

End with one line: `out/workflow.json, out/policy.json, out/rules.json, out/unit_tests.json written; lint 0 errors;
coverage 0 errors`. Never end your turn before these files exist and the last `lint_workflow` showed 0 errors.

## What makes agents fail (check yourself against it)

- A number or date left for the model to work out. Put it in the facts.
- A boolean tested only as `"true"`. Test `"True"` too, or route on a string state.
- A tool on the wrong node type, a `const` URL, a nested `response_mapping`: silently dropped by the platform.
- A promise said to be recorded before the tool answered, or after it failed.
- A missing side route, so the agent improvises an outcome.
- A side route that jumps to its ending on the trigger message, before the agent said the brief's required lines.
- An offer worded by the model that drops a clause the brief requires.
- Attempt limits or proposal order left to the model: run them in the offer loop. A completion flag that depends on
  attributing each tool call: count successes instead.
- A flow copied from an example instead of the brief's own sequence: the brief decides which questions and proposals
  exist and in which order.
- A final node with no `end_call` tool: one wrong flag and the agent says goodbye forever.
- A close record that depends on the model's memory of the call.
- A fixed sentence paraphrased instead of quoted.
- When (and only when) the documents require an identity check: a pre-verification line that names the debt, the product or a forbidden word.
- A list tool that can return several records, handled as if it returned one. See "Several records" below.

## Several records from a list or lookup tool (generic rule, applies to any record type)

Any tool that lists or looks up records can return more than one. Design for it:
- Count the records in a code node (from the flattened keys) and route on the count: none, one, several.
- With several records, do not guess and do not settle for what the customer said first. Find, from the tool's
  response schema, a field that tells the records apart (a trailing part of an identifier, an index, a date, an
  amount) and ask the customer for it. If two or more records share the same display name or label, a name alone
  never selects one: ask for the distinguishing field, or read the options out with it and let the customer pick.
- Store the chosen record's own key (not its name) in a state variable, and pass that key to every later tool call.
- A match that is not unique after the answer: ask again, with that field; never pick the first.
- Choosing the record is a step, not the goal. After the choice the flow must go on to the action the customer
  asked for (read-out, change, send) and call that tool, then say the result. A route that ends the turn on the
  selection, or returns to the opening question, loses the request: keep the original intent in a variable and
  resume it right after the choice.
- If the first distinguishing field still matches several records, ask the next, more specific one (a longer part of
  the identifier); only a unique match selects. Never fall back to the first match.
- The selection step must advance by state, not by the model: when the customer's answer identifies a record, a code
  node or a route sets the chosen key and moves on in the same turn. A selection node that can only wait (a filler
  line such as "one moment", no route on the answer, no turn_target at its max turns) loops until the turn limit and
  ends the call with nothing read out. Give it a route on the answer and an exit that continues to the action.
- Every figure, date and amount said about the chosen record comes from that record's own tool result (read it
  after the choice, with the chosen key). Never say a figure from memory or from another record; if the lookup
  failed, say so.
- Add a unit test with a list of several records, two of them sharing a label, and one test that the action tool is
  called with the chosen record's key.
