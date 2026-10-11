"""Verdict of one reserved fix-verification slot.   python3 scripts/slot_verdict.py <name>   (reads out/template_cc/eval/reserved_slot_<name>.env)
Rule: a fix goes in only if its slot GAINS (sum over its briefs > baseline) and NO brief DROPS. Baseline per brief: m2bg1 (m2b), else m2a0g1, else pipe9g1.
Pass/fail counts only (shared rows)."""
import json
import re
import sys

name = sys.argv[1]
env = open(f"out/template_cc/eval/reserved_slot_{name}.env").read()
get = lambda k: re.search(rf'^{k}=("?)(.*?)\1\s*$', env, re.M).group(2)
SET, PFX, BRIEFS = get("SET"), get("PFX"), get("BRIEFS").split()
E = "out/template_cc/eval/freya"


def score(b, tag):
    try:
        return json.load(open(f"{E}/{b}.{tag}.json"))["passed"]
    except (OSError, KeyError, ValueError):
        return None


gain = drop = 0
lines = []
for b in BRIEFS:
    new = score(b, f"{PFX}1")
    base, src = next(((score(b, t), t) for t in ("m2bg1", "m2a0g1", "pipe9g1") if score(b, t) is not None), (None, "-"))
    if new is None or base is None:
        lines.append(f"{b}: no result ({PFX}1={new}, baseline {src}={base})")
        continue
    gain += new - base
    drop += new < base
    lines.append(f"{b}: {new} vs {base} ({src}) {'+' if new > base else ''}{new - base}")
done = all(score(b, f"{PFX}1") is not None for b in BRIEFS)
verdict = "INCOMPLETE" if not done else ("KEEP (gains, no brief drops)" if gain > 0 and not drop else "DROP (" + ("a brief drops" if drop else "no gain") + ")")
print(f"slot {name} (set {SET}): " + "; ".join(lines) + f" -> {verdict}")
