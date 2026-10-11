# Local simulator (scripts/local_sim.py)

Diagnosis only. Ship decisions come from Freya runs. It runs an existing compiled `workflow.json` (no rebuild) against the persona Freya gets.

## Roles
| role | local | Freya (freya.py) |
|---|---|---|
| agent: extraction, routing, dialogue | Sonnet through `claude_cli` (`llm._claude_cli`, one `claude -p` call each) | `AGENT_LLM` = provider/model `experimental-5` (env `FREYA_AGENT_PROVIDER` / `FREYA_AGENT_MODEL`), also used as `routingLlmOverride` and `extractionLlmOverride` |
| customer | `google/gemini-3-flash-preview`, OpenRouter, temperature 0.7 (Freya's own `SIM_LLM`) | `SIM_LLM` = google `gemini-3-flash-preview` |
| judge | `google/gemini-3-flash-preview`, OpenRouter, temperature 0 | `SIM_LLM` (`analysisLlmOverride`) |
**Freya's agent is `experimental-5`; we cannot use it. The local Sonnet agent is probably stronger, so local passes on agent-capability
behaviour are optimistic** (it records the promise, keeps the digits, answers the robot question where Freya's agent did not). Structural
bugs (wrong node, missing transition, wrong variable) reproduce; capability failures may not.

## Engine semantics (builder/agentic/localsim/engine.py, imported unchanged)
Per customer message: (1) extraction of the current node's `extraction_schema` (one model call); variables found are stored, an enum value outside the list is dropped; (2) routing: deterministic transitions in list order, then global nodes, then the `matches_intent` descriptions of the node and the globals in ONE model call; `loop_condition`, `max_node_turns` / `max_turn_transition`; (3) dialogue: system prompt + node `role_message` + `Current Task` (+ `loop_prompt` after the first turn, + the entry prompt), with the node's tools; a tool call runs, its result is flattened into `<tool>_response.*` variables, routing runs again, up to 6 tool rounds. Code nodes run their snippet on entry, `api_request` nodes run their `pre_actions`, passthrough nodes route at once, `on_enter` tts/llm/silent as in docs/workflow-format.md; `end_call` nodes end the call and say their custom message; the workflow-level end_of_call tools run when the call ends.
- Tools run against the vendor mock bank logic (`mockbank.Bank` + `HANDLERS`, in process, same seeded accounts as `tcc_shared_bank.py`; it is the same code the daemon serves, so the argument schemas and responses are the bank's). Not a separate local port.
- Personas: `tools/run_cases.py persona_for(case, {"identity": ...}, case.get("style"))`, the prompt Freya gets. Cases: the DEV cases only (the first 10 of the family-spread order, as `tcc_eval_freya.py --limit 10`).
- Output per conversation: `out/template_cc/localsim/<set>/<brief>/<case>.<rep>.json` (transcript, node path, extracted variables, tool calls + bank responses, judge checks, ledger result).

## Where this is a GUESS
1. **Agent adapter (GUESS):** the agent returns JSON `{say, tool_calls}` instead of the platform's native tool-calling; extraction/routing prompts are ours. Freya's prompts for these are unknown.
2. **Opening / first line:** the engine speaks the `on_enter` of `start`/`opening`; Freya's chat route may differ (GUESS that it matches).
3. **Max turns (GUESS):** 30 customer turns and 900 s per conversation; Freya ends a simulated call at `maxCallDurationSeconds` (420) or when the agent ends the call.
4. **Judge (GUESS):** Freya's judge reads the conversation and the persona's `successCriteria`. Ours also gets the recorded tool calls as text, and answers yes/no per criterion; the case passes when the bank ledger (`score_ledger`) passes AND every criterion is yes, as in `tcc_eval_freya.py`.
5. **Latency, interruptions, voice/TTS:** not simulated.
6. **Variable carry-over, `node_turns`, `non-list mappings`:** as the engine docstring (platform-facts.md); the platform's own behaviour for edge cases is not verified here.
7. **Customer:** since the second calibration it is Freya's own model; the first one (Llama-3.1-8B) mis-said digits and drifted off the script (75% agreement).

## Limits
DEV cases only (never GATE, never `out/template_cc/eval/sealed/`); at most 60 conversations; concurrency 3; the first claude usage/rate-limit warning stops the run (no retry).

## Calibration (set p6, DEV cases 1-10 of brief-a and f3-kestrel, x1) vs the existing Freya p6r1/p6r2 verdicts
Freya's p6r1 and p6r2 agree on all 20 cases, so the ceiling is 100%.
1. Llama-3.1-8B customer + Sonnet judge: **75%** (15/20). Disagreements A-002, A-003, F3-014, F3-027 (local FAIL) and F3-039 (local PASS):
   the customer (garbled digits, ignored the script's wrong answers, asked the robot question at another moment). Re-run of the five: three then agreed.
2. Gemini-3-flash-preview customer (temperature 0.7) + Gemini-3-flash-preview judge (temperature 0): **80%** (16/20). Local FAIL / Freya PASS: none.
   Local PASS / Freya FAIL: A-025, F3-003, F3-021, F3-032. In each the bank ledger shows Freya's agent recorded no promise / the wrong outcome
   (or failed identity) where the local agent did: the cause is the agent model / engine difference (local Sonnet is stronger), not the customer and not the judge.


## Shared budget and the sealed counts mode (added for the 85 push)
- One budget for every session that runs `scripts/local_sim.py`: `out/template_cc/localsim/_budget/` holds `count.json` (conversations used so far,
  cap `LOCALSIM_CAP`, default 300 in total; 69 were already used), four cross-process concurrency slots (`LOCALSIM_SLOTS`, default 4) and the `STOP` file.
  A conversation waits for a free slot, then claims one count; when the cap is reached nothing new starts.
- The first claude usage / rate-limit warning in any run writes `_budget/STOP`: every local sim run stops starting conversations and says so.
  Tell the user; remove the file only on their word.
- `--sealed`: GATE cases 11-20 of the given briefs, counts only. No transcript, ledger or failed criterion is written or printed; the only output is
  the per-brief pass/fail counts in `out/template_cc/localsim/sealed_counts.json`. It is the only way local_sim touches GATE cases (the 18:45 m2-vs-m1 check).
- Local judge and customer: `google/gemini-3-flash-preview` (Freya's own). The local agent (Sonnet) is probably stronger than Freya's `experimental-5`.
