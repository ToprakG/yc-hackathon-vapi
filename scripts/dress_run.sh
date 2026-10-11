#!/bin/bash
# The dress rehearsal with the OFFICIAL run command: python3 builder/build.py <brief> <openapi>, once per brief: brief-a, then brief-b ALONE (it must resolve
# "Brief A" from briefs/). Real runs (Freya save + self-test + export), from the frozen commit, with the flags of FINAL_FLAGS.txt. Then scripts/dress_check.py ->
# out/dress/report.txt. Needs the Claude login, FREYA_API_KEY, cloudflared. Each run takes about 10-12 minutes.
#   scripts/dress_run.sh            runs now (needs FINAL_FLAGS.txt)
#   scripts/dress_run.sh --wait     waits until FINAL_FLAGS.txt exists AND it is 18:55 or later, then runs
#   OFFLINE=1 scripts/dress_run.sh  same, but --save none (no Freya; no export check)
cd "$(dirname "$0")/.." || exit 1
if [ "${1:-}" = --wait ]; then
  until [ -f FINAL_FLAGS.txt ] && [ "$(date +%H%M | sed 's/^0*//')" -ge 1855 ]; do sleep 15; done
fi
[ -f FINAL_FLAGS.txt ] || { echo "no FINAL_FLAGS.txt"; exit 2; }
set -a; [ -f .env ] && . ./.env; set +a; unset FREYA_API_KEY_W2
rm -rf out/dress; mkdir -p out/dress
{ echo "$(date +%T) dress run from commit $(git rev-parse --short HEAD) ($(git status --porcelain --untracked-files=no | grep -v ' traces/' | wc -l | tr -d ' ') tracked changes)"; echo "FINAL_FLAGS.txt: $(cat FINAL_FLAGS.txt)"; echo "command: python3 builder/build.py briefs/<brief>.md tools/openapi.json --out out/dress/<brief>${OFFLINE:+ --save none}"; } > out/dress/report.txt
for b in brief-a brief-b; do
  t=$(date +%s)
  python3 builder/build.py briefs/$b.md tools/openapi.json --out out/dress/$b ${OFFLINE:+--save none} 2>&1 | tee out/dress/$b.build.out | tail -1 > out/dress/$b.build_py.json
  echo "$(date +%T) build.py $b: exit ${PIPESTATUS[0]}, $(( $(date +%s) - t )) s: $(cat out/dress/$b.build_py.json | cut -c1-200)" >> out/dress/report.txt
done
.venv310/bin/python scripts/dress_check.py out/dress FINAL_FLAGS.txt ${OFFLINE:+--offline} >> out/dress/report.txt 2>&1
echo "$(date +%T) done" >> out/dress/report.txt
