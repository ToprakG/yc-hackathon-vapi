# Claude Code prompt — Builder v1 + variants

Paste from the repo root. Read HACKATHON_PLAN.md first; it is the source of truth.

````
Read HACKATHON_PLAN.md fully before doing anything. It contains the hackathon facts, the three builder variants (A1, A-agent, A-hybrid), the evaluation protocol and the platform limits. Follow it.

Hard rules (from the organizers):
- Entry point: python3 builder/build.py {brief_path} {tool_api_path}. Runs alone, no human input, no manual edits after it runs.
- Output: a Freya WORKFLOW (steps, prompts, tools, conditional routes), created/updated via freya.py, exported with freya.export_workflow into workflows/.
- Never change the phone-agent model in freya.py.
- The agent may call only the 7 kit tools. Read tool fields and allowed values from the tool API file at runtime; hardcode nothing from Brief A/B.
- Max 10 workflows: update in place, use the slot allocation in HACKATHON_PLAN.md §6.
- One Freya simulation at a time. Never parallel, never loop, never probe.
- Every build writes a trace (start/end time, each model call: model + one-line summary, workflow ID, agent ID, step and tool counts, self-tests + results). No keys in traces.
- Builder time limit 30 min per brief; target < 5 min for A1.

Reuse from this repo: agentforge/build/template.py content (as step prompts), self_check.py (hybrid repair), the decision-model judge and paired sign test in agentforge/experiments, and the fake briefs in agentforge/domain/collections (convert them to the kit's 7 tool names and tool-API format). Replace the keyword/regex core of extract.py with LLM extraction. Do NOT reuse the Vapi/local platforms, MODEL_SWEEP or the kasko domain for the submission. Commit 96324ac produced a single prompt instead of a workflow; the submission must be a workflow.

Phase 1 — Read the kit: briefs/, tools/openapi.json, public-test-set.json, docs/, freya.py, examples/minimal_builder.py, tools/run_cases.py. Use the Freya MCP (dev only) to inspect the workflow minimal_builder creates. Write KIT_NOTES.md: exact workflow structure Freya expects (steps, prompts, tool attachments, conditional routes, variables, how customer data and the current date reach the agent), every Brief A/B rule grouped by topic, every tool's fields/values/failure modes, every practice case and what passing requires, and anything contradicting HACKATHON_PLAN.md.

Phase 2 — Baseline, then STOP: run minimal_builder on A and B; run_cases.py --reps 3 for each (sequentially). Log one row per case per run to results/results.jsonl (config_id, brief, case, run, pass, outcome/policy/honesty, failure reason, tool sequence, timestamp). Write results/BASELINE_FAILURES.md: one line per failed case (check failed, what the agent did, rule broken), then failure types ranked by frequency. Stop and show me.

Phase 3 — A1 (after I confirm): builder/build.py, builder/trace.py, builder/extract.py (LLM → Policy JSON as in HACKATHON_PLAN.md §4), builder/compile_workflow.py (Policy → workflow template in §4), fallback deploy, export. Run on A and B with --reps 3, write results/A1_VS_BASELINE.md (paired per-case comparison, failure types gone/new).

Phase 4 — Generalization set: convert agentforge/domain/collections fake briefs to the kit's tool names and tool-API format; add a raw-material brief (email thread + policy extract + memo + code list, some rules only implied) and a multi-product brief; modify field names and allowed values in their tool-API files. Run A1 on all; fix generally, never per brief. Write results/GENERALIZATION.md.

Phase 5 — A-agent (time-boxed): skills/collections/SKILL.md with the same playbook as A1's template; builder/agentic.py runs headless Claude (non-interactive, allowlisted Freya MCP tools, max turns, wall-clock budget), every turn traced; must leave a valid workflow or build.py deploys A1. Flag it as dev-only if the organizers don't confirm reruns can invoke it.

Phase 6 — A-hybrid: A1 → agentic review/repair (missing rules vs Policy, routes, tool fields, local self-test) → deploy repaired only if valid and self-test no worse, else A1.

Phase 7 — Comparison: per HACKATHON_PLAN.md §5 (2 builds per variant on A, 1 on B, --reps 3, queued sequentially; plus fake briefs). Write results/VARIANTS.md with the decision per §5's rules.

After each phase: commit with a clear message and give me a short summary (what you did, numbers, what's next).
````
