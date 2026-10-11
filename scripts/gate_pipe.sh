#!/bin/bash
# GATE (sealed) on the workflow final_run.sh SHIPPED for f6, next to m1's f6 GATE score.
#   scripts/gate_pipe.sh <final_run out dir of f6>      e.g. out/rehearsal/f6     (needs <dir>/workflow.json and policy.json)
# Puts the shipped build in set f6pipe, runs the f6 GATE cases (--skip 10 --limit 10, ONLY_BRIEFS=f6-corvid-memo), tag f6pipe_g1
# (a tag ending in g<n> is SEALED: only pass/fail and the failed-criterion category are written outside sealed/), then prints it
# next to m1g1's f6 row. Takes a lane like every eval (run_cases.sh lock wait).
cd "$(dirname "$0")/.." || exit 2
SRC=${1:?final_run out dir of f6}; B=f6-corvid-memo
[ -f "$SRC/workflow.json" ] || { echo "no $SRC/workflow.json: run final_run.sh first"; exit 2; }
MAIN=$(cd "$(git rev-parse --git-common-dir)/.." && pwd)
D=out/template_cc/f6pipe/$B; mkdir -p "$D"
cp "$SRC/workflow.json" "$SRC/policy.json" "$D/"; cp "$SRC/build_report.json" "$D/" 2>/dev/null
echo "$(date +%H:%M:%S) f6pipe_g1 on the shipped workflow $(shasum "$D/workflow.json" | cut -c1-8)"
ONLY_BRIEFS=$B scripts/run_cases.sh . f6pipe f6pipe_g --skip 10 --limit 10 1 | tail -4
echo "--- m1g1 (f6):"
f=$MAIN/out/template_cc/eval/freya/$B.m1g1.json; [ -f "$f" ] || f=out/template_cc/eval/freya/$B.m1g1.json
python3 - "$f" "out/template_cc/eval/freya/$B.f6pipe_g1.json" <<'PY'
import json, os, sys
for name, f in (("m1g1", sys.argv[1]), ("f6pipe_g1", sys.argv[2])):
    if not os.path.exists(f):
        print(f"{name}: not available ({f})"); continue
    d = json.load(open(f))
    print(f"{name}: {d['passed']}/{d['cases']}  fails: " + " ".join(x["case"] + "(" + ",".join(x.get("failed", [])) + ")" for x in d["rows"] if not x["pass"]))
PY
