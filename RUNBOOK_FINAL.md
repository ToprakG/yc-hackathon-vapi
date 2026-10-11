# RUNBOOK_FINAL: the 20:00 run (Istanbul time)

Hidden briefs open **20:00**, hard deadline **23:00**, our target: **submit by 21:30**.

Two hidden briefs, run **one after the other** (one Freya simulation at a time per workspace). Budget per brief: 30 min, shipped by minute 26.
Times below assume start at 20:00: brief 1 20:00 to 20:30, brief 2 20:30 to 21:00, packaging by 21:10, submit by 21:30 (23:00 is the hard limit, 90 min of slack for a re-run).

## 0. Before 20:00 (5 min)
- `git status` clean on the commit that will be submitted (`git rev-parse HEAD`; S0 merges, so check this is the merged hash).
- `.env` keys present (**names only**): `FREYA_API_KEY`, `FREYA_BANK_TEAM_KEY`, `FREYA_WORKSPACE_ID`, `FREYA_API_URL` (default staging URL).
  There is **no** Anthropic / OpenRouter key in the final setup: the only LLM path is the local `claude` login (`claude_cli`).
  `FREYA_API_KEY_W2` is never used (final_run unsets it).
- One read-only Freya check (no loop). If it 5xx's, see section 4.
- `cloudflared` is installed (`cloudflared --version`); `.venv310/bin/python` exists; no other eval holds `out/template_cc/eval/lane1.lock`.
- Put the two briefs and their tool specs in a fresh dir, e.g. `hidden/b1.md`, `hidden/b1.openapi.json`, `hidden/b2.md`, `hidden/b2.openapi.json`.
  The brief name (output folder) is taken from `--job`'s out dir, not from the file.

## 1. The command (both briefs, sequential)

```bash
cd <repo>   # the checkout that holds the submitted commit
# LLM provider: claude_cli only (leave TCC_LLM_PROVIDER unset), see "LLM provider" below
FINAL_MODE=$(cat FINAL_MODE.txt) FINAL_VOTES=3 \
scripts/final_run.sh --budget-min 30 --ship-min 26 \
  --job "hidden/b1.md|hidden/b1.openapi.json|out/final/b1" \
  --job "hidden/b2.md|hidden/b2.openapi.json|out/final/b2" \
  2>&1 | tee out/final/final_run.all.log
```

### LLM provider: variant A (claude_cli) is the ONLY path
- Set nothing (`TCC_LLM_PROVIDER` unset or `claude_cli`). The builder calls `claude -p` with model `sonnet`; needs the Claude login on this machine and no usage limit.
- There is no switch-to-anthropic / openrouter fallback in the final setup (no keys). If the preflight stops, see "Quota" below.
- **Preflight (automatic):** `final_run.sh` starts every brief with one tiny call to the chosen provider (`scripts/llm_preflight.py`, 25 s limit). It logs `LLM preflight ok: provider X ...` or `STOP: no usable LLM provider` with the reason and exits 1 for that brief within 30 s. Run it by hand first: `.venv310/bin/python scripts/llm_preflight.py`. `SKIP_PREFLIGHT=1` turns it off.

Currently `FINAL_MODE.txt` = `patcher_on`. Flags are not passed: `final_run.sh` reads them itself via `scripts/final_flags.sh` = `FINAL_FLAGS.txt` if it exists, else `M1_FLAGS.txt` (17 flags now). **Switching to m2 = write the m2 list into `FINAL_FLAGS.txt`** (one line, comma-separated, committed). Check what will be used: `bash scripts/final_flags.sh . <main checkout>`; the log line `final_run: ... flags: ...` shows it per brief. An explicit `--set-flags` still overrides.
If a brief has several files, put them space-separated in the first field: `--job "a.md b.md|tools.json|out/final/b1"`.
Run it in `tmux`/`nohup` so a closed terminal does not kill it.

Single brief (re-run after a failure): same command with one `--job`.

## 2. What happens per brief (and typical time)
| stage | typical | log line (`<out>/final_run.log`) |
|---|---|---|
| build: 3 extractions + vote, fixups, compile, lint, save to Freya | 160 to 270 s | `stage build: Ns` |
| precheck (quotes / numbers / verbatim lines), rebuild only if it changed a value | 0 to 25 s (+ about 120 s if a rebuild happens) | `stage precheck`, `stage rebuild` |
| cases (10 most important rule types) | about 40 s | `stage cases` |
| run_r0: bank + tunnel (about 70 s), one Freya simulation, verdicts | 600 to 720 s | `stage run_r0` |
| repair round 1 (only if at least 720 s are left before minute 26) | 400 to 700 s | `stage repair` |
| finalize (trace, export last-green to Freya) | 5 to 60 s | `stage finalize` |

## 3. What to watch in the logs
- `tail -f out/final/b1/final_run.log`: every line has `T-30 in N min`. Stages must follow the table above.
- `stage build: ... exit 0` then `<out>/build.out` ends with `lint ... 0 errors`. Exit not 0 is a section 4 case.
- `precheck` lines: `changed` fields are fine if each has a brief quote; the log names them.
- `OUTAGE SIGNATURE in the first run`: Freya returned no tool calls. Nothing is repaired from it; one re-run after 60 s happens by itself. Still outage: the build ships untested (`STATUS=outage`). Do not treat it as a result.
- `repair skipped: Ns before ship time`: expected when run_r0 was slow. Not an error; the first build ships.
- `repair: GREEN <dir>` or `FINAL <dir>`: last-green dir. `patch_report.json` lists every patcher action (only R1 to R4).
- `no lane free`: another eval holds lane 1. Check `cat out/template_cc/eval/lane1.lock/tag`; a stale lock (dead pid) is removed automatically.
- Final line per brief: `final_run: done ...`; deliverables `<out>/workflow.json`, `policy.json`, `selftest_report.md`, `patch_report.json`, `build_report.json`.

## 4. If something fails
**Brief 1 fails (non-zero exit, no `workflow.json`)**
1. Do not wait: brief 2 already runs by itself (jobs are independent). Open `<out>/final_run.log` and the last stage's log (`<out>/build.out`, `<out>/r0/build.log`).
2. Extraction or compile error: re-run brief 1 alone *after* brief 2 finishes with `FINAL_VOTES=1` (about 90 s faster) and the same flags.
3. Time is short (after 20:50): run it offline, `--offline` (no Freya, about 3 to 4 min), then save with `FINAL_SAVE=freya scripts/final_build.sh ...` or `scripts/final_run.sh` without `--offline` and `FINAL_MODE=patcher_off` (build + saved workflow + one test run, no repair). An untested build is better than none.
4. Never edit `graph.py`, the compiler, or the policy by hand during the run.

**Freya 5xx / runner down**
- Every Freya call retries 3 times, 10 s apart. Past that: one read-only check (`GET /api/v2/workspaces`), then wait, no polling loop.
- While it is down, brief 1 and 2 still build (build is offline). Run with `FINAL_SAVE=none` if even saving fails; the submission then has no workflow id, so tell S0 and re-save with `scripts/final_build.sh` once Freya answers.
- Outage guard is automatic (see section 3).

**Claude usage limit / LLM errors (preflight STOP)**: there is no other provider. Do not start the build; see "Quota" (below): wait for the limit to reset or tell S0. Re-run the failed brief when `scripts/llm_preflight.py` says ok.

## 4b. Quota (the claude_cli quota is the ONLY path to the final build)
- **19:45 preflight:** `.venv310/bin/python scripts/llm_preflight.py` (one tiny `claude -p` call, 25 s limit; exit 0 = usable). Run it once at 19:45, by hand. If it fails
  (`LLM preflight FAILED ...`): do not retry in a loop; check `claude` login and the usage-limit message, wait, retry every 5 minutes at most. `final_run.sh` repeats the same check per brief.
- **No claude_cli call of any kind after 19:15**, except the rehearsal (f3, about 17:00) and the 19:45 preflight. That covers every session (S1-S4): local sims, extractions, patcher runs, evals with the local judge.
- **local_sim.py enforces it:** it refuses new (normal) conversations from 18:30, the `--sealed` check until 19:15, and makes no claude call at all after 19:15 (`LOCALSIM_CUTOFF=1830`, `LOCALSIM_HARD_STOP=1915`). The first usage / rate-limit warning in any run writes `out/template_cc/localsim/_budget/STOP` and stops all local sim runs.
- Budget today (all sessions): local_sim 300 conversations in total, 4 concurrent; the 18:45 sealed check is 4 briefs (brief-b, f3, f5, f7) x m1 and m2 = 80 conversations.
- If a usage warning appears at any time: stop everything that calls claude, tell S0, and keep the remaining quota for the 20:00 run.

## 5. Packaging and submission
1. After both briefs finished (about 21:00):
   ```bash
   scripts/package_submission.sh out/final
   ```
   It copies workflow.json, build_report.json, policy.json, trace.txt, events.jsonl to `out/final/submission/<brief>/`, exports the Freya workflow
   (`freya_export.workflow.json`), scans the package for secret values (stops with `STOP:` if one is found), and prints the form fields.
2. Check the printout: both briefs have a **workflow id**; no `PROBLEMS:` block (except known ones you understand); commit hash equals the merged one.
   Trace check: `.venv310/bin/python scripts/check_trace.py out/final/b1 --freya --selftest` (every field `ok`).
3. Fill the form (about 21:10): team name, repo URL, commit, run command (`scripts/final_run.sh <brief files> <tool-api.json> <out dir>` as in README_RUN.md), per brief the workflow id and the trace.
4. **Submit by 21:30** (hard deadline 23:00). If packaging is not clean by 21:20, submit the unpacked `out/final/<brief>/workflow.json` plus trace and fix details afterwards if the form allows.
5. Push only branch artifacts that are allowed; never push `.env`, `.freya-agents*.json`, persona caches, `out/` results, or transcripts.

## 6. Timing summary (from the pipe9 builds and the f5 dry run)
- Worst case to ship, repair skipped: 270 (build) + 25 + 120 (rebuild) + 40 + 720 (run_r0) + 60 = about 1240 s = **21 min**. Budget 30 min, ship 26 min.
- Typical: build 210 + cases 40 + run_r0 650 = 900 s, leaving 660 s before minute 26. That is under `ROUND_S=720`, so repair is skipped. Rehearsal runs use `ROUND_S=540`; use the same value on the night if the rehearsal shows a round fits.
