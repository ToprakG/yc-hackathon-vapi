#!/bin/bash
# The final-night loop for ONE unseen brief: final_build -> selftest_cases -> selftest_run -> selftest_repair (<= 3 rounds, or until T-30).
#   scripts/final_run.sh <brief files...> <tool-api.json> <out-dir> [--set-flags F1,F2] [--from-set SET] [--briefs-parallel 1]
#   --set-flags F   the kept flag string (default: env FEATURES, FINAL_FLAGS.txt, else the p4 report)
#   --from-set SET  no extraction: take policy/workflow/zones of this dev brief from out/template_cc/SET/<brief>/ (p10, m1 ...); the brief
#                   name is the folder of brief.md (testbed/fake_briefs/f5-...) or the stem of the file (briefs/brief-a.md)
#   --briefs-parallel N   accepted for the entry-point contract; one brief per call, the lane runs one eval at a time
#   FINAL_END=<epoch>  end of the working window (default now + 3 h); no new round starts after FINAL_END - 30 min
#   MAX_ROUNDS=3
# Result: <out>/workflow.json + policy.json = the LAST-GREEN build, <out>/final_run.log (time per stage), <out>/patch_report.json,
#         <out>/selftest_report.md. The builder never reads testbed files.
cd "$(dirname "$0")/.." || exit 2
MAIN=$(cd "$(git rev-parse --git-common-dir)/.." && pwd)
POS=(); FLAGS_ARG=""; FROM_SET=""
while [ $# -gt 0 ]; do case "$1" in
  --set-flags) FLAGS_ARG=$2; shift 2;; --set-flags=*) FLAGS_ARG=${1#*=}; shift;;
  --from-set) FROM_SET=$2; shift 2;; --briefs-parallel) shift 2;; *) POS+=("$1"); shift;; esac; done
set -- "${POS[@]}"
[ $# -ge 3 ] || { sed -n 2,12p "$0"; exit 2; }
ARGS=("$@"); OUT=${ARGS[$#-1]}; API=${ARGS[$#-2]}; BRIEFS=("${ARGS[@]:0:$#-2}")
mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd); API=$(cd "$(dirname "$API")" && pwd)/$(basename "$API")
BRIEFS_CSV=$(IFS=,; echo "${BRIEFS[*]}")
FEATURES=${FLAGS_ARG:-${FEATURES:-$(cat FINAL_FLAGS.txt 2>/dev/null || cat "$MAIN/FINAL_FLAGS.txt" 2>/dev/null || python3 -c "import json;print(','.join(json.load(open('$MAIN/out/template_cc/p4/brief-a/build_report.json'))['features']))")}}
export FEATURES SELFTEST_API=$API
T_START=$(date +%s); END=${FINAL_END:-$((T_START + 10800))}; CUT=$((END - 1800)); MAX_ROUNDS=${MAX_ROUNDS:-3}
LOG=$OUT/final_run.log; : > "$LOG"
say() { echo "$(date +%H:%M:%S) $*" | tee -a "$LOG"; }
left() { echo $(( (CUT - $(date +%s)) / 60 )); }
STAGES=()
stage() { local n=$1; shift; local t=$(date +%s)
  say "stage $n: start (T-30 in $(left) min)"
  "$@" >> "$OUT/$n.out" 2>&1; local rc=$?
  local s=$(( $(date +%s) - t )); STAGES+=("$n=$s"); say "stage $n: ${s}s, exit $rc"; return $rc; }
say "final_run: briefs ${BRIEFS_CSV}, window ends $(date -r "$END" +%H:%M), flags: $FEATURES${FROM_SET:+, from set $FROM_SET}"

# 1. build (fresh extraction + compile), or an already built set
GREEN=$OUT/r0
if [ -n "$FROM_SET" ]; then
  f=${BRIEFS[0]}; B=$(basename "$f" .md); [ "$B" = brief ] && B=$(basename "$(dirname "$f")")
  mkdir -p "$GREEN"; t=$(date +%s)
  cp "$MAIN/out/template_cc/$FROM_SET/$B"/{policy.json,workflow.json,zones.final.json,build_report.json} "$GREEN/" || { say "no build $FROM_SET/$B"; exit 1; }
  STAGES+=("build=$(( $(date +%s) - t ))"); say "stage build: taken from set $FROM_SET/$B"
  FEATURES=$(python3 -c "import json;print(','.join(json.load(open('$GREEN/build_report.json'))['features']))"); export FEATURES
else
  stage build bash scripts/final_build.sh "${BRIEFS[@]}" "$API" "$GREEN"
fi
[ -f "$GREEN/workflow.json" ] || { say "no workflow from the build: nothing to test"; exit 1; }

# 1b. static pre-check (no simulation): fields that disagree with their own _source quote -> R1 (verifier + brief quote), then rebuild
if [ -z "$FROM_SET" ] || [ -n "${PRECHECK:-}" ]; then
  stage precheck .venv310/bin/python scripts/policy_precheck.py "${BRIEFS[@]}" "$GREEN/policy.json" --out "$OUT/policy.fixed.json"
  if [ "$(tail -1 "$OUT/precheck.out" | python3 -c "import json,sys;print(json.loads(sys.stdin.read() or '{}').get('changed',0))" 2>/dev/null)" -gt 0 ] 2>/dev/null; then
    say "precheck changed fields: rebuilding from the fixed policy"; cp "$GREEN/policy.json" "$OUT/policy.extracted.json"
    stage rebuild env POLICY="$OUT/policy.fixed.json" bash scripts/final_build.sh "${BRIEFS[@]}" "$API" "$OUT/r0b" && [ -f "$OUT/r0b/workflow.json" ] && GREEN=$OUT/r0b
  fi
fi

# 2. scenarios (from the brief + the extracted policy only)
mkdir -p "$OUT/selftest"
stage cases .venv310/bin/python scripts/selftest_cases.py "${BRIEFS[@]}" "$GREEN/policy.json" --out "$OUT/selftest/cases.json"
STATUS=tested
if [ ! -s "$OUT/selftest/cases.json" ]; then say "no scenarios: delivering the build untested"; STATUS=untested
else
  export LANE_WAIT=${LANE_WAIT:-1800}
  stage run_r0 bash scripts/selftest_run.sh "$GREEN" --cases "$OUT/selftest/cases.json" --api "$API"
  [ -f "$GREEN/selftest/results.json" ] || { say "the first test run produced no results: delivering the build untested"; STATUS=untested; }
fi

# 3. repair rounds (inside selftest_repair.py: <= MAX_ROUNDS, stops at T-30, reverts a round that breaks anything)
if [ "$STATUS" = tested ]; then
  stage repair .venv310/bin/python scripts/selftest_repair.py --dir "$GREEN" --work "$OUT/repair" --briefs "$BRIEFS_CSV" --api "$API" \
      --cases "$OUT/selftest/cases.json" --deadline "$CUT" --rounds "$MAX_ROUNDS"
  R=$(tail -1 "$OUT/repair.out"); say "repair: $R"
  case "$R" in GREEN*|FINAL*) GREEN=${R#* };; esac
  [ -f "$OUT/repair/patch_report.json" ] && cp "$OUT/repair/patch_report.json" "$OUT/patch_report.json"
fi

# 4. deliver the last-green build + the report
cp "$GREEN/workflow.json" "$OUT/workflow.json"; cp "$GREEN/policy.json" "$OUT/policy.json"
[ -f "$GREEN/build_report.json" ] && cp "$GREEN/build_report.json" "$OUT/build_report.json"
python3 - "$OUT" "$GREEN" "$STATUS" "${STAGES[*]}" <<'PY'
import json, os, sys
out, green, status, stages = sys.argv[1:5]
st = dict(s.split("=") for s in stages.split())
r = json.load(open(os.path.join(green, "selftest", "results.json"))) if os.path.exists(os.path.join(green, "selftest", "results.json")) else None
pr = json.load(open(os.path.join(out, "patch_report.json"))) if os.path.exists(os.path.join(out, "patch_report.json")) else None
L = [f"# Self-test report ({status})", f"last-green build: `{green}`", "", "## Time per stage (s)", ""] + [f"- {k}: {v}" for k, v in st.items()]
if r:
    L += ["", f"## Scenarios on the delivered build: {r['passed']}/{r['cases']} passed", ""]
    for x in r["rows"]:
        L.append(f"- {x['case']} {x['rule']}: {'PASS' if x['pass'] else 'FAIL ' + ' | '.join(x['failed'])[:300]}")
    if r.get("missing"):
        L.append(f"- no verdict (not counted): {', '.join(r['missing'])}")
for rd in (pr or {}).get("rounds", []):
    L += ["", f"## Round {rd['round']}: {rd.get('result')} (fixed {rd.get('fixed')}, broken {rd.get('broken')}, {rd.get('seconds')} s)"]
    for a in rd["actions"]:
        L.append(f"- {a['case']} ({a.get('rule')}): {a['action']} {a.get('pointer') or a.get('flag') or ''} {a.get('how', '')} {a.get('diagnosis') or a.get('why') or ''}"[:300])
open(os.path.join(out, "selftest_report.md"), "w").write("\n".join(L) + "\n")
json.dump({"status": status, "green": green, "stages_s": st}, open(os.path.join(out, "selftest_report.json"), "w"), indent=1)
PY
say "done: $(( $(date +%s) - T_START ))s; workflow $OUT/workflow.json (from $GREEN); report $OUT/selftest_report.md"
