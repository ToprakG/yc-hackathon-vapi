#!/bin/bash
# One command for the final night: fresh extraction (claude_cli:sonnet) -> compile with the kept flags -> lint -> report.
# Usage: scripts/final_build.sh <brief files...> <tool-api.json> <out-dir>
#   FEATURES=...   kept flag string (default: the features of out/template_cc/p4/brief-a/build_report.json)
#   FINAL_VOTES=3  number of independent extractions; id_decline and attempt_plan[*].cap_at_deadline are settled over them by
#                  builder.template_cc.final_vote (brief-text rule, else majority, else a verifier quote). 1 = a single extraction.
#   CONFIG=...     optional testbed config.json: also prints the policy_critical misses (scoring only; the builder never reads it)
# Nothing is sent to Freya (--save none; FREYA_API_KEY is removed from the build's environment).
cd "$(dirname "$0")/.." || exit 2
# --disable f17_x,f18_y : switch flags off for THIS brief only (a misbehaving rule), without touching the compiler
DISABLE=""; REST=()
while [ $# -gt 0 ]; do case "$1" in --disable) DISABLE="$2"; shift 2;; --disable=*) DISABLE="${1#--disable=}"; shift;; *) REST+=("$1"); shift;; esac; done
set -- "${REST[@]}"
[ $# -ge 3 ] || { echo "usage: $0 [--disable flag,flag] <brief files...> <tool-api.json> <out-dir>"; exit 2; }
ARGS=("$@"); OUT=${ARGS[$#-1]}; API=${ARGS[$#-2]}; BRIEFS=("${ARGS[@]:0:$#-2}")
FEATURES=${FEATURES:-$(cat FINAL_FLAGS.txt 2>/dev/null || python3 -c "import json;print(','.join(json.load(open('out/template_cc/p4/brief-a/build_report.json'))['features']))")}
{
  FEATURES=$(python3 - "$FEATURES" "$DISABLE" <<'PY'
import sys
sys.path.insert(0, ".")
from builder.template_cc import features as F
on = F.parse(sys.argv[1]) - F.parse(",".join(f for f in sys.argv[2].split(",") if f))
print(",".join(sorted(on)))
PY
)
  [ -n "$DISABLE" ] && echo "disabled for this brief: $DISABLE"
}
mkdir -p "$OUT"; T0=$(date +%s)
echo "features: $FEATURES"
[ -n "${FINAL_BUILD_DRY:-}" ] && exit 0
VOTES=${FINAL_VOTES:-3}; POLICY_ARG=()
if [ "$VOTES" -gt 1 ]; then
  echo "final vote: $VOTES independent extractions"
  PIDS=(); for i in $(seq 1 "$VOTES"); do
    env -u FREYA_API_KEY .venv310/bin/python -m builder.template_cc.run "${BRIEFS[@]}" "$API" --save none --audit off --features "$FEATURES" \
      --slot "final-$(basename "$OUT")-e$i" --out "$OUT/ext$i" > "$OUT/ext$i.log" 2>&1 & PIDS+=($!)
  done; for p in "${PIDS[@]}"; do wait "$p"; done
  POLS=(); for i in $(seq 1 "$VOTES"); do [ -f "$OUT/ext$i/policy.json" ] && POLS+=("$OUT/ext$i/policy.json"); done
  BARGS=(); for b in "${BRIEFS[@]}"; do BARGS+=(--brief "$b"); done
  rm -f "$OUT/policy.voted.json"
  [ ${#POLS[@]} -ge 2 ] && .venv310/bin/python -m builder.template_cc.final_vote "${POLS[@]}" "${BARGS[@]}" -o "$OUT/policy.voted.json" 2>&1 | tee "$OUT/final_vote.log"
  if [ -f "$OUT/policy.voted.json" ]; then
    POLICY_ARG=(--policy "$OUT/policy.voted.json")
  else echo "final vote: fewer than 2 extractions finished or the vote failed; extracting again in the final build"; fi
fi
# deterministic fixups from explicit brief phrases (id_decline, cap_at_deadline); the single-extraction path applies them inside extract.py
if [ -f "$OUT/policy.voted.json" ]; then
  BARGS2=(); for b in "${BRIEFS[@]}"; do BARGS2+=(--brief "$b"); done
  .venv310/bin/python -m builder.template_cc.policy_fixups "$OUT/policy.voted.json" "${BARGS2[@]}" | tee -a "$OUT/final_vote.log"
fi
env -u FREYA_API_KEY .venv310/bin/python -m builder.template_cc.run "${BRIEFS[@]}" "$API" --save none --audit off --features "$FEATURES" "${POLICY_ARG[@]}" \
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
