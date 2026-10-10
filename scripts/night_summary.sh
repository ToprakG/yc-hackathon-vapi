#!/bin/bash
# Morning summary of the overnight eval queue (no LLM). Writes results/ablation/NIGHT_SUMMARY.md and prints it.
# Env: LADDER="f149br:f149b p2r:p2 p3r:p3 p4r:p4"  (tag prefix : set directory under out/template_cc/, "-" if none)  REPS=2
cd "$(dirname "$0")/.." || exit 2
exec python3 - "$@" <<'PY'
import glob, json, os, re, subprocess, sys
from pathlib import Path

REPO = Path.cwd()
EV = REPO / "out/template_cc/eval/freya"
LADDER = [x.split(":") for x in os.environ.get("LADDER", "f149br:f149b p2r:p2 p3r:p3 p4r:p4").split()]
REPS = int(os.environ.get("REPS", "2"))  # 0 = tags without a rep number (s10, f14)
RL = [""] if REPS == 0 else [str(r) for r in range(1, REPS + 1)]
BRIEFS = ["brief-a", "brief-b", "f1-nordhavn", "f2-ostral", "f3-kestrel", "f4-brightwell", "f5-halden-email", "f6-corvid-memo", "f7-lumen-codes"]
out = []
def say(s=""): out.append(s); print(s)
def run(*a):
    r = subprocess.run(["python3", *a], capture_output=True, text=True, cwd=REPO)
    return (r.stdout + r.stderr).strip()

say("# Night summary"); say()
say("## 1. Files present (briefs done / 9)"); say()
say("| tag | " + " | ".join(f"rep{r or 1}" for r in RL) + " | complete |"); say("|---|" + "---|" * (len(RL) + 1))
complete = {}
for pre, _ in LADDER:
    n = [sum((EV / f"{b}.{pre}{r}.json").exists() for b in BRIEFS) for r in RL]
    complete[pre] = all(x == 9 for x in n)
    say(f"| {pre} | " + " | ".join(f"{x}/9" for x in n) + f" | {'yes' if complete[pre] else 'NO - incomplete'} |")
q = REPO / "out/template_cc/eval/night_queue.log"
if q.exists():
    say(); say("Queue log (last 3 lines):"); say("```"); [say(l) for l in q.read_text().splitlines()[-3:]]; say("```")

say(); say("## 2. Stability per tag (solid / flaky / dead over the reps)"); say()
for pre, _ in LADDER:
    if complete[pre]:
        say(f"### {pre}"); say("```"); say(run("scripts/stability.py", *[f"{pre}{r}" for r in RL])); say("```")
    else:
        say(f"### {pre}: incomplete, skipped")

def grew(base, new):
    txt = run("scripts/failure_patterns.py", base, new)
    keep, cur = [], None
    for line in txt.splitlines():
        m = re.match(r"\[(\d+)\] .*\(was (\d+)\)", line)
        if m:
            cur = [line] if int(m.group(1)) > int(m.group(2)) else None
            if cur: keep.append(cur)
        elif cur is not None and line.strip():
            cur.append(line)
        elif not line.strip():
            cur = None
    return "\n".join("\n".join(c[:3]) for c in keep) or "(no cluster grew)"

say(); say("## 3. Ladder: each step against the last ACCEPTED step"); say()
kept = LADDER[0] if complete.get(LADDER[0][0]) else None
if kept is None:
    say(f"Baseline {LADDER[0][0]} is incomplete: no verdicts possible.")
decisions = []
for pre, setdir in LADDER[1:]:
    if kept is None:
        say(f"- {pre}: SKIPPED (no complete base)"); continue
    if not complete[pre]:
        say(f"- {pre}: INCOMPLETE ({'/'.join(str(sum((EV / f'{b}.{pre}{r}.json').exists() for b in BRIEFS)) for r in RL)} briefs per rep), no verdict"); continue
    base = ",".join(f"{kept[0]}{r}" for r in RL); new = ",".join(f"{pre}{r}" for r in RL)
    txt = run("scripts/stability.py", "--base", base, "--new", new)
    verdict = "ACCEPT" if re.search(r"^ACCEPT", txt, re.M) else "REJECT"
    say(f"### {pre} vs {kept[0]}: **{verdict}**"); say("```"); say(txt); say("```")
    say("Clusters that grew (rep 1):"); say("```"); say(grew(f"{kept[0]}{RL[0]}", f"{pre}{RL[0]}")); say("```")
    decisions.append((pre, verdict))
    if verdict == "ACCEPT":
        kept = [pre, setdir]

say(); say("## 4. Kept flags"); say()
if kept is None:
    say("none (no complete baseline)")
else:
    rep = REPO / "out/template_cc" / kept[1] / "brief-a/build_report.json"
    feats = json.loads(rep.read_text()).get("features") if kept[1] != "-" and rep.exists() else None
    say(f"Last accepted step: **{kept[0]}** (set {kept[1]})")
    say(f"Flags: `{','.join(feats)}`" if feats else "Flags: (no build report for this set)")
    say(); say("Decisions: " + (", ".join(f"{p}={v}" for p, v in decisions) or "none"))
(REPO / "results/ablation").mkdir(parents=True, exist_ok=True)
(REPO / "results/ablation/NIGHT_SUMMARY.md").write_text("\n".join(out) + "\n")
PY
