"""Check one final_run.sh --offline call with exactly brief-a + brief-b (the final's shape).   python3 scripts/dress_check.py <out dir> [flags file]
  1. the flags the build used == the flags of FINAL_FLAGS.txt (default M1_FLAGS.txt); f18_opening_fallback off, f28_tool_failure on when named
  2. no opening_resume node; promise_try / promise_error present (f28)
  3. brief-b resolved its reference to brief-a inside the call (found_in call, path = the call's brief-a file); no DEGENERATE line anywhere
  4. lint 0 errors
Prints OK / PROBLEM per line and a final verdict. Reads only the build outputs."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, ".")
from builder.template_cc import features as F  # noqa: E402

out = Path(sys.argv[1])
flags_file = Path(sys.argv[2]) if len(sys.argv) > 2 else (Path("FINAL_FLAGS.txt") if Path("FINAL_FLAGS.txt").exists() else Path("M1_FLAGS.txt"))
want = F.parse(flags_file.read_text().replace("\n", "").strip())
problems = []


def line(ok, msg):
    print(("OK      " if ok else "PROBLEM ") + msg)
    if not ok:
        problems.append(msg)


def build_dir(b):
    d = out / b
    for sub in ("r0b", "r0"):
        if (d / sub / "build_report.json").exists() and (d / sub / "workflow.json").exists():
            return d / sub
    return d


print(f"flags file: {flags_file}  ({len(want)} flags; f18_opening_fallback {'ON' if 'f18_opening_fallback' in want else 'off'}, f28_tool_failure {'ON' if 'f28_tool_failure' in want else 'off'})")
for b in ("brief-a", "brief-b"):
    d = build_dir(b)
    try:
        rep = json.load(open(d / "build_report.json"))
        wf = json.load(open(d / "workflow.json"))
    except OSError as e:
        line(False, f"{b}: no build output ({e})")
        continue
    wf = wf.get("workflow", wf)
    got = frozenset(rep.get("features") or [])
    line(got == want, f"{b}: flags used == flags file ({len(got)} vs {len(want)})" + ("" if got == want else f"; extra {sorted(got - want)}, missing {sorted(want - got)}"))
    nodes = set(wf["nodes"])
    line("opening_resume" not in nodes if "f18_opening_fallback" not in want else "opening_resume" in nodes, f"{b}: opening_resume node {'absent' if 'opening_resume' not in nodes else 'present'}")
    if "f28_tool_failure" in want:
        line({"promise_try", "promise_error"} <= nodes, f"{b}: promise_try / promise_error nodes present")
    lint = (rep.get("lint") or {}).get("errors")
    line(lint == 0, f"{b}: lint errors {lint}")
    line(rep.get("status") == "ok", f"{b}: build status {rep.get('status')}")
    logs = " ".join(p.read_text(errors="ignore") for p in list(out.glob(f"{b}/**/*.log")) + list(out.glob(f"{b}/**/trace.txt")) + list(out.glob(f"{b}/*.out"))[:3])
    line("DEGENERATE" not in logs, f"{b}: no DEGENERATE line")
res = None
for p in (out / "brief-b").rglob("brief_resolution.json"):
    res = json.load(open(p))
    break
if res is None:
    line(False, "brief-b: no brief_resolution.json")
else:
    entries = [e for e in res.get("log", []) if e.get("ref") == "A"]
    ok = bool(entries) and all(e.get("status") == "resolved" and e.get("found_in") == "call" and "brief-a" in e.get("path", "") for e in entries)
    line(ok, f"brief-b: reference 'Brief A' resolved {[(e.get('status'), e.get('found_in'), e.get('path')) for e in entries]}")
print("\nVERDICT:", "ALL OK" if not problems else f"{len(problems)} PROBLEM(S)")
sys.exit(0 if not problems else 1)
