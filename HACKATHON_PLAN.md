# Hackathon Plan — Build the Builder (Freya × YC)

**Status:** supersedes ROADMAP.md, EXPERIMENT_PLAN.md and the parts of TEST_PLAN.md marked below.
**Source of facts:** https://www.freyavoice.ai/hackathon + the kit. Re-check against `docs/` in the kit; the kit wins on any conflict.
**Times:** all in Istanbul time (UTC+3).

---

## 1. The facts that drive every decision

| Fact | Consequence |
|---|---|
| Builder = `python3 builder/build.py {brief_path} {tool_api_path}`, runs alone, no manual edits | Everything the builder does must be code we commit. No interactive sessions. |
| Output = a Freya **workflow** (steps, prompts, tools, conditional routes). `minimal_builder` (one step) is "not a good score". | Single-prompt output is the baseline, not the target. Our commit `96324ac` (single prompt, "instead of a workflow graph") must be reversed for the submission. |
| Phone-agent model is **fixed** in `freya.py`, same for all teams | No agent model sweep. Builder model is free → use the strongest. |
| Phone agent may call **only** the kit's 7 tools: `verify_identity`, `get_account`, `create_promise`, `add_note`, `schedule_callback`, `transfer_to_agent`, `close_call` | Any other call fails the case. |
| Hidden briefs keep tool **names**; **fields and allowed values can change**. One hidden brief is a clean spec, the other is **raw bank material** (email, policy extract, memo, code list). | The builder reads the tool API file at runtime and hardcodes nothing. Keyword/regex extraction will not survive raw material → LLM extraction. |
| A case passes only if **Outcome** (records right: product, date, amount, recorded **once**) + **Policy** (judge model on the transcript) + **Honesty** (never claims a recording succeeded when the tool failed) all pass. A dispute recorded with no promise is a pass when the customer disputes. | Exactly-once `create_promise`, correct date resolution and tool-failure honesty are lethal points. |
| Final: 2 hidden briefs × 30 customers. **Each case runs 3×, passes only if all 3 pass.** Score = passes / 60. | Optimize run-to-run **consistency**. Practice with `--reps 3`. |
| Tie-breaks: 1) total promised amount on passed cases, 2) shorter build time, 3) earlier submission | Agent aims for the highest amount the policy allows (full payment first). Builder stays fast. |
| Builder limit **30 min per brief incl. self-tests** | Self-tests possible; they cost tie-break #2. |
| Workspace: **10 workflows max**, update in place | Fixed slot allocation (§6). |
| Practice: 13 cases (10 A, 3 B), text mode, `tools/run_cases.py <agent_id> --brief A [--reps 3]`. A 10-case run takes 3–11 min. **One simulation at a time** per workspace. Output: PASS/FAIL, tool-call sequence, failure reason. | Practice throughput ≈ 3–6 runs/hour. It is the bottleneck. Never run in parallel, never probe or load-test. |
| All practice cases are set on **Wed 14 Oct 2026, 11:00** | Inject the case's current date; resolve "next Friday" against it. |
| Trace required per hidden brief: start/end time, each model call (model + one-line summary), what was created (workflow ID, agent ID, step and tool counts), self-tests + results. No keys. Top 10: organizers clone, rerun, compare; a reviewer agent checks traces vs code. | Tracing is built in from the first line of `build.py`. Builds must be reproducible. |
| Hidden briefs open **Sun 20:00**. Submission form before **Sun 23:00**. After 20:00 only bug fixes, nothing from a hidden brief may enter code or prompts. | **Builder frozen by Sun 20:00.** 20:00–23:00 = run on 2 briefs (≤30 min each), tee traces, commit, export workflows, email the form. |

---

## 2. What we already have (repo audit)

| Piece | State | Use |
|---|---|---|
| `agentforge/build/extract.py` | Keyword/regex extraction into a thin `Policy` (language, plan_allowed, min payment, max months, disclosure, rules) | **Replace the core with LLM extraction** into a richer Policy (§4). Keep the role-mapping idea, but the kit's tool names are fixed now; what changes is fields/values. |
| `agentforge/build/template.py` | Renders a single prompt | **Reuse the content** as step prompts in the workflow compiler. |
| `self_check.py`, `best_of_k.py` | Exist | `self_check` → hybrid repair stage. `best_of_k` only if it pays for its build time. |
| `domain/collections/` (5 fake briefs: anadolu_tr, ege_strict, karadeniz_noplan, marmara_standard, trakya_oddformat; personas; unit tests; mock tool server) | Uses our own tool names | **Convert to the kit's 7 tool names + tool-API file format**; add a raw-material brief and a multi-product brief. This is the generalization set. |
| Decision-model judge, paired sign test, agreement, pairwise ranking (`experiments/`) | Built | Reuse for local triage and fake-brief scoring. |
| Vapi/local platforms, `MODEL_SWEEP`, kasko domain, adversary/patcher loop | Built for the old setup | **Do not use for the submission.** Practice cases give real failures now. |
| `results/DECISION.md` lessons | Measured yesterday | Apply: inject today's date, no hedging, disclosure once, ask key questions yourself, judge was too lenient. |

---

## 3. Three builder variants (all three get tested)

| Variant | What it is | Built from |
|---|---|---|
| **A1 · Claude pipeline** | Deterministic: LLM extracts Policy → fixed collections workflow template → workflow via `freya.py` | The core. Built first. Also the fallback for the other two and the safe submission. |
| **A-agent · Agentic** | Headless Claude (Agent SDK or `claude -p`, non-interactive) + collections **skill** + Freya MCP builds the workflow itself | Same playbook as A1's template, written as `SKILL.md`. |
| **A-hybrid** | A1 output → agentic review/repair (missing rules, wrong routes, tool-field mismatches, local self-test) → deploy the repaired version only if it validates and self-tests no worse; else deploy A1 | A1 + A-agent. Almost free once both exist. |

**Fairness:** all three use the same domain knowledge (A1 template content == skill content). Only the process differs.

**Agentic constraints (A-agent and A-hybrid):**
- Started by `build.py`, fully non-interactive: permissions pre-granted, MCP tools allowlisted, `--max-turns` and a wall-clock budget.
- Every agent turn written to the trace (model + one-line summary).
- Must leave a valid workflow within the budget, or `build.py` deploys A1.
- **Ask the organizers:** does a rerun environment allow invoking Claude Code / Agent SDK from `build.py`, and with whose key? If not allowed → A-agent and A-hybrid are dev-only tools, A1 ships.

---

## 4. Builder v1 (A1) — what it must produce

**Extraction (LLM, strongest model, temperature 0)** → Policy JSON:
identity rules · required statements (AI disclosure, recording notice, debt mention, mini-Miranda-style lines) · amounts, plans and limits (min down payment, max instalments, allowed dates) · promise rules · dispute route · already-paid route · hardship/vulnerability route · third-party rule · callback rule · escalation/transfer triggers · do-not-call / lawyer · closing rules · honesty rule · multi-product rules · each tool's fields and allowed values **read from the tool API file**. Works on clean specs and raw material. Ambiguity → conservative, compliant reading, logged in the trace.

**Workflow template:**
- Main path: greet (bank name, AI disclosure / recording notice if required, ask for the named customer **without mentioning the debt**) → `verify_identity` (must succeed before any account info) → `get_account` → required disclosures → negotiate (full amount first, then a plan strictly within limits, never invent discounts) → repeat back amount + date + method → `create_promise` **exactly once** (one per product in multi-product) → closing checklist → `close_call`.
- Side routes: wrong person / third party (never mention the debt, `add_note`, close) · cannot verify · dispute (`add_note`, no promise) · already paid · hardship · stop calling / lawyer · callback (`schedule_callback`) · abusive · escalation (`transfer_to_agent`) · "is this a scam?".
- Every step prompt: 1–2 sentence turns, rules as explicit if/then in call order, current date injected, narrate actions ("I've recorded your payment of X on DATE"), **honesty rule** (tool failed → say so, never claim success, follow the brief's failure path).
- Tool descriptions rewritten from the tool API file: when to call, prerequisites, exact field formats and allowed values, what to do on failure.

**Engineering:** `builder/build.py` entry point · `trace.py` from line one · timeouts + retries on every call · fallback deploy on any failure · one workflow per brief, updated in place · `freya.export_workflow` into `workflows/` · target build time < 5 min.

---

## 5. Evaluation protocol

**Unit of decision:** practice `--reps 3` on Brief A (10 cases) + Brief B (3 cases), per-case pass counts.
**Statistic:** paired per-case comparison vs the **current best** (sign test / Wilcoxon on per-case pass-count differences). Kazanç / gain = p < 0.1 + direction holds on a fresh re-run + no drop on critical case types. A "drop" uses the same paired test. (Unchanged from TEST_PLAN.md.)

**New because builders can be nondeterministic:** build each variant **2× on Brief A** and score every build. The final gets one build per hidden brief, so build-to-build variance counts as much as run-to-run variance.

**Generalization (decides between near-equal variants):** run every variant on the fake briefs (converted to the kit format), especially the raw-material brief and the modified tool-API files. Count: build failures, missing rules (self-check vs Policy), broken tool fields, local-sim pass rate.

**Cost estimate:** one build on A with `--reps 3` ≈ 10–30 min; on B ≈ 3–10 min. 3 variants × (2 builds on A + 1 on B) ≈ 1.5–3.5 h of **serial** simulation → queue overnight, read results while the next run goes.

**Decision rules**

| Result | Choice |
|---|---|
| Agent or hybrid beats A1 (gain) on practice **and** doesn't break on fake briefs | The better of those two |
| Agent ≈ hybrid | **Hybrid** (fallback safety) |
| Hybrid ≈ A1 | **A1** (faster build = tie-break, reproducible rerun, no agent risk) |
| Agent wins on practice but high build-to-build variance | Hybrid; A1 if variance survives the repair step |
| Agent can't finish reliably within 30 min | Drop it |

---

## 6. Workflow slots (10 max)

| Slot | Use |
|---|---|
| 1–2 | A1 on Brief A / B |
| 3–4 | A-agent on A / B |
| 5–6 | A-hybrid on A / B |
| 7–9 | Rotating: fake briefs, updated in place, deleted after scoring |
| 10 | Reserve (emergency / final run) |

---

## 7. Order of work and kill criteria

1. **Kit reading + baseline** (now): read `briefs/`, `tools/openapi.json`, `public-test-set.json`, `docs/`; run `minimal_builder` on A and B with `--reps 3`; read every failure reason by hand; group into outcome / policy / honesty.
2. **A1 end-to-end today.** First working version → keep it as the safe submission candidate.
3. **A-agent with a time box:** if it can't produce a valid workflow end-to-end by late tonight, park it; fold the skill content into A1's template.
4. **A-hybrid** as soon as A1 and A-agent both exist.
5. **Comparison queued overnight** (§5). Decide Sunday morning.
6. **Sunday until 20:00:** apply the lessons library, harden (odd briefs, timeouts, fallback, clean-clone test, pinned deps), final fake-brief run. **Freeze at 20:00.**
7. **Sunday 20:00–23:00:** run the frozen builder on both hidden briefs with `tee`, export workflows, commit code + workflows + traces, send the form (`team`, `repo`, `commit`, `run_command`, `workflows`, `traces`).

---

## 8. Changes to TEST_PLAN.md

- **Dropped:** agent model sweep (T1.1), all voice experiments, "single prompt vs workflow" as optional (workflow is expected; single prompt is only the baseline).
- **Moved up:** consistency across 3 runs; exactly-once `create_promise` with the right product/date/amount; date resolution; honesty after tool failure; dynamic tool-API reading; raw-material robustness.
- **New:** builder architecture comparison A1 / A-agent / A-hybrid (§3, §5); build-to-build variance; tie-break-aware choices (promise amount, build time).
- **Unchanged:** paired-test statistics, current-best comparison, re-run of every win, decision-model judge + calibration, acceptance gate, robustness section.

---

## 9. MCP and skills

- **Dev:** the Freya MCP may be used to inspect workflows/steps/routes, read practice results and debug failures. Before writing the compiler, inspect the workflow `minimal_builder` creates and record the exact structure Freya expects in `KIT_NOTES.md`.
- **Builder:** A1 talks to Freya only through `freya.py`. A-agent / A-hybrid may use MCP **only** inside `build.py`'s non-interactive agent stage, under the constraints in §3.
- **Skill = lessons library:** the collections playbook + workflow shape + every recurring practice failure as a general rule. When a failure type repeats, update the skill (and A1's template) once.
- MCP actions count toward platform limits: 10 workflows, one simulation at a time, no probing.

---

## 10. Open questions for the organizers (ask now)

1. May `build.py` invoke Claude Code / Agent SDK during the rerun? With whose key?
2. How are transcripts shown in practice results, beyond PASS/FAIL, tool sequence and failure reason?
3. Is the judge model's policy rubric available, or only the failure reason?
4. Does build time for the tie-break include self-tests and agent turns?
