"""Scoreboard of scripts/tcc_eval_testbed.py results: per brief and per family, for the given tags (merged)."""
import collections
import json
import sys
from pathlib import Path

D = Path(__file__).resolve().parents[1] / "out" / "template_cc" / "eval"
tags = sys.argv[1:] or ["s10"]
tot = collections.Counter()
fam = collections.defaultdict(collections.Counter)
print(f"{'brief':<18}{'passed':>8}{'scored':>8}{'unscored':>10}")
for f in sorted({p.name.split('.')[0] for p in D.glob("*.json")}):
    rows = []
    for t in tags:
        p = D / f"{f}.{t}.json"
        if p.exists():
            rows += json.loads(p.read_text())["rows"]
    if not rows:
        continue
    sc = [r for r in rows if not r.get("infra")]
    ok = sum(r["passed"] for r in sc)
    print(f"{f:<18}{ok:>8}{len(sc):>8}{len(rows) - len(sc):>10}")
    tot.update(passed=ok, scored=len(sc), unscored=len(rows) - len(sc))
    for r in sc:
        fam[r.get("family")].update(scored=1, passed=int(r["passed"]))
print(f"{'TOTAL':<18}{tot['passed']:>8}{tot['scored']:>8}{tot['unscored']:>10}"
      + (f"   ({100 * tot['passed'] / tot['scored']:.0f}%)" if tot["scored"] else ""))
print("\nby family:")
for k, c in sorted(fam.items(), key=lambda kv: kv[1]["passed"] / max(1, kv[1]["scored"])):
    print(f"  {str(k):<20}{c['passed']}/{c['scored']}")
