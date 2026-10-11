#!/bin/bash
# The dress rehearsal with the OFFICIAL run command: python3 builder/build.py <brief> <openapi>. brief-b ALONE as a REAL run (Freya save + self-test + export; it must
# resolve "Brief A" from briefs/) and, in parallel, brief-a OFFLINE (--save none: no Freya, no lane). From the frozen flags (FINAL_FLAGS.txt). Then scripts/dress_check.py ->
# out/dress/report.txt. The dress run has lane priority: LANE_WAIT=900 lets the real run wait for a GATE brief that is still running.
#   scripts/dress_run.sh            runs now (needs FINAL_FLAGS.txt)
#   scripts/dress_run.sh --wait     waits until FINAL_FLAGS.txt exists AND it is 19:10 or later, then runs
cd "$(dirname "$0")/.." || exit 1
if [ "${1:-}" = --wait ]; then
  until [ -f FINAL_FLAGS.txt ] && [ "$(date +%H%M | sed 's/^0*//')" -ge 1910 ]; do sleep 15; done
fi
[ -f FINAL_FLAGS.txt ] || { echo "no FINAL_FLAGS.txt"; exit 2; }
set -a; [ -f .env ] && . ./.env; set +a; unset FREYA_API_KEY_W2
export LANE_WAIT=900
rm -rf out/dress; mkdir -p out/dress
{ echo "$(date +%T) dress run from commit $(git rev-parse --short HEAD) ($(git status --porcelain --untracked-files=no | grep -v ' traces/' | wc -l | tr -d ' ') tracked changes)"; echo "FINAL_FLAGS.txt: $(cat FINAL_FLAGS.txt)"
  echo "commands: python3 builder/build.py briefs/brief-b.md tools/openapi.json --out out/dress/brief-b   (real)  ||  python3 builder/build.py briefs/brief-a.md tools/openapi.json --out out/dress/brief-a --save none   (offline)"; } > out/dress/report.txt
run() { b=$1; shift; t=$(date +%s)
  python3 builder/build.py briefs/$b.md tools/openapi.json --out out/dress/$b "$@" > out/dress/$b.build.out 2>&1; rc=$?
  tail -1 out/dress/$b.build.out > out/dress/$b.build_py.json
  echo "$(date +%T) build.py $b: exit $rc, $(( $(date +%s) - t )) s: $(cut -c1-200 out/dress/$b.build_py.json)" >> out/dress/report.txt; }
run brief-b &
run brief-a --save none &
wait
.venv310/bin/python scripts/dress_check.py out/dress FINAL_FLAGS.txt --offline-briefs brief-a >> out/dress/report.txt 2>&1
echo "$(date +%T) done" >> out/dress/report.txt
