#!/bin/bash
# The 20:00 sequence, one stage at a time (nothing runs by itself).   CASE=case/<folder> TEAM="..." MEMBERS="Ad Soyad:mail;Ad2 Soyad2:mail2" scripts/final_go.sh <stage>
#   mock     convert_case.sh -> mock_load_case.sh (PUT spec, e2e, reset); prints mock_url                     (needs MOCK_ADMIN_TOKEN in .env)
#   freeze   scripts/freeze.sh: clean tracked tree + dress2 ALL OK + secret scan -> tag final-submit, push main + tag to origin
#   build    the REAL build with current main: builder/build.py $CASE $MOCK_URL --members "$MEMBERS" --out out/final/build  (FINAL_FLAGS, FINAL_MODE.txt)
#   check    scripts/dress_check_tr.py out/final/build's parent (live checks: tool URLs = mock_url/v1, language, export, submission.json, trace)
#   commit   copy nothing: git add workflows/<slot>.workflow.json + the trace dir + submission.json, finish_submission.py, commit, push origin main (no tag move)
#   rerun    21:20 second build into out/final2 (run AFTER `commit`: build.py overwrites ./submission.json and workflows/<slot>.workflow.json; if the check is not ALL OK they are
#            restored from git, so the committed submission stays; if ALL OK run `commit` again)
# MOCK_URL defaults to https://bank-mock.tccbank2026-yc.workers.dev/freyabank
cd "$(dirname "$0")/.." || exit 1
CASE=${CASE:?CASE=case/<folder>}; MOCK_URL=${MOCK_URL:-https://bank-mock.tccbank2026-yc.workers.dev/freyabank}; SPEC=${SPEC:-freyabank}
MEMBERS_ARGS=(); IFS=';' read -ra MM <<< "${MEMBERS:-}"; for m in "${MM[@]}"; do MEMBERS_ARGS+=(--member "$m"); done
names() { echo "${MEMBERS:-}" | tr ';' '\n' | sed 's/:.*//' | paste -sd, -; }
case ${1:-} in freeze|build|rerun) scripts/check_no_case_leak.sh || { echo "NO-HARDCODE GUARD FAILED: fix the builder diff first (generic only)"; exit 3; };; esac
case ${1:?stage} in
  mock)   mock/convert_case.sh "$CASE" "$SPEC" && scripts/mock_load_case.sh "mock/spec.$SPEC.json" "$SPEC";;
  freeze) FREEZE_RETAG=1 scripts/freeze.sh;;
  build)  rm -rf out/final; mkdir -p out/final
          python3 builder/build.py "$CASE" "$MOCK_URL" --variant "${VARIANT:-agentic}" --localsim off --max-minutes "${BUILD_MIN:-25}" --members "$(names)" --out out/final/build 2>&1 | tee out/final/build.out; tail -1 out/final/build.out > out/final/build_py.json;;
  check)  D=${2:-out/final}
          if [ "${VARIANT:-agentic}" = agentic ]; then .venv310/bin/python scripts/check_agentic_build.py "$D" "$MOCK_URL" | tee "$D/check.txt"
          else .venv310/bin/python scripts/dress_check_tr.py "$D" FINAL_FLAGS.txt live-mock "${MOCK_URL%/}/v1/" | tee "$D/check.txt"; fi;;
  commit) S=$(python3 -c "import json;print(json.load(open('submission.json'))['workflow'])"); T=$(python3 -c "import json;print(json.load(open('submission.json'))['trace'])")
          git add -f "$S" "$T"; .venv310/bin/python scripts/finish_submission.py --team "${TEAM:?TEAM}" "${MEMBERS_ARGS[@]}" --out submission.json && git add submission.json
          git commit -q -m "submission: workflow + trace + submission.json (real build)" && .venv310/bin/python scripts/secret_scan.py origin/main..main | tail -1 && git push origin main;;
  rerun)  rm -rf out/final2; mkdir -p out/final2
          python3 builder/build.py "$CASE" "$MOCK_URL" --variant "${VARIANT:-agentic}" --localsim off --max-minutes "${BUILD_MIN:-25}" --members "$(names)" --out out/final2/build 2>&1 | tee out/final2/build.out; tail -1 out/final2/build.out > out/final2/build_py.json
          if scripts/final_go.sh check out/final2 | grep -q "VERDICT: ALL OK"; then echo "FINAL2 ALL OK: replace the submission (run: commit)"; else git checkout -- submission.json workflows/ 2>/dev/null; echo "FINAL2 NOT ALL OK: submission.json + workflows/ restored from the commit (build.py had overwritten them); keep out/final as the submission"; fi;;
  *) echo "unknown stage"; exit 2;;
esac
