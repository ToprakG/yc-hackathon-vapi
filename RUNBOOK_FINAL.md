# RUNBOOK_FINAL: the 20:00 run (Istanbul time)

Hidden briefs open **20:00**, hard deadline **23:00**, our target: **submit by 21:30**.

Two hidden briefs, run **one after the other** (one Freya simulation at a time per workspace). Budget per brief: 30 min, shipped by minute 26.
Times below assume start at 20:00: brief 1 20:00 to 20:30, brief 2 20:30 to 21:00, packaging by 21:10, submit by 21:30 (23:00 is the hard limit, 90 min of slack for a re-run).

## FINAL FORMAT (read this first; it supersedes the "two briefs" wording further down)
At **20:00 we get ONE hidden brief** (plus its tool spec and, for the evaluation, its cases). We run `final_run.sh` (at most 30 min), then the evaluation sims on Freya
(`final_eval.sh`), then package and send. If the entry is in the top 10 the organizers re-run our builder 3 times on other briefs, so the submitted commit (`git describe final-submit`)
must reproduce: nothing outside the repo, `README_RUN.md` setup, the Claude login, one Freya key.

### Where the 20:00 files go (`<name>` = a short name you choose, e.g. `hidden1`)
| file | goes to | used by |
|---|---|---|
| the brief (one or more `.md`; a brief that builds on another is built together with it, list them in the same job) | `hidden/<name>.md` | `final_run.sh` |
| the tool spec (OpenAPI json) | `hidden/<name>.openapi.json` and a copy `testbed/fake_briefs/<name>/tools.openapi.json` | `final_run.sh`; `final_eval.sh` (mock bank) |
| the brief again | `testbed/fake_briefs/<name>/brief.md` (a copy; only documentation) | nobody reads it, keep it for the record |
| cases / bank config (only if you run `final_eval.sh`, which the final does not) | `testbed/fake_briefs/<name>/cases.json` and `config.json` | `final_eval.sh` |
`mkdir -p hidden testbed/fake_briefs/<name>` first. The builder (`final_run.sh`) reads only the brief(s) and the tool spec, never cases or config.

### The commands, in order
The OFFICIAL run command (what the organizers run again for the top-10 re-run) is `python3 builder/build.py <brief> [<more brief files>] <tool-api.json>`; it wraps `scripts/final_run.sh`
(flags from `FINAL_FLAGS.txt`, patcher mode from `FINAL_MODE.txt`, 3 extractions voted, self-test on Freya, repair rounds, the last-green workflow saved to Freya and exported).
```bash
cd <repo>      # the checkout at the tag final-submit (git describe must say final-submit)
# 1. build (at most 30 min; shipped by minute 26)
python3 builder/build.py hidden/<name>.md hidden/<name>.openapi.json --out out/final/<name> 2>&1 | tee out/final/build.log
# 2. package (workflow export from Freya, trace, build report, secret scan, the form fields)
scripts/package_submission.sh out/final
```
Results: `out/final/<name>/workflow.json` (last-green), the Freya export copied to `workflows/<slot>.workflow.json` (the committed path), the trace under `traces/tcc-final-*/` (trace.txt + events.jsonl), and the last line of
the build prints `{"status": "ok", "slot": ..., "saved": "workflows/...", "trace": "traces/..."}`. A brief that builds on another is built with it automatically (the referenced brief comes from the call or from `briefs/`).
**The evaluation sims are NOT part of the final**: the organizers score the exported agents, we do not submit sim results. `scripts/final_eval.sh` stays in the repo but is not run (the 19:20 rehearsal is cancelled).
Check after 1: `build_report.json` has `"status": "ok"`, lint 0; the build.py line says ok. Do not re-run with changed code. Never edit the compiler or policy during the run.

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
**Both hidden briefs go in the SAME `final_run.sh` call (two `--job`s, as above).** The call's briefs are the pool for brief references: a brief that says
"Brief B is Brief A with ..." / "same as Brief X" / "Brief X is not supplied" is built WITH the brief it refers to (found first among the briefs of this call, then in `briefs/*.md` by title letter or file name; the referenced brief goes first, the referring brief overrides).
Look for `brief refs: ref {...resolved...}` in `<out>/final_run.log` (and `<out>/brief_resolution.json`); `brief refs: WARN ... building alone` means the reference was not found: stop and pass the missing brief as an extra file in that job's first field.
After the extraction a **policy sanity check** runs (placeholder bands, empty attempt_plan, generic opening line, null transfer outcomes, "not supplied" notes): a degenerate policy is extracted once more; `DEGENERATE:` in `build.out` / `final_run.log` after that is a stop-and-look line (usually a missing referenced brief).
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
