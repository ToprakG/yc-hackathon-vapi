# Agentforge — Hackathon Prep Roadmap (Vapi today → Freya tomorrow)

**Goal of today:** know, with numbers, whether our loop beats the builder alone on unseen scenarios — before porting to Freya.
**Scoring reality:** the final agent is scored on (hidden) simulations. Freya scores simulations with an LLM judge over the
transcript (+ optional tool calls / extraction events) against each persona's `successCriteria` and global assertions.
So everything today is built in Freya's data format and scored the same way.

## Our pipeline

```
TASK + TOOLS -> LLM BUILDER -> V1 -> LLM ADVERSARY (3-5 personas) -> SIMULATIONS -> TRANSCRIPTS
-> LLM ANALYZER (generalized behavioral bugs) -> FAILURE REPORT
   -> LLM TEST GENERATOR -> UNIT TESTS
   -> LLM PATCHER -> V2
-> SIMULATIONS + TESTS -> REGRESSION GATE -> COMMIT / DISCARD -> BEST
```

Four guards added to protect the hidden-benchmark score:
1. **Coverage personas** next to adversary personas (the hidden benchmark is mostly ordinary callers).
2. **Train / held-out split** — analyzer + patcher see only `train`; the gate scores only `heldout`.
3. **3 runs per persona** — simulations are noisy.
4. **Blind set** — written by Person 1, never seen by Person 2. The only number that predicts the real score.

## Before you start
- `.env`: `VAPI_API_KEY`, LLM provider keys, `AGENT_MODEL`, `JUDGE_MODEL` (different provider from agent), `BUILDER_MODEL`, `TOOLS_BASE_URL`
- Install `cloudflared` (Vapi needs a public URL to call our mock tools)
- Each person runs their own Claude Code session in this repo. **S0 must be pushed before anything else.**

## Schedule (2 people, 6 hours)

| Time | Person 1 | Person 2 |
|---|---|---|
| 0:00–0:30 | **S0** Scaffold + schemas (one runs, other reviews) | — |
| 0:30–1:15 | **S1** Vapi adapter + simulator loop | **S2** Domain pack + mock tools |
| 1:15–2:00 | S1 continues | **S3** LLM Builder (V1) |
| 2:00–2:45 | **S4** Blind test set (P2 must not see) | **S5** Adversary + coverage + assertions |
| 2:45–3:30 | **S6** Freya-style scorer | **S7** Analyzer + test gen + patcher + gate |
| 3:30–4:00 | Noise test (in S6) | S7 continues |
| 4:00–5:15 | **S8** Loop + experiment (together) | S8 |
| 5:15–6:00 | **S9** Results + Freya port notes (together) | S9 |

If time runs short: cut variant C in S8 and the Freya implementation in S9. **Never cut the blind set.**

---

## S0 · Both · 0:00–0:30 · Scaffold + schemas

Paste into Claude Code:

```
Create a Python 3.11 project `agentforge`: an AI system that builds voice agents for insurance/banking.
Today we test on Vapi; tomorrow we port to Freya. Keep platform code isolated behind one interface.

Our pipeline: TASK+TOOLS -> LLM BUILDER -> V1 -> LLM ADVERSARY (3-5 personas) -> SIMULATIONS -> TRANSCRIPTS
-> LLM ANALYZER (generalized behavioral bugs) -> FAILURE REPORT -> {LLM TEST GENERATOR -> UNIT TESTS, LLM PATCHER -> V2}
-> SIMULATIONS + TESTS -> REGRESSION GATE -> COMMIT/DISCARD -> BEST.

Structure:
agentforge/
  schemas.py, config.py (.env: VAPI_API_KEY, TOOLS_BASE_URL, AGENT_MODEL, JUDGE_MODEL, BUILDER_MODEL, provider keys)
  llm.py            # call_llm(system, user, model=None, json_schema=None, temperature=0.2) -> str|dict ; supports anthropic + openai
  platform/base.py  # abstract Platform
  platform/vapi.py, platform/freya.py  # stubs
  domain/ build/ testgen/ run/ analyze/ patch/ loop/ experiments/
  runs/ results/ (gitignored outputs)
pyproject: pydantic>=2, httpx, python-dotenv, fastapi, uvicorn, pyyaml, rich, anthropic, openai, pytest

schemas.py (pydantic v2). Mirror Freya's formats so data can be uploaded tomorrow unchanged:
- ToolDef: name, description, parameters (JSON schema), extraction_schema: list[{name,type,description,required}] = [],
  preconditions: list[str] = []
- AgentConfig: version_label, system_prompt, first_message, tools: list[ToolDef], model, parent_version: str|None,
  notes: str = ""
- Persona (Freya persona shape): name, prompt, successCriteria, evaluationPrompt: str|None, tags: list[str]
  (tags include exactly one of "train" | "heldout" | "blind")
- Assertion (Freya shape): name, prompt, contextConfig: {includeToolCalls: bool, includeExtractionEvents: bool,
  includeRoutingEvents: bool}
- UnitTest: name, prefix_turns: list[Turn], expectation: str, tool_assertions: list[{tool, args: dict|None, negate: bool}]
- Turn: role ("user"|"assistant"|"tool"), text, tool_calls: list[dict]|None, turn_idx
- RunResult: persona_name, agent_version, run_idx, mode, transcript: list[Turn], tool_calls: list[{name,args,result,turn_idx}],
  extraction_events: list[{field,value,turn_idx}], ended_reason, duration_s, cost_usd: float|None, raw: dict
- Verdict: check_name, passed, reason, evidence_turn: int|None
- ScoredRun: run: RunResult, verdicts: list[Verdict], passed: bool
- FailureReport: version, bugs: list[{bug_id, description, generalized_rule, evidence: list[{persona, run_idx, turn}],
  culprit: "agent"|"simulator"|"judge", layer: "prompt"|"tool_schema"|"first_message"}]
- Patch: bug_id, layer, operator, before, after, rationale

platform/base.py: class Platform(ABC):
  upsert_agent(cfg: AgentConfig) -> str
  run_conversation(cfg: AgentConfig, persona: Persona, run_idx: int) -> RunResult
  run_unit_test(cfg: AgentConfig, test: UnitTest) -> Verdict

Add a smoke test (imports + schema round-trip to JSON) and a README describing the pipeline and folders. Minimal, typed, no extra layers.
```

**Done when:** smoke test passes, pushed to main.

---

## S1 · Person 1 · 0:30–2:00 · Vapi adapter + simulator loop (critical path)

```
Implement agentforge/platform/vapi.py: VapiPlatform(Platform), using httpx against https://api.vapi.ai.
Read and follow these docs exactly before coding:
- https://docs.vapi.ai/api-reference/assistants/create.md
- https://docs.vapi.ai/tools/custom-tools.md
- https://docs.vapi.ai/api-reference/chats/create.md
- https://docs.vapi.ai/chat/session-management.md
- https://docs.vapi.ai/observability/evals-quickstart.md

1. upsert_agent(cfg): map AgentConfig -> Vapi assistant (model = cfg.model, system prompt, firstMessage, function tools whose
   server.url = TOOLS_BASE_URL + "/tools/" + name). Create or update; cache assistant id by version_label.
   Also expose to_vapi_json(cfg) for transient use.
2. run_conversation(cfg, persona, run_idx): our own simulator loop over the Vapi Chat API:
   - Simulator = LLM with system prompt: "You are a phone caller. Stay in character.
     Follow this persona: {persona.prompt}. Speak Turkish, short spoken sentences. When your goal is done or the agent transfers
     you, say a goodbye and output [END]."
   - Agent speaks first using first_message; alternate turns; max 20 turns; stop on [END], transfer, or error.
   - Collect transcript and tool calls (from Vapi responses AND from the mock tool server log GET {TOOLS_BASE_URL}/calls/{session_id};
     pass a session id the tool server can see, e.g. via tool call metadata or a header — check the docs).
   - Return RunResult with duration and any cost info available.
3. run_unit_test(cfg, test): create a Vapi Eval of type chat.mockConversation from test.prefix_turns, add a judgePlan checkpoint:
   exact tool-call checks from test.tool_assertions, plus an AI judge with test.expectation. Run against the transient assistant,
   poll GET /eval/run/{id} until ended (deadline 120s). endedReason != mockConversation.done => Verdict(passed=False, reason="ERROR: ...").
4. Retries with exponential backoff on 429/5xx, and log every request/response to runs/vapi_log.jsonl.
5. scripts/smoke_vapi.py: build a trivial AgentConfig with one tool, run 1 conversation with a dummy persona, print the transcript.
```

**Done when:** `smoke_vapi.py` prints a full conversation with at least one tool call.

---

## S2 · Person 2 · 0:30–1:15 · Domain pack + mock tools

```
In agentforge/domain/kasko/ build a Turkish car-insurance claim intake ("kasko hasar ihbarı") test domain.

1. sop.md: a realistic, slightly messy Turkish call-center SOP (~1.5 pages). Include: AI disclosure at call start; identity check
   (TCKN last 4 + birth date) BEFORE any policy info; policy lookup; claim creation with date, location, description, injury yes/no,
   other party plate; transfer to human if injury=yes or caller asks twice; never read back full TCKN/card numbers; never promise
   coverage not listed in the policy; read policy numbers digit by digit; short spoken sentences. Bury some rules inside paragraphs.
2. tools.json: ToolDef list for verify_identity(tckn_last4, birth_date), get_policy(policy_number),
   create_claim(policy_number, date, location, description, injury, other_plate), transfer_to_human(reason).
   Put extraction_schema on create_claim (date, location, injury, other_plate).
3. policies.json: 6 synthetic customers (fake TCKN, birth date, policy no like KSK-2024-004512, coverage list, exclusions e.g. deprem).
4. tools_server.py (FastAPI):
   - POST /tools/{name}: accept Vapi's tool-call webhook format (see https://docs.vapi.ai/tools/custom-tools.md;
     respond with results[] keyed by toolCallId) and also plain JSON.
   - Deterministic logic over policies.json, in-memory per-session state; get_policy and create_claim return an error
     if verify_identity hasn't succeeded in the same session.
   - Log every call (session_id, name, args, result, timestamp); GET /calls/{session_id} returns the log; POST /reset clears it.
5. README: run `uvicorn agentforge.domain.kasko.tools_server:app --port 8001` and `cloudflared tunnel --url http://localhost:8001`,
   then set TOOLS_BASE_URL.
6. pytest: precondition enforcement + successful claim.
```

**Done when:** tool server runs behind the tunnel; tests pass.

---

## S3 · Person 2 · 1:15–2:00 · LLM Builder (V1)

```
Implement agentforge/build/builder.py: build_agent(task_md: str, tools: list[ToolDef], model=BUILDER_MODEL) -> AgentConfig.
This is the "LLM BUILDER" box: TASK + TOOLS -> V1.

- One strong LLM call with a careful builder prompt that produces JSON {system_prompt, first_message, tool_descriptions}.
- The builder prompt must instruct:
  - Turkish voice agent; short spoken sentences, no lists or markdown, read numbers digit by digit.
  - Organize the system prompt into numbered stages (Açılış/AI bildirimi -> Kimlik doğrulama -> Talebi anlama -> İşlem -> Kapanış),
    each listing which tools may be used.
  - A "Kesin kurallar" section with every hard rule from the task, phrased as observable behaviour.
  - Make compliance VISIBLE in speech: confirm verification out loud, summarize actions at the end
    (our scorer is an LLM judge reading the transcript + tool calls).
  - Tool descriptions must state preconditions explicitly.
- Merge tool_descriptions back into the ToolDefs; set version_label="v1", parent_version=None.
- Save to runs/v1/agent.json and print prompt length.
CLI: python -m agentforge.build.builder domain/kasko
```

**Done when:** `runs/v1/agent.json` exists and S1's adapter can run it.

---

## S4 · Person 1 · 2:00–2:45 · Blind test set (Person 2 must NOT see it)

Run in Person 1's own session. Keep the output local or out of Person 2's view.

```
Read ONLY agentforge/domain/kasko/sop.md, tools.json and policies.json (do not read any agent prompt or other testgen code).
Write agentforge/domain/kasko/blind_personas.json: 10 personas in Freya persona format
{name, prompt, successCriteria, evaluationPrompt: null, tags: ["blind"]}.

Mix like a real evaluator would: 6 ordinary callers (normal claim, policy question, claim without policy number at hand,
caller with a minor accident and the other party's plate, caller asking whether something is covered that IS excluded,
caller who just wants to update info), 3 hard-but-honest (elderly person reading numbers slowly and correcting themselves,
caller who gives everything out of order and interrupts, caller with injury who doesn't mention it until late),
1 adversarial (tries to get policy details for "my husband" without his data).

prompt: Turkish, first person, concrete facts from policies.json, behaviour traits, what they want.
successCriteria: specific and observable from transcript + tool calls (e.g. "Agent calls verify_identity before get_policy,
creates a claim with injury=true and transfers to a human; never confirms coverage for deprem").
Also write blind_assertions.json: 5 global assertions in Freya format {name, prompt, contextConfig} covering the SOP's hard rules.
Do not reuse wording from any other file in the repo.
```

**Done when:** 10 blind personas + 5 assertions exist and Person 2 hasn't seen them.

---

## S5 · Person 2 · 2:00–2:45 · Adversary + coverage personas + assertions

```
Implement agentforge/testgen/ (the "LLM ADVERSARY" box plus coverage). Never read domain/kasko/blind_*.json.

1. adversary.py: generate_adversary(task_md, tools, cfg: AgentConfig, n=4) -> list[Persona]
   Step 1: LLM lists likely failure modes of THIS agent prompt (procedure order, wrong tool args from misheard numbers,
   hallucinated coverage, missed escalation, over-confirmation, PII read-back, social engineering).
   Step 2: one persona per top failure mode, in Freya format {name, prompt, successCriteria, tags}.
2. coverage.py: generate_coverage(task_md, tools, n=6) -> list[Persona]: one persona per main SOP path, ordinary callers mostly.
3. split.py: tag ~60% "train", ~40% "heldout", stratified so every failure mode/path type appears in both if possible.
4. assertions.py: generate_assertions(task_md) -> list[Assertion] from the SOP's hard rules, with contextConfig.includeToolCalls=true.
5. Save runs/testsets/personas.json and assertions.json. Print a table of personas with tags.
```

**Done when:** ~10 personas tagged train/heldout + assertions saved.

---

## S6 · Person 1 · 2:45–4:00 · Freya-style scorer + noise test

```
Implement agentforge/run/scorer.py and agentforge/run/runner.py.

scorer.py — imitate Freya's simulation evaluation (LLM judge over transcript + optional tool calls/extraction events):
- score_run(run: RunResult, persona: Persona, assertions: list[Assertion]) -> ScoredRun
- One judge call for persona.successCriteria (use persona.evaluationPrompt as instructions if set).
- One judge call per assertion; include tool calls / extraction events only if its contextConfig enables them.
- Judge returns JSON {passed, reason, evidence_turn}; temperature 0; JUDGE_MODEL from a different provider than AGENT_MODEL.
- Run passes iff successCriteria and all assertions pass.

runner.py:
- run_suite(platform, cfg, personas, assertions, runs_per_persona=3, concurrency=4) -> list[ScoredRun], saved to runs/<version>/<set>.jsonl
- metrics(scored) -> {pass_rate, pass_hat_3 (tau-bench: per persona C(c,3)/C(n,3) averaged), per_persona, per_assertion_fail_counts,
  total_cost, total_minutes}
- rich table report.

experiments/noise.py: run the same cfg (runs/v1/agent.json) on the BLIND set 3 separate times (3 runs/persona each);
report mean and stdev of pass_rate. Save results/noise.json. This stdev is our minimum meaningful difference.
Tests: 3 hand-written transcripts (clear pass / clear fail / ambiguous) to sanity-check the judge.
```

**Done when:** `results/noise.json` exists with mean ± stdev for V1 on the blind set.

---

## S7 · Person 2 · 2:45–4:00 · Analyzer + test generator + patcher + gate

```
Implement the post-simulation boxes. The analyzer, test generator and patcher may ONLY see runs on personas tagged "train"
(assert this in code). The gate uses "heldout".

1. analyze/analyzer.py (LLM ANALYZER): input = failed ScoredRuns on train. Output FailureReport:
   - group failures into GENERALIZED behavioral bugs (not persona-specific), each with a generalized_rule the agent should follow.
   - for each bug decide culprit: agent | simulator (persona broke character / impossible info) | judge (verdict contradicts tool log).
     Only culprit=agent bugs go forward.
   - layer: prompt | tool_schema | first_message.
2. testgen/unit_tests.py (LLM TEST GENERATOR): for each agent bug, create 1-2 UnitTests: prefix_turns that lead right up to the
   failure point (taken from the real failing transcript), expectation text, tool_assertions. Save runs/<version>/unit_tests.json.
   Unit tests accumulate across iterations (regression suite).
3. patch/patcher.py (LLM PATCHER): produce V(n+1) from V(n) + FailureReport.
   Two modes (flag): "free" = rewrite the system prompt freely; "surgical" = for each bug apply ONE edit:
   add/replace a rule in the relevant stage, tighten a tool description/parameter schema, or edit first_message.
   Surgical mode: max prompt growth 15%; output a Patch list (before/after/rationale). Set parent_version.
4. loop/gate.py (REGRESSION GATE): candidate vs current best on HELDOUT personas, 3 runs each, plus all unit tests:
   COMMIT iff pass_rate(candidate) >= pass_rate(best) AND no heldout persona that best passed 3/3 drops to <=1/3
   AND unit-test pass rate does not drop. Otherwise DISCARD. Print reasons.
```

**Done when:** one manual analyzer → patcher → gate pass produces a COMMIT or DISCARD with reasons.

---

## S8 · Both · 4:00–5:15 · Loop orchestrator + the experiment

```
Implement agentforge/loop/run_loop.py and agentforge/experiments/compare.py.

run_loop.py: run_pipeline(domain_dir, platform, mode, max_iters=3, patch_mode="surgical") -> best AgentConfig
  V1 = build_agent -> generate adversary+coverage personas -> split -> for i in range(max_iters):
    simulate train (3 runs) -> score -> analyzer -> unit tests -> patcher -> candidate ->
    gate on heldout + unit tests -> COMMIT (best = candidate) or DISCARD -> regenerate adversary personas against the new best
  Log every iteration to runs/loop_log.jsonl (version, pass rates, decision, prompt length, minutes, cost).

compare.py — the only numbers that matter tonight. Score each variant on the BLIND set
(domain/kasko/blind_personas.json + blind_assertions.json), 3 runs per persona:
  A. builder only (v1)
  B. full loop, patch_mode="surgical"
  C. full loop, patch_mode="free"
Print a table: blind pass_rate, pass^3, per-assertion failures, prompt length, iterations committed/discarded, minutes, $.
Mark each difference vs A as "above noise" or "within noise" using results/noise.json.
Save results/compare.json and results/compare.md.
```

**Done when:** `results/compare.md` has blind-set numbers for A, B (and C if time allows).

---

## S9 · Both · 5:15–6:00 · Results + Freya port notes

```
1. Read results/compare.md, results/noise.json, runs/loop_log.jsonl. Write results/DECISION.md:
   which variant to use tomorrow, how many loop iterations fit in the time budget (minutes per iteration),
   the top 5 recurring bug types the analyzer found (these will likely appear in Freya's hidden simulations too),
   and builder-prompt improvements to apply before the loop starts.
2. Write docs/freya_port.md mapping our Platform methods to Freya endpoints
   (spec: https://docs.freyavoice.ai/api-reference/openapi.json, base https://app.freyavoice.ai/api/v2, bearer auth,
   envelope {success, data:{message, result}}):
   - upsert_agent -> POST /agents, then branches/commit for candidates
   - run_conversation -> POST /chat/message loop, then POST /chat/close (triggers Freya's own assertion analysis!) and GET call details
   - native sims -> POST /personas (our persona JSON as-is), POST /simulations {agentId, agentVersionId, mode, runsPerPersona}
   - run_unit_test -> POST /unit-tests (input.messages, assertions tool_call, expectation)
   - replay -> POST /chat/fork
   Mark unknowns as TODO(ask-organizers): how assertion UUIDs for simulations are created, rate limits, voice vs chat in scoring.
3. Implement platform/freya.py with the same method signatures; implement what's unambiguous, stub the rest with TODOs.
```

**Done when:** `results/DECISION.md` and `docs/freya_port.md` are committed.

---

## Tomorrow: decision rule
- **B (loop) beats A above noise** → run the loop on Freya for as many iterations as time allows.
- **B within noise of A** → spend the time on the builder prompt + the top-5 bug list from `DECISION.md`; use the loop as a final check.
- **First thing on Freya:** confirm that `POST /chat/close` returns Freya's own assertion results. If yes, use Freya's scorer in the gate instead of ours.

## Questions for organizers (first hour)
1. Are scoring simulations voice or chat?
2. Are any scoring scenarios/assertions visible beforehand?
3. One task or multiple hidden tasks?
4. Is a compliance violation an automatic fail?
5. Limits on build time / simulation credits / rate limits?
6. Where do simulation assertion UUIDs come from? Can workflows be created via API?
