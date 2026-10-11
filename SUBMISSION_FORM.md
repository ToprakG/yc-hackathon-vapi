# Submission form: draft for the two final briefs

Fill the `<...>` fields after the 20:00 builds. Nothing here needs Freya or a model call.

## Fields

| field | value |
|---|---|
| Team name | `TEAM_NAME` (placeholder: write the real name at submit time) |
| Repo URL | `https://github.com/ToprakG/yc-hackathon-vapi.git` (check: `git remote get-url origin`) |
| Commit | tag `final-submit`; the hash is `git rev-parse final-submit` (the tag is created in step 4 below, after the workflow and trace files are committed) |
| Run command | `python3 builder/build.py {brief_path} {tool_api_path}` |
| | A brief that builds on another ("Brief B is Brief A with ..."): `python3 builder/build.py {base_brief_path} {brief_path} {tool_api_path}` (later file overrides). A reference that is not passed in the call is taken from `briefs/*.md`, else WARN and built alone. |
| Workflow file, brief 1 | `workflows/tcc-<stem of brief 1's last file>.workflow.json` |
| Workflow file, brief 2 | `workflows/tcc-<stem of brief 2's last file>.workflow.json` |
| Trace, brief 1 | `traces/<dir>/trace.txt` (+ `events.jsonl` in the same dir); `<dir>` = the `trace` path printed by build.py (`tcc-final-tcc-<stem>-<timestamp>`) |
| Trace, brief 2 | same, from the second run |
| Workflow / agent ids (if asked) | `out/tcc/<slot>/build_report.json` -> `saved.workflow_id`, `saved.agent_id` |

`build.py` defaults (tcc variant): 30 min budget, ship by minute 26, FINAL_MODE from `FINAL_MODE.txt`, flags from `FINAL_FLAGS.txt` (else `M1_FLAGS.txt`), output `out/tcc/<slot>/`, slot = `tcc-<stem of the last brief file>`. It prints one JSON line with `status`, `slot`, `saved`, `trace`.

## After the 20:00 runs: what must be committed

Only these (never `git add .`, never the whole `traces/` or `out/`):

1. `workflows/tcc-<stem1>.workflow.json`, `workflows/tcc-<stem2>.workflow.json` (the Freya exports; see gap G1 for how to get them)
2. the two trace directories named in the build.py output: `traces/<dir1>/` and `traces/<dir2>/` (each holds `trace.txt` and `events.jsonl`, about 20 KB)
3. `FINAL_FLAGS.txt` if it was changed after the last push (and any last code fix that S0 approved)

Not committed: `out/`, `.env`, `.freya-agents*.json`, persona caches, the other `traces/tcc-*` dirs (extraction, self-test, rehearsal runs).

```bash
# 0. before 20:00: dry check of the packaging path on the last rehearsal output (no Freya)
scripts/package_submission.sh --dry out/rehearsal          # copies + secret scan; lists what would be exported

# 1. after BOTH builds (run from the repo root)
scripts/package_submission.sh out/tcc                      # exports the Freya workflow of every out/tcc/<slot>/ to out/tcc/submission/<slot>/freya_export.workflow.json,
                                                           # scans the package for key values (stops with STOP: if one is found), prints the form fields
for s in tcc-<stem1> tcc-<stem2>; do                       # G1 workaround: put the exports at the committed path if build.py did not (workflows/<slot>.workflow.json missing)
  [ -f workflows/$s.workflow.json ] || cp out/tcc/submission/$s/freya_export.workflow.json workflows/$s.workflow.json
done
grep -rIl -E "$(grep -hoE '(FREYA_API_KEY|FREYA_BANK_TEAM_KEY|ANTHROPIC_API_KEY|OPENROUTER_API_KEY)=.+' .env | cut -d= -f2- | paste -sd'|' -)" workflows traces/<dir1> traces/<dir2> && echo "STOP: key value found" || echo "no key values"

# 2. commit explicit paths only
git add workflows/tcc-<stem1>.workflow.json workflows/tcc-<stem2>.workflow.json traces/<dir1> traces/<dir2>
git status --short | grep -v '^??'                         # review: only the files above (+ FINAL_FLAGS.txt if changed)
git commit -m "final: workflows and traces for the two final briefs"

# 3. push the branch S0 designates (never force)
git push origin <branch>

# 4. the tag the form points at
git tag final-submit && git push origin final-submit && git rev-parse final-submit
```

## Gaps found and how they were closed

- **G1 (fixed, `84266d7`):** `final_trace.py` now also exports the unchanged first build to `<out>/<slot>.workflow.json`, so `build.py` copies it to `workflows/<slot>.workflow.json`. The `cp` workaround in step 1 above stays as a safety net (it only copies when the file is missing).
- **G2 (docs only):** at 20:00 save BOTH hidden briefs into `briefs/` as `00-<name>.md` first (file placement; the `00-` prefix makes them sort before our dev `brief-a.md`/`brief-b.md`), then run `build.py` per brief. The resolver finds the referenced brief in `briefs/`. See `RUNBOOK_FINAL.md`.
- **G3 (fixed):** `package_submission.sh` prints the official run command.
- **README_RUN.md (fixed):** `build.py` as the command, the `workflows/` and `traces/` paths, Claude Code install + login, `cloudflared`, `.env` vs `env.sh`, `FREYA_BANK_TEAM_KEY` needed for the self-test.
