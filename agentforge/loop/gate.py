"""REGRESSION GATE: candidate vs best on held-out personas plus the unit-test suite."""

from __future__ import annotations

import importlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from rich.console import Console

from agentforge.platform.base import Platform
from agentforge.schemas import AgentConfig, Assertion, Persona, ScoredRun, UnitTest, Verdict


@dataclass
class GateDecision:
    commit: bool
    reasons: list[str]
    candidate_metrics: dict
    best_metrics: dict
    candidate_scored: list[ScoredRun] = field(default_factory=list)
    best_scored: list[ScoredRun] = field(default_factory=list)


def unit_test_rate(platform: Platform, cfg: AgentConfig, tests: list[UnitTest]) -> float:
    if not tests:
        return 1.0
    def run_one(test: UnitTest) -> Verdict:
        try:
            return platform.run_unit_test(cfg, test)
        except Exception as error:  # one flaky platform call must not abort the whole gate
            return Verdict(check_name=test.name, passed=False, reason=f"ERROR: {error}")

    with ThreadPoolExecutor(max_workers=min(len(tests), 4)) as pool:
        verdicts = list(pool.map(run_one, tests))
    return sum(verdict.passed for verdict in verdicts) / len(tests)


def gate(
    platform: Platform,
    candidate: AgentConfig,
    best: AgentConfig,
    heldout: list[Persona],
    assertions: list[Assertion],
    unit_tests: list[UnitTest],
    runs_per_persona: int = 3,
    best_scored: list[ScoredRun] | None = None,
) -> GateDecision:
    bad = [persona.name for persona in heldout if persona.split != "heldout"]
    if bad:
        raise ValueError(f"gate only scores heldout personas; got {bad}")
    runner = importlib.import_module("agentforge.run.runner")

    if best_scored is None:
        best_scored = runner.run_suite(platform, best, heldout, assertions, runs_per_persona=runs_per_persona, set_name="heldout")
    candidate_scored = runner.run_suite(
        platform, candidate, heldout, assertions, runs_per_persona=runs_per_persona, set_name="heldout"
    )
    best_metrics = dict(runner.metrics(best_scored))
    candidate_metrics = dict(runner.metrics(candidate_scored))
    best_metrics["unit_test_pass_rate"] = unit_test_rate(platform, best, unit_tests)
    candidate_metrics["unit_test_pass_rate"] = unit_test_rate(platform, candidate, unit_tests)

    reasons: list[str] = []
    commit = True
    cand_rate, best_rate = candidate_metrics["pass_rate"], best_metrics["pass_rate"]
    if cand_rate >= best_rate:
        reasons.append(f"heldout pass_rate {cand_rate:.2f} >= best {best_rate:.2f}")
    else:
        commit = False
        reasons.append(f"heldout pass_rate {cand_rate:.2f} < best {best_rate:.2f}")

    for name, stats in best_metrics["per_persona"].items():
        if not stats["runs"] or stats["passed"] < stats["runs"]:
            continue
        cand = candidate_metrics["per_persona"].get(name, {"passed": 0, "runs": 0})
        if cand["runs"] and cand["passed"] * 3 <= cand["runs"]:
            commit = False
            reasons.append(f"persona {name} regressed: best {stats['passed']}/{stats['runs']} -> {cand['passed']}/{cand['runs']}")

    cand_ut, best_ut = candidate_metrics["unit_test_pass_rate"], best_metrics["unit_test_pass_rate"]
    if cand_ut < best_ut:
        commit = False
        reasons.append(f"unit tests dropped {best_ut:.2f} -> {cand_ut:.2f}")
    else:
        reasons.append(f"unit tests {cand_ut:.2f} (best {best_ut:.2f}, {len(unit_tests)} tests)")

    decision = GateDecision(commit, reasons, candidate_metrics, best_metrics, candidate_scored, best_scored)
    console = Console()
    color = "green" if commit else "red"
    console.print(f"[bold {color}]{'COMMIT' if commit else 'DISCARD'}[/] {candidate.version_label} vs {best.version_label}")
    for reason in reasons:
        console.print(f"  - {reason}")
    return decision
