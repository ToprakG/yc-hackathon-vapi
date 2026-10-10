"""Build the shippable collections variants and write them. Score only when a gate file allows it.

This command does not call Freya, and it does not write ranking, judge, or fidelity files.
"Template equal to one-call" is stored as a template win. It is not a live builder call.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agentforge.build.best_of_k import ScoringBlocked, simulation_allowed, unit_scoring_allowed
from agentforge.build.extract import extract
from agentforge.build.self_check import self_check
from agentforge.build.variants import shippable
from agentforge.config import RESULTS_DIR
from agentforge.domain import load_domain
from agentforge.store import save_json

# Stored, not measured. The one-call builder is a separate call the runner does not make here.
TEMPLATE_VERSUS_ONE_CALL = "template"


def build_brief(domain: str, *, repair: bool = True, model: str | None = None) -> dict:
    task_md, tools = load_domain(domain)
    policy = extract(task_md, tools)
    variants = shippable(policy, tools, model=model)
    checked = {}
    gap_report = {}
    for name, config in variants.items():
        repaired, gaps = self_check(policy, config, repair=repair)
        checked[name] = repaired
        if gaps:
            gap_report[name] = gaps
    return {
        "brief": domain,
        "template_versus_one_call": TEMPLATE_VERSUS_ONE_CALL,
        "gaps": list(policy.gaps),
        "self_check": gap_report,
        "variants": checked,
    }


def write_brief(domain: str, *, repair: bool = True, model: str | None = None) -> Path:
    payload = build_brief(domain, repair=repair, model=model)
    out = RESULTS_DIR / "levers" / f"{Path(domain).name}.json"
    save_json(out, _serializable(payload))
    return out


def _serializable(payload: dict) -> dict:
    variants = payload["variants"]
    dumped = {
        name: config.model_dump(mode="json") if hasattr(config, "model_dump") else config
        for name, config in variants.items()
    }
    return {**payload, "variants": dumped}


def score_when_allowed(payload: dict, *, kind: str, results_dir: Path, score) -> str:
    from agentforge.build.best_of_k import best_of_k

    winner = best_of_k(list(payload["variants"].values()), score, kind=kind, results_dir=results_dir)
    return winner.version_label


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write collections lever AgentConfigs.")
    parser.add_argument("brief", help="Domain path, for example collections/strict")
    parser.add_argument("--platform", default="local", choices=["local", "freya"])
    parser.add_argument("--score", choices=["unit", "simulation"], default=None)
    parser.add_argument("--no-repair", action="store_true")
    args = parser.parse_args(argv)
    payload = build_brief(args.brief, repair=not args.no_repair)
    path = RESULTS_DIR / "levers" / f"{Path(args.brief).name}.json"
    save_json(path, _serializable(payload))
    print(path)
    if args.score is None:
        return 0
    try:
        if args.score == "simulation":
            simulation_allowed(RESULTS_DIR)
        else:
            unit_scoring_allowed(RESULTS_DIR)
    except ScoringBlocked as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        f"The {args.score} gate is open for --platform {args.platform}. This build does not call the platform.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
