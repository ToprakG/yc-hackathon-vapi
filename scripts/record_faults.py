"""Record the self-test of faulty builds ONCE: scenarios (relevant rule types + 2 others, <= 5 per build) -> one Freya simulation per build
(single lane, lock wait in selftest_run.sh) -> out/template_cc/faults/recordings/<brief>/<fault>/{cases.json,results.json,transcripts/,
fault.json,policy.json}. The patcher is then iterated OFFLINE on these (patcher_eval.py).

    .venv310/bin/python scripts/record_faults.py [--faults f5-halden-email/deadline_shift,...] [--reuse]
"""
import argparse, json, os, shutil, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
F = REPO / "out" / "template_cc" / "faults"
USE = {"f5-halden-email": ["right_party_real", "deadline_shift", "wrong_queue", "wrong_outcome", "ask_limit", "corrupt_line", "unknown_rule_removed"],
       "brief-a": ["deadline_shift", "max_wrong", "callback_window", "corrupt_line", "unknown_rule_removed", "multi_flip"]}


def paths(brief):
    if brief.startswith("brief-"):
        return [f"briefs/{brief}.md"], "tools/openapi.json"
    return [f"testbed/fake_briefs/{brief}/brief.md"], f"testbed/fake_briefs/{brief}/tools.openapi.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--faults", default="")
    ap.add_argument("--reuse", action="store_true", help="skip faults that already have a recording")
    a = ap.parse_args()
    todo = [f"{b}/{x}" for b, xs in USE.items() for x in xs]
    if a.faults:
        todo = a.faults.split(",")
    for fid in todo:
        brief = fid.split("/")[0]
        d, rec = F / fid, F / "recordings" / fid
        if a.reuse and (rec / "results.json").exists():
            continue
        fault = json.loads((d / "fault.json").read_text())
        if not fault.get("built"):
            print(fid, "not built, skipped"); continue
        bf, api = paths(brief)
        cmd = [".venv310/bin/python", "scripts/selftest_cases.py", *bf, str(d / "policy.json"), "--out", str(d / "selftest" / "all_cases.json"), "--max", "12"]
        if fault.get("extra_rules"):
            er = d / "extra_rules.json"; er.write_text(json.dumps(fault["extra_rules"])); cmd += ["--extra-rules", str(er)]
        subprocess.run(cmd, cwd=REPO, check=True, capture_output=True)
        cases = json.loads((d / "selftest" / "all_cases.json").read_text())
        rel = [c for c in cases if c["rule"] in fault["rules"]]
        oth = [c for c in cases if c["rule"] not in fault["rules"] and c["rule"] != "unknown_rule"][:2]
        sub = (rel + oth)[:5]
        (d / "selftest" / "cases.json").write_text(json.dumps(sub, indent=1, ensure_ascii=False))
        print(f"{fid}: {len(sub)} scenarios ({','.join(c['rule'] for c in sub)})", flush=True)
        r = subprocess.run(["bash", "scripts/selftest_run.sh", str(d), "--cases", str(d / "selftest" / "cases.json"), "--api", api],
                           cwd=REPO, capture_output=True, text=True, env={**os.environ, "LANE_WAIT": "7200"})
        print(r.stdout.strip().splitlines()[-6:] if r.stdout else r.stderr[-300:], flush=True)
        if (d / "selftest" / "results.json").exists():
            rec.mkdir(parents=True, exist_ok=True)
            shutil.copytree(d / "selftest", rec / "selftest", dirs_exist_ok=True)
            for fn in ("fault.json", "policy.json", "zones.final.json", "workflow.json", "build_report.json"):
                if (d / fn).exists():
                    shutil.copy(d / fn, rec / fn)
            shutil.copy(d / "selftest" / "results.json", rec / "results.json")
            shutil.copy(d / "selftest" / "cases.json", rec / "cases.json")


main()
