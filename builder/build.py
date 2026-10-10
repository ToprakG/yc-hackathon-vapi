"""Our hackathon builder: brief material + a tool API file -> a Freya workflow phone agent.

    python3 builder/build.py <brief> [<more briefs> ...] <tools.openapi.json> [options]

The tool API is the one argument whose JSON has a top-level `openapi` key; every other argument is brief material in
override order (Brief B: `brief-a.md brief-b.md`). Variants register in VARIANTS; `agentic` is the default.
Exit code 0 when a lint-clean workflow was produced (and saved, with --save freya).
"""

from __future__ import annotations

import argparse
import json
import os
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


VARIANTS = {"agentic": run_agentic}


def parse(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("inputs", nargs="+", help="brief files (any text format) and exactly one tool API file")
    p.add_argument("--variant", default="agentic", choices=sorted(VARIANTS))
    p.add_argument("--save", default="freya", choices=["freya", "none"], help="none: write files only, touch nothing on Freya")
    p.add_argument("--slot", help="Freya slot name; default <variant>-<last brief stem>")
    p.add_argument("--max-minutes", type=float, default=15.0, help="hard wall clock for the build agent")
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
    args.slot = args.slot or slot_name(briefs, args.variant)
    args.out = args.out or str(REPO / "out" / args.variant / args.slot)
    report = VARIANTS[args.variant](args, briefs, api)
    print(json.dumps({k: report.get(k) for k in ("status", "slot", "saved", "fallback_used", "message", "trace")}, default=str))
    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
