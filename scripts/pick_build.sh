#!/bin/bash
# One command to make a finished build THE submission:   TEAM=... MEMBERS="Ad:mail;Ad2:mail2" scripts/pick_build.sh C1|C3      (B is already committed: d72b6c5)
#   copies the build's Freya export + trace into this repo, sets submission.json (commit = the commit the build was locked to), runs
#   scripts/check_agentic_build.py (ALL OK required), commits workflow + trace + submission.json, scans the push range, pushes main. No tag move, no e-mail.
cd "$(dirname "$0")/.." || exit 1
set -e; set -a; [ -f .env ] && . ./.env; set +a
W=${1:?C1|C3}; N=${W#C}; case "$W" in C1) COMMIT=${RUN_COMMIT:-5e60d3a};; C3) COMMIT=${RUN_COMMIT:-6aef6bf};; *) echo "B is already committed (d72b6c5)"; exit 0;; esac
WT=/Users/alinebidal/yc-$W; MOCK=${MOCK_URL:-https://bank-mock.tccbank2026-yc.workers.dev/freyabank}; SLOT=case-freyabank-final-c$N
[ -s "$WT/out/final2/build_py.json" ] || { echo "$W has not finished (no $WT/out/final2/build_py.json)"; exit 2; }
TR=$(python3 -c "import json;print(json.load(open('$WT/out/final2/build/build_report.json'))['trace'])")
EXP="$WT/workflows/$SLOT.workflow.json"; [ -f "$EXP" ] || { echo "no export $EXP"; exit 2; }
mkdir -p traces workflows; cp "$EXP" workflows/; rm -rf "traces/$(basename "$TR")"; cp -R "$TR" traces/
python3 - "$WT" "$SLOT" "$(basename "$TR")" "$MOCK" <<'PY'
import json, sys, os
wt, slot, tr, mock = sys.argv[1:5]
s = json.load(open(f"{wt}/out/final2/build/submission.json"))
s["workflow"] = os.path.abspath(f"workflows/{slot}.workflow.json"); s["trace"] = os.path.abspath(f"traces/{tr}"); s["mock_url"] = mock
json.dump(s, open("submission.json", "w"), indent=1, ensure_ascii=False)
PY
git add -f "workflows/$SLOT.workflow.json" "traces/$(basename "$TR")"
[ -z "${PREP_ONLY:-}" ] && git commit -q -m "$W build (locked to $COMMIT): workflow export + trace" || true   # finish_submission wants the files committed
IFS=';' read -ra MM <<< "${MEMBERS:?MEMBERS}"; ARGS=(); for m in "${MM[@]}"; do ARGS+=(--member "$m"); done
if [ -n "${PREP_ONLY:-}" ]; then   # nothing is committed yet, so finish_submission (which wants tracked files) cannot run: write the same fields directly
python3 - "$COMMIT" "$TEAM" "$MEMBERS" "$MOCK" "$SLOT" "$(basename "$TR")" <<'PY'
import json, subprocess, sys, re
commit, team, members, mock, slot, tr = sys.argv[1:7]
repo = re.sub(r"//[^/@]*@", "//", subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip())
json.dump({"team": team, "members": [{"name": m.split(":")[0], "email": m.split(":")[1]} for m in members.split(";")], "repo": repo, "commit": commit,
           "run_command": "python3 builder/build.py {case_folder} {mock_url}", "workflow": f"workflows/{slot}.workflow.json", "trace": f"traces/{tr}/trace.txt", "mock_url": mock},
          open("submission.json", "w"), indent=1, ensure_ascii=False)
PY
else
.venv310/bin/python scripts/finish_submission.py --team "${TEAM:?TEAM}" --commit "$COMMIT" "${ARGS[@]}" --out submission.json > /dev/null
fi
# the check runs on the build's own out dir, with the finished root submission.json
CHK=$(.venv310/bin/python scripts/check_agentic_build.py "$WT/out/final2" "$MOCK" || true); echo "$CHK" | tail -14 | cut -c1-200
echo "$CHK" | grep -q "VERDICT: ALL OK" || { echo "CHECK NOT ALL OK: nothing committed (files are staged only)"; exit 3; }
scripts/check_no_case_leak.sh | tail -1
[ -n "${PREP_ONLY:-}" ] && { echo "PREP_ONLY: check ALL OK, files staged, NOT committed"; git add submission.json; exit 0; }
git add submission.json && git commit -q -m "submission: $W build (locked to $COMMIT): workflow + trace + submission.json"
.venv310/bin/python scripts/secret_scan.py origin/main..main | tail -1
git push origin main 2>&1 | tail -1; git rev-parse --short HEAD
