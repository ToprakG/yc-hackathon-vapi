#!/bin/bash
# One command for the final night: fresh extraction (claude_cli:sonnet) -> compile with the kept flags -> lint -> report.
# Usage: scripts/final_build.sh <brief files...> <tool-api.json> <out-dir>
#   FEATURES=...   kept flag string (default: the features of out/template_cc/p4/brief-a/build_report.json)
#   CONFIG=...     optional testbed config.json: also prints the policy_critical misses (scoring only; the builder never reads it)
#   RULE_COVERAGE=off      skip the rule-coverage step; RULE_COVERAGE_ENFORCE=0 report it without failing the build
# After the compile: unknown_rules.py injects every normative sentence that fits no rule type (verbatim, into its stage's
# prompt) and writes UNKNOWN.md; rule_coverage.py then lists the rules the compiler enforces only in prompt text or not at
# all, and the script exits 1 when there are any (rule types the compiler cannot enforce).
# Nothing is sent to Freya (--save none; FREYA_API_KEY is removed from the build's environment).
cd "$(dirname "$0")/.." || exit 2
[ $# -ge 3 ] || { echo "usage: $0 <brief files...> <tool-api.json> <out-dir>"; exit 2; }
ARGS=("$@"); OUT=${ARGS[$#-1]}; API=${ARGS[$#-2]}; BRIEFS=("${ARGS[@]:0:$#-2}")
FEATURES=${FEATURES:-$(python3 -c "import json;print(','.join(json.load(open('out/template_cc/p4/brief-a/build_report.json'))['features']))")}
mkdir -p "$OUT"; T0=$(date +%s)
echo "features: $FEATURES"
env -u FREYA_API_KEY .venv310/bin/python -m builder.template_cc.run "${BRIEFS[@]}" "$API" --save none --audit off --features "$FEATURES" \
  --slot "final-$(basename "$OUT")" --out "$OUT" > "$OUT/build.log" 2>&1; RC=$?
WALL=$(( $(date +%s) - T0 ))
BRIEFS_CSV=$(IFS=,; echo "${BRIEFS[*]}") python3 - "$OUT" "$RC" "$WALL" "$API" "${CONFIG:-}" <<'PY'
import json, re, subprocess, sys
from pathlib import Path
out, rc, wall, api, config = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
rep = json.loads((out / "build_report.json").read_text()) if (out / "build_report.json").exists() else {}
trace = Path(rep.get("trace", "")) / "trace.txt"
lines = trace.read_text().splitlines() if trace.exists() else []
def sec(l):
    m = re.match(r"(\d\d):(\d\d):(\d\d)", l); return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) if m else None
t = [(sec(l), l) for l in lines if sec(l) is not None]
start = t[0][0] if t else 0
ext = [s for s, l in t if "model call" in l and "extract" in l]
lint = next((s for s, l in t if "lint baseline" in l), None)
end = t[-1][0] if t else start
fmt = lambda a, b: f"{(b - a) % 86400}s" if a is not None and b is not None else "?"
print(f"stage extract (readings, verifier, pass 2, fix): {fmt(start, max(ext) if ext else None)}")
print(f"stage compile + lint:                            {fmt(max(ext) if ext else None, lint)}")
print(f"total wall: {wall}s (exit {rc}), status {rep.get('status')}")
print(f"lint: {rep.get('lint')}")
human = []
if rc != 0 or rep.get("status") != "ok": human.append("the build did not finish ok")
if (rep.get("lint") or {}).get("errors"): human.append("lint errors")
if (rep.get("extract") or {}).get("repairs"): human.append("policy defaults were applied: " + "; ".join(rep["extract"]["repairs"])[:200])
if any("policy default" in l for _, l in t): human.append("policy_check could not validate some fields")
print("needed a human:", "; ".join(human) if human else "no")
if config:
    r = subprocess.run(["python3", "scripts/policy_critical.py", str(out / "policy.json"), config, "--api", api] + sum([["--brief", b] for b in __import__("os").environ.get("BRIEFS_CSV", "").split(",") if b], []), capture_output=True, text=True)
    print("policy_critical:", r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[:200])
PY

RC2=0
if [ "${RULE_COVERAGE:-on}" != "off" ] && [ -f "$OUT/workflow.json" ] && [ -f "$OUT/policy.json" ]; then
  echo "--- rule coverage ---"
  env -u FREYA_API_KEY .venv310/bin/python -m builder.template_cc.unknown_rules "${BRIEFS[@]}" "$OUT/policy.json" "$OUT/workflow.json" \
    || echo "unknown_rules failed (exit $?)"
  .venv310/bin/python scripts/rule_coverage.py "${BRIEFS[@]}" "$OUT/policy.json" "$OUT/workflow.json" --out "$OUT" --quiet | tee "$OUT/rule_coverage.txt"
  RC2=${PIPESTATUS[0]}
  [ "$RC2" -eq 0 ] || echo "needed a human: rule types the compiler does not enforce in code (see $OUT/rule_coverage.txt, GAPS.md)"
fi
[ "$RC2" -eq 0 ] || exit "$RC2"
[ "$RC" -eq 0 ] || exit "$RC"
