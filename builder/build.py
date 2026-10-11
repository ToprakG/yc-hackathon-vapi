"""Our hackathon builder: brief material + a tool API file -> a Freya workflow phone agent.

    python3 builder/build.py <brief> [<more briefs> ...] <tools.openapi.json> [options]

The tool API is the one argument whose JSON has a top-level `openapi` key; every other argument is brief material in
override order (Brief B: `brief-a.md brief-b.md`). Variants register in VARIANTS; `tcc` (the template compiler + self-test + repair pipeline,
scripts/final_run.sh) is the default and the official run command; `agentic` is the earlier Claude Code builder.
Exit code 0 when a lint-clean workflow was produced (and saved, with --save freya).

The tcc variant needs: `python3 -m venv .venv310` with the packages of README_RUN.md, the Claude login (claude_cli), FREYA_API_KEY in the environment or .env,
cloudflared. A brief that builds on another ("Brief B builds on Brief A") is built together with it: the referenced brief is taken from the call or from briefs/.
Results: <out>/workflow.json (last-green), the Freya export workflows/<slot>.workflow.json (committed path), the trace under traces/.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from builder.common.io import InputError, slot_name, split_inputs  # noqa: E402


def run_agentic(args, briefs, api) -> dict:
    from builder.agentic.run import BuildOptions, run  # noqa: PLC0415

    return run(BuildOptions(briefs=briefs, api=api, slot=args.slot, out_dir=Path(args.out), save=args.save,
                            max_minutes=args.max_minutes, model=args.model, max_usd=args.max_usd,
                            review=args.review == "on", review_minutes=args.review_minutes, fix_minutes=args.fix_minutes,
                            unit=args.unit == "on", localsim=args.localsim == "on",
                            keep_workspace=args.keep_workspace, self_test=args.self_test))


def tcc_command(args, briefs, api) -> tuple[list[str], dict]:
    """The final_run.sh command line and environment for this build (pure; unit-tested)."""
    env = dict(os.environ)
    mode = (REPO / "FINAL_MODE.txt")
    env.setdefault("FINAL_MODE", mode.read_text().strip() if mode.exists() else "patcher_on")
    env.setdefault("FINAL_VOTES", "3")
    budget = int(args.max_minutes)
    cmd = ["bash", str(REPO / "scripts" / "final_run.sh"), "--budget-min", str(budget), "--ship-min", str(max(1, budget - 4))]
    if args.save == "none":
        cmd.append("--offline")
    cmd += [str(b) for b in briefs] + [str(api), str(args.out)]
    return cmd, env


def run_tcc(args, briefs, api) -> dict:
    cmd, env = tcc_command(args, briefs, api)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rc = subprocess.run(cmd, cwd=REPO, env=env).returncode
    report = {}
    try:
        report = json.loads((out / "build_report.json").read_text())
    except (OSError, ValueError):
        pass
    exports = sorted(out.glob("*.workflow.json"))
    saved = None
    if exports:   # the Freya export, copied to a committed path
        dest = REPO / "workflows"
        dest.mkdir(exist_ok=True)
        saved = dest / f"{args.slot}.workflow.json"
        shutil.copyfile(exports[-1], saved)
    ok = rc == 0 and (out / "workflow.json").exists() and (report.get("status") in (None, "ok"))
    return {"status": "ok" if ok else "failed", "slot": args.slot, "saved": str(saved) if saved else None, "fallback_used": None,
            "message": None if ok else f"final_run.sh exit {rc}; see {out}/final_run.log", "trace": report.get("trace"), "out": str(out)}


VARIANTS = {"tcc": run_tcc, "agentic": run_agentic}


def parse(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("inputs", nargs="+", help="brief files (any text format) and exactly one tool API file")
    p.add_argument("--variant", default="tcc", choices=sorted(VARIANTS))
    p.add_argument("--save", default="freya", choices=["freya", "none"], help="none: write files only, touch nothing on Freya")
    p.add_argument("--slot", help="Freya slot name; default <variant>-<last brief stem>")
    p.add_argument("--max-minutes", type=float, default=None, help="hard wall clock (tcc: 30, shipped at minute -4; agentic: 15)")
    p.add_argument("--unit", default="on", choices=["on", "off"], help="run the builder's own unit tests on Freya (a -unit copy)")
    p.add_argument("--localsim", default="on", choices=["on", "off"], help="hard local simulations from the builder's own policy; failures join the fix round")
    p.add_argument("--review", default="on", choices=["on", "off"], help="fresh-context review + one fix round")
    p.add_argument("--review-minutes", type=float, default=5.0)
    p.add_argument("--fix-minutes", type=float, default=6.0)
    p.add_argument("--model", default=os.environ.get("BUILDER_MODEL", "claude-opus-5-5"))
    p.add_argument("--max-usd", type=float, default=None, help="optional cost cap for the agent run")
    p.add_argument("--out", help="output directory; default out/<variant>/<slot>/")
    p.add_argument("--self-test", default="none", choices=["none"], help="later: local, freya")
    p.add_argument("--keep-workspace", action="store_true", help="keep the temp workspace for inspection")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse(argv)
    try:
        briefs, api = split_inputs(args.inputs)
    except InputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    args.max_minutes = args.max_minutes if args.max_minutes is not None else (30.0 if args.variant == "tcc" else 15.0)
    args.slot = args.slot or slot_name(briefs, args.variant)
    args.out = args.out or str(REPO / "out" / args.variant / args.slot)
    report = VARIANTS[args.variant](args, briefs, api)
    print(json.dumps({k: report.get(k) for k in ("status", "slot", "saved", "fallback_used", "message", "trace")}, default=str))
    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
