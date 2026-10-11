#!/bin/bash
# The dress rehearsal of the final's shape: ONE final_run.sh --offline call with exactly brief-a + brief-b (two jobs), from the frozen commit, with the
# flags of FINAL_FLAGS.txt (final_run.sh reads it via scripts/final_flags.sh). No Freya. Then scripts/dress_check.py -> out/dress/report.txt.
#   scripts/dress_run.sh            runs now (needs FINAL_FLAGS.txt)
#   scripts/dress_run.sh --wait     waits until FINAL_FLAGS.txt exists AND it is 18:55 or later, then runs
cd "$(dirname "$0")/.." || exit 1
if [ "${1:-}" = --wait ]; then
  until [ -f FINAL_FLAGS.txt ] && [ "$(date +%H%M | sed 's/^0*//')" -ge 1855 ]; do sleep 15; done
fi
[ -f FINAL_FLAGS.txt ] || { echo "no FINAL_FLAGS.txt"; exit 2; }
mkdir -p out/dress; rm -rf out/dress/brief-a out/dress/brief-b
{ echo "$(date +%T) dress run from commit $(git rev-parse --short HEAD) ($(git status --porcelain --untracked-files=no | grep -v ' traces/' | wc -l | tr -d ' ') tracked changes)"; echo "FINAL_FLAGS.txt: $(cat FINAL_FLAGS.txt)"; } > out/dress/report.txt
FINAL_MODE=$(cat FINAL_MODE.txt 2>/dev/null || echo patcher_on) FINAL_VOTES=3 scripts/final_run.sh --offline --budget-min 30 --ship-min 26 \
  --job "briefs/brief-a.md|tools/openapi.json|out/dress/brief-a" --job "briefs/brief-b.md|tools/openapi.json|out/dress/brief-b" > out/dress/final_run.all.log 2>&1
echo "$(date +%T) final_run exit $?" >> out/dress/report.txt
.venv310/bin/python scripts/dress_check.py out/dress FINAL_FLAGS.txt >> out/dress/report.txt 2>&1
echo "$(date +%T) done" >> out/dress/report.txt
