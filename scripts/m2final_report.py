"""m2final (tag m2fg1) on all briefs: the 9-brief total and every brief that is 2+ below its best earlier result.   python3 scripts/m2final_report.py
Earlier results per brief: every non-ablation GATE tag of the day (m2bg1, m2a0g1, m2ag1, m2anofb_g1, m2a_fb_g1 is excluded: fallback ON, m2cg1, m2rg1, m2dg1, m2jg1, pipe9g1, p6g1).
Pass/fail counts only."""
import json

E = "out/template_cc/eval/freya"
BRIEFS = ["brief-a", "brief-b", "f1-nordhavn", "f2-ostral", "f3-kestrel", "f4-brightwell", "f5-halden-email", "f6-corvid-memo", "f7-lumen-codes"]
EARLIER = ["m2bg1", "m2a0g1", "m2ag1", "m2anofb_g1", "m2cg1", "m2rg1", "m2dg1", "m2jg1", "pipe9g1", "p6g1"]


def sc(b, tag):
    try:
        return json.load(open(f"{E}/{b}.{tag}.json"))["passed"]
    except (OSError, KeyError, ValueError):
        return None


tot = n = 0
warn = []
print(f"{'brief':16s}{'m2fg1':>7s}  best earlier (tag)")
for b in BRIEFS:
    now = sc(b, "m2fg1")
    best = max(((sc(b, t), t) for t in EARLIER if sc(b, t) is not None), default=(None, "-"))
    print(f"{b:16s}{('%d/10' % now) if now is not None else '-':>7s}  {best[0]}/10 ({best[1]})")
    if now is not None:
        tot += now
        n += 1
        if best[0] is not None and now <= best[0] - 2:
            warn.append(f"{b}: {now} vs best {best[0]} ({best[1]})")
print(f"\nm2final total over {n} finished brief(s): {tot}/{n * 10}" + ("" if n == 9 else f"  ({9 - n} brief(s) not finished)"))
print("briefs 2+ below their best earlier result:", "; ".join(warn) or "none")
