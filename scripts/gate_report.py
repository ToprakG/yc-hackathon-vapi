"""Side by side per brief: python3 scripts/gate_report.py [tag ...]   (default: m1g1 pipe9g1 p6g1). Pass/fail counts only (the shared result files)."""
import glob
import json
import sys

tags = sys.argv[1:] or ["m1g1", "pipe9g1", "p6g1"]
BRIEFS = ["brief-a", "brief-b", "f1-nordhavn", "f2-ostral", "f3-kestrel", "f4-brightwell", "f5-halden-email", "f6-corvid-memo", "f7-lumen-codes"]
res = {t: {} for t in tags}
for t in tags:
    for f in glob.glob(f"out/template_cc/eval/freya/*.{t}.json"):
        d = json.load(open(f))
        res[t][d["brief"]] = (d["passed"], d["cases"])
print(f"{'brief':16s}" + "".join(f"{t:>10s}" for t in tags))
for b in BRIEFS:
    print(f"{b:16s}" + "".join(f"{('%d/%d' % res[t][b]) if b in res[t] else '-':>10s}" for t in tags))
common = [b for b in BRIEFS if all(b in res[t] for t in tags)]
print(f"{'sum (briefs in all)':16s}" + "".join(f"{sum(res[t][b][0] for b in common):>10d}" for t in tags) + f"   over {len(common)} briefs")
print(f"{'sum (all finished)':16s}" + "".join(f"{sum(v[0] for v in res[t].values()):>10d}" for t in tags))
