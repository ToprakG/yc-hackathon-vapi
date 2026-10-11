# Self-test and repair loop for an unseen brief

`scripts/final_run.sh` uses the final window (no test cases, up to 3 h) to test the freshly built agent on Freya and repair it.

```
build (final_build.sh)  ->  static pre-check  ->  scenarios  ->  Freya run  ->  patcher rounds  ->  last-green build + report
```

1. **Build**: fresh extraction + compile with the kept flags. `--from-set <set>` takes an already built dev set instead.
2. **Static pre-check** (`policy_precheck.py`, no simulation): a policy field that disagrees with its own `_source` quote goes to R1; rebuild if a value changed.
3. **Scenarios** (`selftest_cases.py`): no fixed count: one scenario per rule type the policy has (16 on f5), plus `--extra N` variants in other speaking styles only when more than 100 min are left; the rule types come from the policy (S3's `rule_coverage.py` is not merged here yet; `present_rule_types` is used if it appears) (identity refusal, robot question at turn 1 and mid-call, human request, hardship with own terms, vague date, spoken/pieces identity, floor amount, dispute, already paid, restructuring, deceased, multi-product, ...). Account data, the bank config and the expected ledger come from `policy.json`; the persona script comes from one `claude_cli:sonnet` call; the success criteria are brief sentences only (each carries an exact brief quote that is checked, otherwise it is dropped). No testbed file is read.
4. **Run** (`selftest_run.sh`): own mock bank behind a cloudflared tunnel, Freya personas (`persona_for`, `create_personas`), one simulation. Freya plays the customer and judges (no OpenRouter). The ledger is scored too. It takes a lane lock (same lock dirs as `run_cases.sh`), timeout 1800 s.
5. **Patcher** (`selftest_repair.py`), at most 3 rounds or until T-30. Diagnosis is deterministic first (ledger diff -> policy pointers), then at most one model call per failed scenario. Allowed actions only:
   - **R1** policy field: re-run the extract verifier for that field; accept only a value with an exact brief quote.
   - **R2** disable a parametric code rule for this brief (`final_build.sh --disable`), only flags in `R2_ALLOW` and only with a brief quote that the rule contradicts.
   - **R3** replace a fixed line with the brief's own sentence (quote-checked).
   - **R4** prompt patch, only for a scenario built from a brief rule marked UNKNOWN: the sentence verbatim plus an IF/THEN restatement in the unlocked zone of its stage.
   - Never compiler code; never a field of a rule that has a passing scenario.
   - **Acceptance:** all actions of a round are built together; only the failed scenarios and 3 previously passing ones are re-run (a broken one once more). The round is kept only if at least one failure is fixed and nothing breaks; otherwise the last green build stays.
6. **Output**: `<out>/workflow.json` + `policy.json` (last green), `final_run.log` (time per stage), `patch_report.json`, `selftest_report.md`.

## Command

```
scripts/final_run.sh <brief files...> <tool-api.json> <out-dir> [--set-flags F1,F2] [--from-set p10] [--briefs-parallel 1]
# FINAL_END=<epoch> (default now+3h; nothing starts after FINAL_END-30min), MAX_ROUNDS=3, LANE_WAIT=1800
```

Environment (names only): `FREYA_API_KEY`, `FREYA_BANK_TEAM_KEY`, `FREYA_STATE_FILE` (set by the lane script), `FREYA_SIM_CONCURRENCY`, optional second lane via `../yc-w2/w2_env.sh` (`SELFTEST_LANES=1 2`), `FEATURES` / `FINAL_FLAGS.txt`, `SELFTEST_API`, `SELFTEST_PERSONA_DIR`, `POLICY` (final_build.sh: compile this policy instead of extracting), `LANE`, `LANE_WAIT`. Needs `cloudflared` and a logged-in `claude` CLI (`claude_cli:sonnet`).

`R2_ALLOW` (one constant in `selftest_repair.py`): `f17*`, `f19_refusal_rule`, `f22_forbidden_disclosure`, `f24_day_once`, `f25_dispute_wins`. Core flags f1-f15 and f18/f20/f21 are never disabled.

## Hidden briefs: sequential jobs with a budget

```
FINAL_MODE=patcher_on scripts/final_run.sh --budget-min 30 --ship-min 26 --set-flags "$(cat M1_FLAGS.txt)" \
  --job "briefA1.md briefA2.md|toolsA.json|out/A" --job "briefB.md|toolsB.json|out/B"
```
Jobs run one after the other (one simulation at a time per workspace), each with its own budget: nothing runs past start+26 min, the last green build is copied to `<out>` at the latest then. A repair round starts only if ROUND_S (720 s in budget mode) fits before the ship time; `FINAL_MODE=patcher_off` skips repair. One Freya workflow slot per brief run (`SELFTEST_SLOT`). Expect no repair round in 30 min unless the first run is short: build ~3 min, scenarios + pre-check ~2 min, first Freya run 10-15 min.

## Trace, Freya save, LLM provider

- `final_run.sh` saves to Freya by default (`FINAL_SAVE=freya`, slot `final-<out name>`, one key, `FREYA_API_KEY_W2` unset): the first build via run.py, and the last-green build (patched or rebuilt) is saved again to the same slot by `final_trace.py`; workflow id and agent id are in the trace and in `<out>/build_report.json["saved"]`. Repair candidates are never saved (`FINAL_SAVE=none` inside the patcher).
- `final_trace.py` appends to the trace that run.py wrote (`build_report.json["trace"]`: trace.txt + events.jsonl): one `selftest_scenario` event per scenario and round (id, name, rule type, pass/fail, judge verdict summary, ledger diff) and one `patcher_action` event per action (round, action, field, kept/reverted, fixed, broken), plus the Freya save.
- Budget mode runs the 10 most important rule types (identity refusal/failed, right party, robot, dispute, floor, vague date, hardship, human/transfer, callback; `MAX_SCENARIOS`) so a repair round fits before T+26.
- Every model call of the self-test tools goes through `llm.call_llm`, so `TCC_LLM_PROVIDER=anthropic` (+ `ANTHROPIC_API_KEY`) works without a Claude Code login (`TCC_SELFTEST_MODEL` overrides the model string). Tested with a mocked transport.

## Outage guard and Freya retries

- A self-test run with no tool call in any scenario (needs 2+ scenarios, or all MISSING) is an outage signature, not a result: `results.json["outage"]=true`. `final_run.sh` re-runs once after 60 s if time allows; the patcher never acts on it (status `outage`, the build is kept); a repair round that shows it is re-run once after 60 s, else discarded. All of it is logged in the trace (`outage` events). The turn-time part of the signature (~0 s) is not measured; the no-tool-call part is.
- Every Freya call in `selftest_run.py` (personas, simulation, iteration, call, save) and the final save/export in `final_trace.py` retries on a 5xx: 3 calls, 10 s apart (`selftest_common.py`). run.py's own first save is not covered.

## Fault tools (patcher development)

`inject_faults.py <set> <brief> [--combo ids]` (clean policy + known faults, compiled), `record_faults.py` (record the self-test of the faulty builds once, in as few simulations as possible), `patcher_eval.py` (offline: detected / action chosen / correct / fixes the field; `--abstain` runs the dev failures, where the right answer is "not patchable").

## Numbers so far

- f5 dry run (treated as unseen), clean build: build 159 s, scenarios 36 s, Freya run 709 s (bank+tunnel 68 s, simulation 621 s; plus about 10 min waiting for the shared workspace), patcher 52 s. 12 scenarios, 8 passed. The patcher took no action on the 4 failures (agent bugs in rules the brief states, not patchable).
- Abstain check on 33 p6 dev failures: 0 proposals (it was 2 R2 proposals before the allow-list, then 1 R1 on a verifier call that varies between runs).

## Patcher numbers on injected faults

`patcher_eval` on 6 faults (5 in one f5 build, 1 in a brief-a build; 2 Freya simulations): iteration 1 detection 50%, iteration 2 detection 100% / correct action 100% / fixes the field 100% (same recordings, run twice). Caution: the fixes of iteration 2 were made after seeing these 6 faults (scenario priority, number words and verbatim lines in the static pre-check, the meaning of `right_party` for the verifier), so 100% is tuned, not held out. Abstain check after the allow-list and quote rules: 0/33.

## Held-out faults (patcher not changed after seeing them)

8 new faults on f3 and f7 (different fields from the tuned set): detection 7/8, correct action 7/8, fixes the field 7/8 (88%). Static pre-check alone found 5/8 (callback end, holiday, dispute outcome code, id_decline, a corrupted verbatim line); the f3 Freya run (1 simulation) found the dispute note value and the removed rule as R4. Missed: `floor_field` (the floor amount read from the overdue field): the floor scenario failed on the judge, but the diagnosis did not point at `/product_types/*/floor_field`. Tuned set: 6/6. The patcher is frozen from 12:45.

## Not tested yet

- No R2 fault could be injected (none of the allowed flags exist in the p10 builds).
- The accept/revert path with a real candidate (rebuild, subset re-run, keep or revert) has not run end to end; no action has been proposed on a real failure yet.
- R2 on a real allowed flag (the p10 builds have none of them).
- `final_run.sh` as one command since the last edits (its stages were run separately).
