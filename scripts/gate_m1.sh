#!/bin/bash
# Single-lane plan: at 12:45 (and once out/template_cc/m1 exists) run the m1 GATE x1 (tag m1g1) on the same 9 briefs as p6g1, as a normal
# (non-background) run on lane 1.
# STANDING RULE: m1 (and m1x) are built ONLY from out/template_cc/policies_fixed/ (scripts/make_policies_fixed.py; build_set.sh and
# build_set_x.sh enforce it for set names m1*). This script refuses to run m1g1 on a set whose id_decline / cap_at_deadline differ from it; finished briefs are skipped. Then print the decision: m1 if m1g1 >= p6g1 over all 9 briefs.
cd "$(dirname "$0")/.." || exit 1
E=out/template_cc/eval; LOG=$E/gate_m1.log
log() { echo "$(date +%H:%M) $*" >> $LOG; }
log "waiting for 12:45 and set m1"
while [ "$(date +%H%M)" -lt 1245 ] || [ ! -d out/template_cc/m1 ]; do sleep 60; done
python3 - >> $LOG <<'PY' || { log "REFUSED: set m1 was not built from policies_fixed (rebuild: scripts/build_set.sh m1 <features>)"; exit 3; }
import json, sys
bad = []
for b in ["brief-a", "brief-b", "f1-nordhavn", "f2-ostral", "f3-kestrel", "f4-brightwell", "f5-halden-email", "f6-corvid-memo", "f7-lumen-codes"]:
    try:
        f = json.load(open(f"out/template_cc/policies_fixed/{b}/policy.json")); m = json.load(open(f"out/template_cc/m1/{b}/policy.json"))
    except OSError as e:
        bad.append(f"{b}: {e}"); continue
    key = lambda p: ((p.get("ask_limits") or {}).get("id_decline"), [s.get("cap_at_deadline") for s in p.get("attempt_plan") or []])
    if key(f) != key(m):
        bad.append(f"{b}: policies_fixed {key(f)} vs m1 {key(m)}")
if bad:
    print("\n".join(bad)); sys.exit(1)
PY
while [ "$(ls $E/freya/*.m1g1.json 2>/dev/null | wc -l)" -lt 9 ]; do
  log "starting m1g1"; scripts/run_cases.sh . m1 m1g --skip 10 --limit 10 1 >> $LOG 2>&1; sleep 60
done
python3 - >> $LOG <<'PY'
import glob, json
def tot(tag):
    t = n = 0
    for f in glob.glob(f"out/template_cc/eval/freya/*.{tag}.json"):
        d = json.load(open(f)); t += d["passed"]; n += d["cases"]
    return t, n
p, m = tot("p6g1"), tot("m1g1")
print(f"p6g1 {p[0]}/{p[1]}  m1g1 {m[0]}/{m[1]}  ->", "m1" if m[0] >= p[0] else "p6")
PY
