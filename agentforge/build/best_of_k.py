"""Best-of-K. A scorer stays off until its gate file exists. This module never writes those files."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from agentforge.schemas import AgentConfig

Score = Callable[[AgentConfig], float]


class ScoringBlocked(RuntimeError):
    """The gate file is missing or below the bar, so that scorer does not run."""


def simulation_allowed(results_dir: Path) -> None:
    fidelity_path = results_dir / "sim_fidelity.json"
    if not fidelity_path.is_file():
        raise ScoringBlocked("simulation scoring is off: results/sim_fidelity.json is missing")
    judge_path = results_dir / "judge_agreement.json"
    if not judge_path.is_file():
        raise ScoringBlocked("simulation scoring is off: results/judge_agreement.json is missing")
    fidelity = json.loads(fidelity_path.read_text(encoding="utf-8"))
    if int(fidelity.get("configs", 0)) < 8:
        raise ScoringBlocked("simulation scoring is off: fewer than 8 configs in sim_fidelity.json")
    if float(fidelity.get("pair_agreement", 0)) < 0.8:
        raise ScoringBlocked("simulation scoring is off: pairwise fidelity is below 0.8")
    if "mean_absolute_gap" not in fidelity:
        raise ScoringBlocked("simulation scoring is off: mean absolute pass-rate gap is not recorded")
    judge = json.loads(judge_path.read_text(encoding="utf-8"))
    for key in ("overall", "third_party", "verification", "promise"):
        if float(judge.get(key, 0)) < 0.85:
            raise ScoringBlocked(f"simulation scoring is off: judge agreement {key} is below 0.85")


def unit_scoring_allowed(results_dir: Path) -> None:
    path = results_dir / "ranking_agreement.json"
    if not path.is_file():
        raise ScoringBlocked("unit-test scoring is off: results/ranking_agreement.json is missing")
    data = json.loads(path.read_text(encoding="utf-8"))
    if float(data.get("pair_agreement", 0)) < 0.8:
        raise ScoringBlocked("unit-test scoring is off: pairwise ranking agreement is below 0.8")


def best_of_k(
    candidates: list[AgentConfig],
    score: Score,
    *,
    kind: str,
    results_dir: Path,
) -> AgentConfig:
    if not candidates:
        raise ValueError("best-of-K needs at least one candidate")
    if kind == "simulation":
        simulation_allowed(results_dir)
    elif kind == "unit":
        unit_scoring_allowed(results_dir)
    else:
        raise ValueError(f"unknown scorer: {kind}")
    ranked = [(score(candidate), candidate) for candidate in candidates]
    return max(ranked, key=lambda item: item[0])[1]
