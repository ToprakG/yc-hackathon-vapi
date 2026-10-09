"""Score the same V1 on the blind set several times; the stdev is our minimum meaningful difference.

python -m agentforge.experiments.noise [--repeats 3] [--runs 3] [--platform vapi]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys

from agentforge.config import DOMAIN_DIR, RESULTS_DIR, RUNS_DIR
from agentforge.platform import get_platform
from agentforge.run.runner import metrics, report, run_suite
from agentforge.schemas import AgentConfig, Assertion, Persona
from agentforge.store import load_model, load_models, save_json

NOISE_PATH = RESULTS_DIR / "noise.json"
BLIND_DIR = DOMAIN_DIR / "kasko"


def load_noise() -> dict | None:
    if not NOISE_PATH.exists():
        return None
    return json.loads(NOISE_PATH.read_text())


def load_blind() -> tuple[list[Persona], list[Assertion]]:
    personas_path = BLIND_DIR / "blind_personas.json"
    assertions_path = BLIND_DIR / "blind_assertions.json"
    missing = [str(p) for p in (personas_path, assertions_path) if not p.exists()]
    if missing:
        sys.exit(f"blind set missing: {', '.join(missing)} (written in S4)")
    return load_models(personas_path, Persona), load_models(assertions_path, Assertion)


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--platform", default="vapi")
    args = parser.parse_args(argv)

    agent_path = RUNS_DIR / "v1" / "agent.json"
    if not agent_path.exists():
        sys.exit(f"{agent_path} missing; run the builder first (S3)")
    cfg = load_model(agent_path, AgentConfig)
    personas, assertions = load_blind()
    platform = get_platform(args.platform)

    pass_rates, hats = [], []
    for i in range(args.repeats):
        scored = run_suite(platform, cfg, personas, assertions, runs_per_persona=args.runs, set_name=f"blind_noise_{i}")
        report(scored, f"noise repeat {i}")
        m = metrics(scored)
        pass_rates.append(m["pass_rate"])
        hats.append(m["pass_hat_3"])

    result = {
        "mean": statistics.mean(pass_rates),
        "stdev": statistics.stdev(pass_rates) if len(pass_rates) > 1 else 0.0,
        "pass_rates": pass_rates,
        "pass_hat_3s": hats,
        "runs_per_persona": args.runs,
        "repeats": args.repeats,
    }
    save_json(NOISE_PATH, result)
    print(f"V1 blind pass_rate = {result['mean']:.3f} ± {result['stdev']:.3f} -> {NOISE_PATH}")
    return result


if __name__ == "__main__":
    main()
