# Track B

You own the tasks and the prompts. Track A owns the runner, the Vapi adapter, and the regression gate. Do not edit `track_a/` to change agent behavior. Change a prompt or a task here, and bump the `prompt_version` on the first line of the prompt file.

Shared contracts live in `shared/schemas/`. Match those field names. Track A writes results to `shared/versions/` and `shared/runs/`. Read those. Do not write them by hand.

## Your files

| File | What it returns |
|---|---|
| `tasks/development/*.json` | A `TaskSpec`. Three starters are already here. Replace them if you want different tasks. |
| `tasks/holdout/*.json` | Two `TaskSpec`s (`cancel_appointment`, `change_delivery_address`). Locked until Phase 6. Track A will not read this directory before then. |
| `prompts/builder/v1.md` | One `AgentConfig` draft: system prompt, first message, tool descriptions. |
| `prompts/adversary/v1.md` | 3–5 `ScenarioSpec`s for one task and one agent version. |
| `prompts/analyzer/v1.md` | A `FailureReport` of generalized behavioral bugs. |
| `prompts/test_generator/v1.md` | `UnitTest`s for the bugs. This prompt must not see the patch. |
| `prompts/patcher/v1.md` | The next agent version. This prompt must not see the tests. |
| `examples/book_clinic_appointment/` | One hand-written output per prompt, chained (scenarios → report → tests → patch). Reference only; the loop does not read it. |

All five prompts are filled in.

## Wiring notes for Track A

Every prompt file has `prompt_version:` on line 1, like the builder. The rest is the system message. Send the inputs as JSON in the user message. Every prompt returns one JSON object, so `parse_json_object` and `response_format: json_object` both work.

| Prompt | User message | Returns |
|---|---|---|
| adversary | `{"task": TaskSpec, "agent": AgentConfig}` | `{"scenarios": [ScenarioSpec]}` |
| analyzer | `{"task": TaskSpec, "agent_version": str, "runs": [RunRecord]}` | `FailureReport` |
| test_generator | `{"task": TaskSpec, "failure_report": FailureReport}` | `{"tests": [UnitTest], "untestable_bug_ids": [{"bug_id", "reason"}]}` |
| patcher | `{"task": TaskSpec, "agent": AgentConfig, "failure_report": FailureReport}` | builder draft shape plus `changes: [{"bug_id", "edit"}]` |

The patcher output feeds the same `assemble()` as the builder. Track A sets `id`, `version`, and `parent_id` and drops `changes` (or logs it). `untestable_bug_ids` is a signal to the gate: such a bug has no test, so the current gate will discard. That is intended. Fix the report or the tests, not the gate.

Unit tests script caller turns only. They cannot force a tool error, so tool-error recovery is checked by simulations, not unit tests.

## What counts as a generalized bug

Partner owns this bar. The analyzer prompt encodes it.

- It is a rule the agent breaks under a condition, not a quote from one turn.
- It shows up in two or more scenarios, or once as a direct constraint break that a tool event proves (write with no yes, write with an unconfirmed value, write after a failed read, guessed required argument).
- Tone, wording, and length are not bugs unless they break a stated constraint.
- Same cause, one bug. Merge and list every scenario id.

Severity follows the plan's score order: `severe` = wrong or unconfirmed write side effect; `high` = invented tool facts or out-of-task promises; `medium` = failed recovery without a wrong write; `low` = anything else that still breaks a constraint.
