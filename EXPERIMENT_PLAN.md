# Freya Voice Agent-Builder Hackathon — Experiment Plan

**Date:** October 9, 2026  
**Execution today:** Vapi  
**Target runtime tomorrow:** Freya  
**Goal:** Find the best-performing agent-builder under a fair, repeatable evaluation budget.

## Mission

We are optimizing the **builder**, not one hand-written voice agent. The builder receives a task and available tools, then produces a voice-agent configuration and prompt that can complete the task reliably.

We will explore broadly, but keep experiments isolated. Every candidate must be evaluated on the same development scenarios and a hidden holdout set. Complexity only stays if it improves results.

## Parallel tracks

We split ownership roughly evenly:

- **Track A — Technical / Optimization & Evaluation (Owner A):** harness, baseline, optimizer strategies, scoring, experiment analysis, holdout evaluation.
- **Track B — Product / Agent Quality & Adversarial Testing (Owner B):** task fixtures, agent compiler variants, adversarial personas, voice/tool scenarios, regression cases, prompt/configuration experiments.

Both owners should make their work runnable independently through shared interfaces below. Pair on integration and final decisions.

---

# Track A — Optimization, Harness & Evaluation

**Owner:** Technical lead  
**Focus:** Prove which builder/optimizer actually performs best.

### A0. Shared experiment contract

Implement or agree on these stable artifacts before parallel work begins:

- `TaskSpec`: task description, available tools, constraints, success criteria.
- `AgentConfig`: provider/runtime settings, system prompt, first message, tool definitions.
- `ScenarioSpec`: persona, attack objective, turn strategy, expected behavior, failure condition, severity.
- `RunRecord`: task ID, candidate ID, scenario ID, transcript, tool events, final state, latency, token/cost estimates, errors.
- `Evaluation`: criterion-level scores, overall score, failure labels, judge rationale.
- `PatchCandidate`: changed prompt sections/rules, rationale, source failures, expected benefit, regression risk.

Keep provider-specific calls behind a runtime adapter so Vapi can be replaced by Freya without changing optimizer logic.

### A1. Baseline harness — P0

- [ ] Build one-shot baseline: `TaskSpec + tools -> AgentConfig`.
- [ ] Validate generated configuration against a schema before execution.
- [ ] Run a fixed starter set of 6 tasks.
- [ ] Store prompts, configs, scenarios, transcripts, tool events, scores, and run metadata.
- [ ] Make runs reproducible and label each experiment/version.
- [ ] Separate development data from hidden holdout data.

**Deliverable:** baseline scores and a repeatable command to run/evaluate a candidate.

### A2. Optimizer comparisons — P1

Compare each optimizer against the same baseline and comparable simulation budget:

- [ ] **Manual reflective patching:** diagnose a failure and make a minimal generalized patch.
- [ ] **GEPA-style reflection:** reflect across multiple successful/failed traces and synthesize generalized improvements. This is inspired by GEPA, not a claim to reproduce the full algorithm.
- [ ] **Best-of-3:** create three strategically different prompts; evaluate and select the best.
- [ ] **Pairwise tournament:** compare candidate transcripts head-to-head.
- [ ] **Coordinate descent:** optimize one prompt section at a time.
- [ ] **Multi-trace synthesis:** combine lessons from several failures rather than patching one transcript at a time.
- [ ] **Revert-on-regression:** retain a patch only when the score improves without unacceptable regressions.
- [ ] If time permits: **beam search** (keep multiple candidates alive) or small evolutionary search.

**Deliverable:** comparison table showing quality, cost, runtime, and holdout performance per approach.

### A3. Evaluation quality — P1

- [ ] Use an explicit rubric: task completion, correct tool use, ambiguity/state handling, safety/confirmation, clarity/efficiency.
- [ ] Prefer deterministic checks for observable facts (tool called, arguments, confirmation present, final state).
- [ ] Use an LLM judge for semantic behavior that code cannot reliably assess.
- [ ] Compare single-judge scores with pairwise or double-judge evaluation on a small sample.
- [ ] Manually inspect judge disagreements and calibrate the rubric.
- [ ] Track repeated-run variance for stochastic scenarios.
- [ ] Track average score, severe failure rate, latency, and cost—not just best score.

**Deliverable:** a scoring method we trust enough to select candidates.

### A4. Patch quality gate — P2

- [ ] Add a patch review step that labels patches `ACCEPT`, `REJECT`, or `REVISE`.
- [ ] Check generality, redundancy, contradictions, overfitting, and regression risk.
- [ ] Compare an ordinary LLM judge with the OpenAI Decisions API if access and integration are practical.
- [ ] Keep deterministic token/diff/schema checks separate from semantic judgment.
- [ ] Run an ablation: same patch candidates with and without the gate.

**Deliverable:** evidence on whether a gate improves final outcomes enough to justify its cost.

### A5. Generalization and final selection — P0/P1

- [ ] Lock a holdout set that the optimizer cannot inspect.
- [ ] Include paraphrases and unseen scenarios.
- [ ] Where possible, include task-family holdouts—not just new wording of familiar tasks.
- [ ] Compare baseline and finalists on the same holdout.
- [ ] Choose the winner based on holdout success per unit of time/compute, with severe failures considered separately.
- [ ] Export the winner and its artifacts for the Freya adapter tomorrow.

**Deliverable:** final evidence-backed recommendation, not just a favorite architecture.

---

# Track B — Agent Compiler, Adversarial Personas & Prompt Quality

**Owner:** Product / agent-quality lead  
**Focus:** Discover which agent construction and test-generation techniques expose and prevent real failures.

### B0. Task fixtures and tool scenarios — P0

- [ ] Create 6 diverse representative tasks with clear success criteria and tool definitions.
- [ ] Ensure each task has enough detail to evaluate success, not merely conversational quality.
- [ ] Include tool success and failure paths where relevant.
- [ ] Write a few manually verified “gold” scenarios for checking automated persona/judge quality.
- [ ] Avoid using the hidden holdout examples to develop prompts or attacks.

**Deliverable:** versioned task fixtures and a starter set of trustworthy scenarios.

### B1. Agent compiler experiments — P1

Generate agent configurations using the same task fixtures:

- [ ] **One-shot compiler:** direct task-to-agent generation.
- [ ] **Requirements-first compiler:** extract goals, constraints, required fields, tool contracts, and success criteria before generating.
- [ ] **Planner + compiler:** create a structured workflow, then compile it into the voice prompt.
- [ ] **Failure-mode-first compiler:** enumerate likely failure modes before prompt writing.
- [ ] **Workflow templates:** adapt a proven template for a similar task.
- [ ] **Modular vs monolithic prompt:** compare separate workflow/tool/clarification/safety sections against one cohesive prompt.
- [ ] **Tool-contract detail:** compare minimal tool descriptions with explicit arguments, side effects, and error behavior.

**Deliverable:** candidate prompts/configurations for the shared evaluation harness.

### B2. Adversarial persona generator — P1

Do not generate generic “rude users.” Generate attacks tied to the task and available tools.

For each task:
1. Identify relevant attack surfaces.
2. Generate 8–12 candidate attack specs.
3. Rank by plausibility, severity, and likelihood of exposing a defect.
4. Execute the top 3–5 in development.
5. Preserve a separate hidden attack pool for holdout evaluation.

Attack surfaces to consider:

- [ ] Missing required information.
- [ ] Ambiguous requests / “you choose.”
- [ ] Changing or contradictory requirements.
- [ ] Multi-turn state tracking and corrections.
- [ ] Tool errors, empty results, timeouts, unavailable options.
- [ ] Premature actions or skipped confirmation.
- [ ] Attempts to override agent instructions or constraints.
- [ ] Voice-specific interruption, disfluency, fragmented speech, ambiguous numbers.
- [ ] Multi-objective requests or changes of intent mid-conversation.

Every `ScenarioSpec` should include:
- persona/behavior
- attack surface and objective
- multi-turn strategy
- expected good behavior
- observable failure condition
- severity / priority

### B3. Compare adversary strategies — P1

- [ ] **Random/generic personas vs task-aware attacks.**
- [ ] **Taxonomy-driven attacks vs attack-surface-first generation.**
- [ ] **Static scripts vs adaptive adversaries** that respond to the agent’s last turn.
- [ ] **Single-turn vs multi-turn attacks.**
- [ ] **Persona pairs:** cooperative vs difficult user with the same objective.
- [ ] **Attack mutation:** paraphrase or restructure an attack while preserving its objective.
- [ ] **Attack ranking:** keep scenarios that uncover real, meaningful failures; remove trivial or impossible ones.
- [ ] **Failure prediction:** ask the generator to predict likely failures before testing, then compare with observed failures.

**Deliverable:** a reusable adversarial scenario generator and a comparison of which approach finds the most meaningful failures.

### B4. Prompt maintenance and regression memory — P1/P2

- [ ] **Append vs merge:** add a new rule or incorporate it into an existing rule.
- [ ] **Prompt bloat test:** retain all accepted rules vs merge/prune redundant rules.
- [ ] **Rule metadata:** link each rule to its source failure and regression tests.
- [ ] **Counterexample-guided refinement:** generate a minimal counterexample for each failure, then fix the general behavior.
- [ ] **Contrastive repair:** compare a failed transcript with a successful one for the same task.
- [ ] **Root cause vs symptom patch:** evaluate whether the patch generalizes beyond the triggering transcript.
- [ ] **Rule deletion/ablation:** remove rules or sections to discover which ones actually contribute.
- [ ] **Regression suite:** convert every confirmed failure into a persistent behavioral test.
- [ ] **Cross-task transfer:** check whether a fix helps similar tasks without harming unrelated tasks.

**Deliverable:** concise prompts with traceable rules and a reusable regression suite.

### B5. Voice-agent-specific experiments — P2

- [ ] First-message variants: direct, warm, or information-gathering first message.
- [ ] Concision vs detailed workflow instructions.
- [ ] Explicit clarification policy for missing decision-critical fields.
- [ ] Explicit tool-failure recovery instructions.
- [ ] State ledger: known facts, unresolved fields, and user corrections.
- [ ] Interruption/correction recovery.
- [ ] Robustness to plausible speech-recognition errors.
- [ ] Model/settings search only if allowed by the task and benchmark.
- [ ] Prompt-only vs prompt + tool/configuration optimization.

**Deliverable:** a ranked list of voice-agent-specific changes that improve task completion.

---

# Shared experiment protocol

## Fair comparisons

- Same task fixtures, base model where possible, tools, and runtime conditions.
- Same development scenarios for candidate comparison.
- Comparable optimization/evaluation budgets; record actual spend and latency.
- Store every candidate and its parent so results can be reproduced.
- Never select a candidate using holdout results and then report that same holdout as unbiased final performance.
- Do not trust the optimizer’s own claim that its patch is better.

## Starter scoring rubric

Use the official hackathon scoring criteria if available. Until then, use this provisional proxy:

| Criterion | Weight |
|---|---:|
| Task completion / outcome | 40% |
| Correct tool use and constraints | 25% |
| Ambiguity, corrections, and recovery | 20% |
| Safety and confirmation | 10% |
| Clarity and efficiency | 5% |

Score observable requirements deterministically where possible; use an LLM judge for semantic requirements. Track severe failures separately so a high average cannot hide dangerous mistakes.

## Experiment log

For every run, record:

- Experiment ID and hypothesis.
- Parent candidate and exact prompt/config version.
- Task and scenario IDs.
- Changes made.
- Development score and holdout score (holdout visible only to final evaluator).
- Failure categories and regression count.
- Latency, token usage, estimated cost, and errors.
- Decision: keep / reject / rerun.
- One-sentence conclusion.

## Suggested repository layout

```text
.
├── README.md
├── EXPERIMENT_PLAN.md
├── schemas/
│   ├── task_spec.json
│   ├── agent_config.json
│   ├── scenario_spec.json
│   ├── run_record.json
│   └── patch_candidate.json
├── tasks/
│   ├── development/
│   └── gold_scenarios/
├── holdout/
│   └── README.md
├── prompts/
│   ├── compiler/
│   ├── adversary/
│   ├── evaluator/
│   └── optimizer/
├── adapters/
│   ├── vapi/
│   └── freya/
├── experiments/
│   ├── configs/
│   └── results/
├── regression_tests/
├── scripts/
└── reports/
```

Keep actual secret keys in environment variables or a local ignored `.env` file. Never commit keys, call recordings, or sensitive transcripts.

## Suggested schedule for today

1. **First 30–45 min:** agree on schemas, task fixtures, scoring, and adapter interface.
2. **Next 60 min:** Track A gets the baseline harness running; Track B builds task fixtures and compiler variants in parallel.
3. **Next 60–90 min:** Track A runs baseline and repair/reflective optimization; Track B builds attack generation and runs persona comparisons.
4. **Next 45–60 min:** integrate regression memory, test candidate selection, and compare prompt maintenance strategies.
5. **Final 30–45 min:** evaluate finalists on the locked holdout, record conclusions, and freeze the winner.
6. **Tomorrow:** replace Vapi runtime/evaluation calls with Freya-compatible calls and rerun smoke tests plus the same evaluation protocol.

## Definition of done

- [ ] A reproducible baseline exists.
- [ ] At least three meaningful builder/optimizer strategies have been compared.
- [ ] Targeted adversarial tests uncover and document failures.
- [ ] Regression tests exist for confirmed failures.
- [ ] The best candidate is evaluated on a locked holdout.
- [ ] Results include quality, severe failures, latency, and cost.
- [ ] The winning system can be ported to Freya by replacing the runtime adapter rather than rewriting the optimizer.

## Guiding principle

**LLM generates → evaluator measures → optimizer proposes → checks reject bad patches → simulations verify → holdout decides.**

We are trying many promising approaches, but the winning architecture is the simplest one that measurably improves unseen-task success within the available time and compute.
