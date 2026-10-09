# Closed-Loop Agent Builder — Experiment Plan

**Date:** October 9, 2026
**Track A (us):** harness, Vapi adapter, tests, regression gate. Code lives in `track_a/`.
**Track B (partner):** tasks and prompts. Files live in `track_b/`. See `track_b/README.md`.
**Runtime:** Vapi today (`POST /assistant` to publish, `POST /chat` when the builder itself runs through Vapi). Freya replaces that adapter later. The builder never calls the provider directly.

**Status:** Phase 0 runs with no network. Phase 1 stores a schema-valid V1 per development task and can publish it through the Vapi adapter. Live generation needs `VAPI_API_KEY` or `OPENAI_API_KEY` in `.env` (see `.env.example`).

```bash
python3 track_a/scripts/run_loop.py phase0
python3 track_a/scripts/run_loop.py build --publish
```

## What we are building

One loop. It starts from a task and its tools, and it ends with the best committed agent version.

```text
TASK + TOOLS
      │
      ▼
 LLM BUILDER ──► V1
      │
      ▼
 LLM ADVERSARY          find likely failure modes
      │
      ▼
 3–5 PERSONAS
      │
      ▼
 FREYA SIMULATIONS ──► TRANSCRIPTS
      │
      ▼
 LLM ANALYZER           generalized behavioral bugs, not one-off lines
      │
      ▼
 FAILURE REPORT
      ├──────────────────────┐
      ▼                      ▼
 LLM TEST GENERATOR     LLM PATCHER
      │                      │
      ▼                      ▼
 UNIT TESTS                V2
                             │
                             ▼
                   SIMULATIONS + TESTS
                             │
                             ▼
                      REGRESSION GATE
                        │         │
                        ▼         ▼
                     COMMIT    DISCARD
                        │
                        ▼
                      BEST
```

The thing we are optimizing is the **builder loop**, not a single hand-written prompt. A version is kept only when the gate says it is better. `BEST` is the latest committed version, or V1 if nothing has passed the gate.

We are not comparing a menu of optimizers today (GEPA, beam search, tournaments). Those stay out of the critical path. If the loop is running and there is time left, a second builder prompt can be dropped in as another candidate and judged by the same gate.

## What each box must do

| Step | Input | Output | Rule |
|---|---|---|---|
| Builder | `TaskSpec` | `AgentConfig` V1 | One shot. Schema-valid before it is simulated. |
| Adversary | task + tools + V1 | 3–5 `ScenarioSpec`s | Attacks tied to this task and these tools. Not generic rude users. |
| Simulations | personas + agent version | `RunRecord`s with transcripts and tool events | Same personas are reused when we retest V2. |
| Analyzer | transcripts + task | `FailureReport` | Bugs are generalized behaviors (“skips confirmation when a required field is missing”), not quotes from one turn. |
| Test generator | failure report | unit tests | Tests encode the bug, not the patch. Written before or without seeing V2. |
| Patcher | failure report + current prompt | V2 | Smallest change that should fix the generalized bug. |
| Regression gate | V1 results, V2 simulations, unit tests | commit or discard | Commit only if targeted failures improve and existing tests do not regress. |

The test generator and the patcher both read the failure report. They do not read each other. That keeps the tests from becoming a restatement of the patch.

## How we collaborate

Two owners, one repo, file handoffs. Chat is for decisions. The artifact is the source of truth.

**Shared, both tracks**

- `shared/schemas/` — the JSON contracts. Neither track renames fields alone.
- `shared/versions/` — Track A writes each agent version. Track B reads it. Do not hand-edit it.
- `shared/runs/` — Track A writes transcripts and gate decisions. Track B reads them.
- `EXPERIMENT_PLAN.md` and `.env.example`.

**Track A, `track_a/`**

- The loop runner, schema checks, version store, and holdout lock.
- The Vapi runtime adapter.
- The regression gate and the unit-test runner.
- Canned Phase 0 fixtures under `track_a/fixtures/`.

**Track B, `track_b/`**

- Task fixtures: description, tools, constraints, success criteria.
- Prompts for builder, adversary, analyzer, test generator, and patcher.
- The bar for a “generalized” bug versus a one-off transcript nit.
- Spot-checks: are the 3–5 personas actually capable of exposing a real defect?

**Decision rights**

- We decide whether a run is valid (schema, reproducibility, gate math).
- Partner decides whether a persona or a bug label is meaningful.
- Either side can discard a patch. Only the gate can commit one.
- Holdout results are not an input to the patcher. We run holdout once, at the end, on `BEST` vs V1.

**Handoff format**

Every step writes a JSON file under a version directory. The next step reads that file, not a pasted chat message. If a prompt changes, the partner bumps the prompt version in the file header so a run can be reproduced.

**Sync points**

We do not wait on each other inside a phase. We sync only at the phase exit below. If one side is blocked, it leaves a stub that still matches the schema so the other side can keep going.

## Shared contracts

Agree on these before writing prompts or the runner. Field names can be thin; they should not churn after Phase 0.

- `TaskSpec` — task, tools, constraints, success criteria.
- `AgentConfig` — system prompt, first message, tool definitions, model/runtime settings, version id, parent id.
- `ScenarioSpec` — persona, attack objective, turn strategy, expected good behavior, observable failure, severity.
- `RunRecord` — task id, agent version, scenario id, transcript, tool events, final state, latency, token/cost, errors.
- `FailureReport` — bug id, generalized statement, evidence scenario ids, severity, suggested invariant.
- `UnitTest` — bug id, scenario or scripted user turns, deterministic assertions.
- `GateDecision` — compared versions, test deltas, simulation deltas, `commit` or `discard`, one-sentence reason.

Provider calls sit behind a runtime adapter. Builder logic never imports Freya or Vapi directly.

## Phases

Each phase has an exit. We do not start the next phase’s real LLM calls until the exit is true. Stubs are fine.

### Phase 0 — Contracts and skeleton

Agree the JSON shapes, directory layout, and who writes which prompt. Runner can execute the loop with canned files and print commit/discard.

**Exit:** a fake V1 → fake report → fake V2 runs through the gate locally, with no network.

### Phase 1 — Builder to a real V1

Partner supplies 2–3 development tasks (not the holdout). Builder prompt turns a `TaskSpec` into a schema-valid `AgentConfig`. We reject invalid configs before simulation.

**Exit:** one command produces a stored V1 for each development task.

### Phase 2 — Adversary and Freya simulations

Adversary reads the task and V1 and writes 3–5 personas. We run those personas and store transcripts and tool events.

**Exit:** every development task has 3–5 transcripts tied to a version id. Partner has skimmed them and confirmed the personas are task-specific.

### Phase 3 — Analyzer

Analyzer reads only transcripts plus the task. It emits a failure report of generalized bugs. If it cannot support a bug with more than a single lucky turn, it drops that bug.

**Exit:** a failure report we both accept as “behavioral,” with severity, for at least one task that actually failed.

### Phase 4 — Tests and patch, in parallel

Same failure report feeds both branches.

- Test generator writes unit tests for the invariants in the report.
- Patcher writes V2 from the current prompt plus the report.

We run the test generator first in wall-clock terms only if we have to serialize. The patcher prompt must not be given the tests, and the test prompt must not be given V2.

**Exit:** V2 is schema-valid, and there is at least one unit test per accepted bug.

### Phase 5 — Regression gate

Replay the same personas on V2. Run the unit tests on V2 and, where they apply, on V1 as a baseline.

Commit V2 only when all of these hold:

- New tests for the targeted bugs pass on V2.
- Tests that already passed on the parent still pass.
- Targeted simulation failures improve.
- No new severe failure on the replayed personas.

Otherwise discard. Parent stays `BEST`. Record the reason either way.

**Exit:** one real commit or one real discard, with the artifacts on disk. The decision is reproducible from the saved scores.

### Phase 6 — Repeat, then holdout

Run the loop again from `BEST` until the budget is gone (time, simulated calls, or no new accepted bugs). Then run V1 and `BEST` on the locked holdout. Holdout does not feed the patcher.

**Exit:** a short result: V1 vs `BEST` on development and on holdout, plus severe-failure count, latency, and cost.

## Gate rules (so we do not relitigate them mid-run)

- A high average cannot hide a new severe failure. Severe failure discards the patch.
- One flaky scenario does not commit a patch. The bug statement has to be general, and the replay has to support it.
- Editing tests after seeing V2 invalidates the run. Save the tests, then patch.
- Prompt growth is a cost. If two rules say the same thing, the patcher should merge, not append forever.
- `BEST` is whatever is committed. Discarded versions stay on disk for the log and are never selected.

## Provisional score

Use the hackathon rubric if it is published. Until then, rank in this order:

1. Severe failures (safety, wrong tool side effect, skipped required confirmation). Fewer is better. This can veto a commit by itself.
2. Task completion and correct tool use.
3. Recovery from ambiguity, correction, and tool failure.
4. Then latency and token cost.

Deterministic checks own tool name, arguments, required confirmation, and final state. An LLM judge is only for behavior those checks cannot see. The gate’s commit/discard uses the deterministic tests plus the severe-failure flag. Judge prose is evidence for the analyzer, not a second vote that overrides the gate.

## Layout

```text
.
├── EXPERIMENT_PLAN.md
├── shared/
│   ├── schemas/          # both tracks
│   ├── versions/         # Track A writes, Track B reads
│   └── runs/
├── track_a/              # harness, adapter, gate, tests
│   ├── loop/
│   ├── fixtures/phase0/
│   ├── tests/
│   └── scripts/run_loop.py
└── track_b/              # tasks and prompts
    ├── tasks/
    │   ├── development/
    │   └── holdout/      # loop cannot read this until Phase 6
    └── prompts/
        ├── builder/
        ├── adversary/
        ├── analyzer/
        ├── test_generator/
        └── patcher/
```

Secrets stay in the environment or a local ignored `.env`. Do not commit keys or raw call recordings.

## Today, in order

1. Phase 0 together, short. Freeze schemas.
2. Partner writes tasks and the builder prompt. We wire the runner and the schema check.
3. Adversary prompt + simulation adapter. Get transcripts.
4. Analyzer prompt. Agree the first failure report is actually general.
5. Split: partner finishes test-generator and patcher prompts; we finish the test runner and the gate.
6. One full commit/discard. If that works, repeat within budget, then holdout.

If Freya is down, we still finish Phases 0–1 and the gate against recorded or stub transcripts. We do not block the loop on the provider.

## Definition of done

- The loop runs from task + tools to a gate decision without hand-copying JSON between steps.
- At least one development task has gone V1 → personas → transcripts → failure report → tests + V2 → commit or discard.
- `BEST` is selected only by the gate.
- V1 and `BEST` are both scored on a holdout the loop did not train on.
- Swapping the runtime adapter to Freya does not require rewriting the builder, analyzer, patcher, or gate.
