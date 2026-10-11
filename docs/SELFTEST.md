# Self-test and repair loop for an unseen brief

`scripts/final_run.sh` uses the final window (no test cases, up to 3 h) to test the freshly built agent on Freya and repair it.

```
build (final_build.sh)  ->  static pre-check  ->  scenarios  ->  Freya run  ->  patcher rounds  ->  last-green build + report
```

1. **Build**: fresh extraction + compile with the kept flags. `--from-set <set>` takes an already built dev set instead.
2. **Static pre-check** (`policy_precheck.py`, no simulation): a policy field that disagrees with its own `_source` quote goes to R1; rebuild if a value changed.
3. **Scenarios** (`selftest_cases.py`): 8-12 per brief, one or two per rule type the policy has (identity refusal, robot question at turn 1 and mid-call, human request, hardship with own terms, vague date, spoken/pieces identity, floor amount, dispute, already paid, restructuring, deceased, multi-product, ...). Account data, the bank config and the expected ledger come from `policy.json`; the persona script comes from one `claude_cli:sonnet` call; the success criteria are brief sentences only (each carries an exact brief quote that is checked, otherwise it is dropped). No testbed file is read.
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

## Fault tools (patcher development)

`inject_faults.py <set> <brief> [--combo ids]` (clean policy + known faults, compiled), `record_faults.py` (record the self-test of the faulty builds once, in as few simulations as possible), `patcher_eval.py` (offline: detected / action chosen / correct / fixes the field; `--abstain` runs the dev failures, where the right answer is "not patchable").

## Numbers so far

- f5 dry run (treated as unseen), clean build: build 159 s, scenarios 36 s, Freya run 709 s (bank+tunnel 68 s, simulation 621 s; plus about 10 min waiting for the shared workspace), patcher 52 s. 12 scenarios, 8 passed. The patcher took no action on the 4 failures (agent bugs in rules the brief states, not patchable).
- Abstain check on 33 p6 dev failures: 1 proposal (F4-025, an R1 id_decline change the verifier backed with a quote; the current value looks right). It was 2 R2 proposals before the allow-list.

## Not tested yet

- `patcher_eval.py` on the fault recordings (detection and correct-action rates): recordings are queued on the lane.
- The accept/revert path with a real candidate (rebuild, subset re-run, keep or revert) has not run end to end; no action has been proposed on a real failure yet.
- R2 on a real allowed flag (the p10 builds have none of them).
- `final_run.sh` as one command since the last edits (its stages were run separately).
