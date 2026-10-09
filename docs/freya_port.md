# Porting agentforge to Freya

Code: `agentforge/platform/freya.py` (`FreyaPlatform`). Tests: `tests/test_freya.py` (offline).

**Which spec is right?** `https://docs.freyavoice.ai/api-reference/openapi.json` is an older subset. It has no chat,
personas, simulations, unit tests or branches. The doc pages embed the full spec from
`https://staging-app.freyavoice.ai/api/openapi.json`. Every path below comes from that file.

- Base URL: `https://app.freyavoice.ai/api/v2`. Bearer token in `FREYA_API_KEY`.
- Every response uses the envelope `{success, data: {message, result}}`. `unwrap()` returns `data.result`
  and raises `FreyaError` when `success` is false or the status is ≥ 400. 429 and 5xx get up to 5 tries with backoff.
- Most GETs need `workspaceId` as a query param (`GET /call/{id}`, `/agents/defaults`, `/versions/...`, unit-test runs).
  The unit-test and version POST bodies need it too. Set `FREYA_WORKSPACE_ID`. The client adds it to every query.

## Platform methods → endpoints

### `upsert_agent(cfg)` → `POST /agents`, then branches for candidates

| Step | Endpoint | Fields |
|---|---|---|
| Defaults | `GET /agents/defaults?workspaceId&language=tr` | `result.config`. `ttsConfig`, `sttConfig` and `complianceConfig` are required on create, so we layer our fields on top of the defaults. |
| V1 | `POST /agents` | `{name, language, config: {llmConfig: {provider, model, systemPrompt, firstMessage, firstMessageMode, tools}}}` → `result.agent.id` (201) |
| V1 version id | `GET /versions/agent/{agentId}?entityId&workspaceId` | `result.versions[]` with the highest `versionNumber` |
| Candidate V(n+1) | `POST /branches` | `{entityType: "agent", entityId, name: version_label, config, baseVersionId: <parent version>, description}` → `branchId`, `headVersionId` |
| Gate COMMIT | `POST /branches/{branchId}/rebase` | `{publish: true}` → `newVersionId`, `conflicts[]`, `checksState`. In the docs this is called "Merge branch". |
| Gate DISCARD | `POST /branches/{branchId}/discard` | |
| More edits to one branch | `POST /branches/{branchId}/commit` | `{config \| patch[], expectedHeadVersionId}`. Not used yet: each label is its own branch. |

`upsert_agent` returns the **version id**, not the agent id. Chat, simulations and unit tests all target a version.

Mapping notes:
- `ToolDef` → `llmConfig.tools[]` = `{type: "function", function: {name, handler, description, parameters}, extraction_schema}`.
  Freya's `extraction_schema` items are `{name, type ∈ string|integer|float|boolean|date|datetime|enum, description, required}`.
  That matches our `ExtractionField` once type names are mapped (`EXTRACTION_TYPES`).
- `AgentConfig.model` `"provider:model"` → `llmConfig.provider` / `llmConfig.model`.
- `ToolDef.preconditions` has no Freya field. Keep them in the tool description, as the builder already does.

### `run_conversation(cfg, persona, run_idx)` → `POST /chat/message` loop, `POST /chat/end`, `GET /call/{id}`

1. `POST /chat/message {agentId, versionId, message}` starts a call and returns `{response, callId, messageId, endedByAgent?, warning?}`.
   Later turns send `{callId, message}`.
2. The caller is our simulator LLM (`SIMULATOR_MODEL`, Turkish, stops on `[END]`, max 20 turns). It is the same as the Vapi adapter.
   The loop also stops when `endedByAgent` is set.
3. `POST /chat/end {callId}` closes the call. **The roadmap says `/chat/close`, but the real path is `/chat/end`.** The response is
   only `{callId, ended, endedReason, alreadyEnded}`. Post-call analysis (summary, problems, **assertions**) runs
   *asynchronously*.
4. `GET /call/{callId}?workspaceId` is polled for up to 60 s until `call.assertionResults` or `call.successCriteriaResult` appears.
   Each result item is `{id, name, assertion, success, reason, relevantMessages, timeTaken, metadata}`, and
   `call.assertionsSummary` is `{passed, failed, total}`. We store them in `RunResult.raw["freya_close"]` and the full call in
   `raw["freya_call"]`.
5. `call.cost` → `cost_usd`. `call.insights` (a free-form map) → `extraction_events`. Tool calls → see TODO below.

### Native simulations → `POST /personas`, `POST /simulations`

These run Freya's own simulator and judge. That is most likely the same machinery that scores the hidden benchmark.
- `upload_personas(personas)` → `POST /personas {personas: [{name, prompt, successCriteria, evaluationPrompt, tags, agentIds}]}`.
  **Our `Persona` JSON goes up unchanged.** `model_dump(exclude_none=True)` is the request item, and `agentIds` is added.
  Returns `result.personas[].id`.
- `run_native_simulation(cfg, persona_ids, assertion_ids, mode="chat", runs_per_persona=3)` →
  `POST /simulations {name, agentId, agentVersionId, mode: voice|chat, selectedPersonaIds, assertions: [uuid], runsPerPersona, start: true}`.
  It then polls `GET /simulations/{id}` until `status == completed` and reads
  `GET /simulations/{id}/iterations?limit=1` (`passRate`, `passedRuns`, `failedRuns`, `agentVersionId`).
  Per-persona rows come from `GET /simulations/version-persona-runs?workspaceId&entityVersionId`.
  Reruns use `POST /simulations/{id}/rerun`.
- Optional overrides on `POST /simulations`: `personaLlmOverride`, `analysisLlmOverride` (the judge) and
  `assistantLlmOverride`.

Where each one fits: our chat loop (`run_conversation`) gives us full control and our own judge
(`agentforge/run/scorer.py`). Use it for the loop's train and held-out runs. Native simulations are the closest thing to the
real score. Use them for the gate and the final blind check once we confirm they accept our personas and assertions.

### `run_unit_test(cfg, test)` → `POST /unit-tests`, `POST /unit-tests/run-all`, `GET /unit-tests/runs/{runId}`

- Create once per test name: `{workspaceId, entityType: "agent", entityId, name, expectation, assertions, input, judgeContext}`
  - `input = {schemaVersion: 1, callType: "web", messages: [{role, message}], authoredAgainstVersionId}`, built from `prefix_turns`
  - `assertions[] = {type: "tool_call", tool, args?, argsMatch: "subset", negate}`, built from `tool_assertions`.
    Freya also supports `extraction` and `routing` assertions, which we don't use yet.
- Run: `POST /unit-tests/run-all {workspaceId, entityType, entityId, entityVersionId, unitTestIds: [id]}` → 202
  `{enqueued: [{unitTestId, runIds, jobIds}], skipped}`. It also takes `repeat`, `mockToolResults` and
  `judgeLlmOverride`.
- Poll `GET /unit-tests/runs/{runId}` until `outcome ∈ pass|fail|error` (120 s deadline). `verdictReason` becomes `Verdict.reason`.
  `error` and timeouts become `passed=False, reason="ERROR: ..."`.

### Replay → `POST /chat/fork`

`{parentCallId, fromMessageId, versionId}` → `{callId, messageId, ...}`. This copies a failing call up to an assistant turn onto a
candidate version. We can then drive it with `POST /chat/message {callId, ...}`. A lighter option is
`POST /chat/message {callId, fromMessageId, versionId}`. Not wired in yet. It is the natural way to build unit tests
(`seedCallId` / `seedMessageId` on `POST /unit-tests`) straight from a failed simulation.

## Unknowns

- **TODO(ask-organizers): where do simulation assertion UUIDs come from?** `POST /simulations.assertions` takes UUIDs, and
  `GET /simulations/{id}` returns assertion objects `{id, name, prompt, contextConfig{includeToolCalls, includeExtractionEvents,
  includeRoutingEvents, includeOtherEvents}}`. These are the same shape as our `Assertion`. But the spec has **no endpoint that creates
  an assertion**. `upload_assertions()` raises `NotImplementedError`.
- **TODO(ask-organizers): what does `POST /chat/end` analysis judge for an ad-hoc chat call?** No persona is attached, so we
  don't know whether `successCriteriaResult` is ever filled or which assertions run.
  If it doesn't work, our own scorer stays the gate.
- **TODO(ask-organizers): where are tool calls in `GET /call/{id}`?** `messages[]` is typed `{role, message, ...}` and `artifact` is
  untyped. `parse_tool_calls` accepts `toolCalls` / `tool_calls` on messages and on `artifact`. Check this against a real call.
- **TODO(ask-organizers): what is `llmConfig.tools[].function.handler`?** It is a required string with no documentation. We send
  `TOOLS_BASE_URL/tools/{name}` and assume it is a webhook. It could instead be a built-in handler name.
- **TODO(ask-organizers): does the agent's greeting come back from the chat API?** `POST /chat/message` requires a non-empty
  `message`, so the caller always speaks first over the API. We record `cfg.first_message` as turn 0.
- **TODO(ask-organizers): what role names do unit-test `input.messages` use for tool turns?** We send `user` / `assistant` and drop tool turns.
- **TODO(ask-organizers): rate limits.** The spec only documents 429. The client backs off on 429 and 5xx.
- **TODO(ask-organizers): are scoring simulations voice or chat?** `POST /simulations.mode` is `voice|chat`. Use the
  scored mode for the final check.
- Workflows have no create endpoint (only `GET /workflow*`). Agents are fully configurable over the API.

## First thing to check on Freya

Run one `run_conversation`, then inspect `RunResult.raw["freya_close"]`. If `assertionResults` arrives filled, swap the gate's
scorer for Freya's. If not, check whether `run_native_simulation` reports `passRate` per iteration and use that instead.
