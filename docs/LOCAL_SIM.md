# Local simulator (scripts/local_sim.py)

Diagnosis only. Ship decisions come from Freya runs. It runs an existing compiled `workflow.json` (no rebuild) against the persona Freya gets.

## Roles
| role | local | Freya (freya.py) |
|---|---|---|
| agent: extraction, routing, dialogue | Sonnet through `claude_cli` (`llm._claude_cli`, one `claude -p` call each) | `AGENT_LLM` = provider/model `experimental-5` (env `FREYA_AGENT_PROVIDER` / `FREYA_AGENT_MODEL`), also used as `routingLlmOverride` and `extractionLlmOverride` |
| customer | `meta-llama/llama-3.1-8b-instruct`, OpenRouter, temperature 0.7 | `SIM_LLM` = google `gemini-3-flash-preview` |
| judge | Sonnet through `claude_cli` (`JUDGE_MODEL` is `anthropic:claude-sonnet-5-5`, which has no key here) | `SIM_LLM` (`analysisLlmOverride`) |
**The local agent model differs from Freya's.** Structural bugs reproduce; wording behaviour and which questions the agent answers may not.

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
7. **Customer:** Llama-3.1-8B is much weaker than Freya's Gemini customer: it mis-says digits, drifts off the script and asks questions at other moments.

## Limits
DEV cases only (never GATE, never `out/template_cc/eval/sealed/`); at most 60 conversations; concurrency 3; the first claude usage/rate-limit warning stops the run (no retry).

## Calibration (set p6, DEV cases 1-10 of brief-a and f3-kestrel, x1) vs the existing Freya p6r1/p6r2 verdicts
- Agreement local vs Freya p6r1 (= p6r2 on all 20 cases): 15/20 = **75%**.
- Disagreements: local FAIL / Freya PASS: A-002, A-003, F3-014, F3-027; local PASS / Freya FAIL: F3-039.
- Cause: **customer** for A-002, A-003, F3-027 (the 8B model gives five digits for "last four", garbles dates, rambles) and F3-014 (it answers the identity questions correctly where the script says wrong); F3-039: **customer timing + agent model** (the script has the customer ask "are you a robot?" right after the greeting; the Llama customer asked it later, and Sonnet answers such a question where Freya's agent ignored it). No disagreement came from the judge or the engine.
- Re-run of the five (x1): A-002 and F3-027 then agreed with Freya, F3-039 failed as in Freya; A-003 and F3-014 failed again. So most of the gap is customer noise at temperature 0.7.
- Pilot cost: ~9-12 claude calls and ~30-60 s per conversation; the Llama customer costs ~$0.0002 per conversation.
