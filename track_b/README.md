# Track B

You own the tasks and the prompts. Track A owns the runner, the Vapi adapter, and the regression gate. Do not edit `track_a/` to change agent behavior. Change a prompt or a task here, and bump the `prompt_version` on the first line of the prompt file.

Shared contracts live in `shared/schemas/`. Match those field names. Track A writes results to `shared/versions/` and `shared/runs/`. Read those. Do not write them by hand.

## Your files

| File | What it returns |
|---|---|
| `tasks/development/*.json` | A `TaskSpec`. Three starters are already here. Replace them if you want different tasks. |
| `tasks/holdout/` | Locked until Phase 6. Track A will not read this directory before then. |
| `prompts/builder/v1.md` | One `AgentConfig` draft: system prompt, first message, tool descriptions. |
| `prompts/adversary/v1.md` | 3–5 `ScenarioSpec`s for one task and one agent version. |
| `prompts/analyzer/v1.md` | A `FailureReport` of generalized behavioral bugs. |
| `prompts/test_generator/v1.md` | `UnitTest`s for the bugs. This prompt must not see the patch. |
| `prompts/patcher/v1.md` | The next agent version. This prompt must not see the tests. |

The builder starter is filled in. The other four prompts are empty slots.
