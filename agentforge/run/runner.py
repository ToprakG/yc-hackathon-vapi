"""Run personas against an agent, score every run, and summarize."""

from __future__ import annotations

import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from math import comb

from rich.console import Console
from rich.table import Table

from agentforge.config import RUNS_DIR
from agentforge.platform.base import Platform
from agentforge.run.scorer import score_run
from agentforge.schemas import AgentConfig, Assertion, Persona, RunResult, ScoredRun
from agentforge.store import save_jsonl


def _one(platform: Platform, cfg: AgentConfig, persona: Persona, run_idx: int, assertions: list[Assertion]) -> ScoredRun:
    try:
        run = platform.run_conversation(cfg, persona, run_idx)
    except Exception as error:
        run = RunResult(
            persona_name=persona.name,
            agent_version=cfg.version_label,
            run_idx=run_idx,
            ended_reason=f"error: {type(error).__name__}: {error}",
        )
    return score_run(run, persona, assertions)


def run_suite(
    platform: Platform,
    cfg: AgentConfig,
    personas: list[Persona],
    assertions: list[Assertion],
    runs_per_persona: int = 3,
    concurrency: int | None = None,
    set_name: str = "train",
) -> list[ScoredRun]:
    jobs = [(persona, idx) for persona in personas for idx in range(runs_per_persona)]
    concurrency = concurrency or int(os.environ.get("SIM_CONCURRENCY", "12"))
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [pool.submit(_one, platform, cfg, persona, idx, assertions) for persona, idx in jobs]
        scored = [future.result() for future in futures]
    save_jsonl(RUNS_DIR / cfg.version_label / f"{set_name}.jsonl", scored)
    check_judge_health(scored)
    return scored


def check_judge_health(scored: list[ScoredRun], max_error_share: float = 0.2) -> None:
    """A broken platform (no credits, auth) or judge (bad key, bad params) turns every run into a failure.
    Stop instead of reporting 0% and letting the gate compare two broken suites."""
    crashed = [s for s in scored if s.run.ended_reason.startswith("error")]
    if scored and len(crashed) / len(scored) > max_error_share:
        raise RuntimeError(f"{len(crashed)}/{len(scored)} conversations errored, e.g. {crashed[0].run.ended_reason[:200]}")
    verdicts = [v for s in scored for v in s.verdicts]
    errors = [v for v in verdicts if v.reason.startswith("ERROR: judge failed")]
    if verdicts and len(errors) / len(verdicts) > max_error_share:
        raise RuntimeError(f"{len(errors)}/{len(verdicts)} judge calls failed, e.g. {errors[0].reason}")


def metrics(scored: list[ScoredRun]) -> dict:
    per_persona: dict[str, dict[str, int]] = {}
    for item in scored:
        entry = per_persona.setdefault(item.run.persona_name, {"passed": 0, "runs": 0})
        entry["runs"] += 1
        entry["passed"] += int(item.passed)
    hats = []
    for entry in per_persona.values():
        n, c = entry["runs"], entry["passed"]
        k = min(3, n)
        hats.append(comb(c, k) / comb(n, k))
    fails = Counter(v.check_name for item in scored for v in item.verdicts if not v.passed)
    return {
        "pass_rate": sum(item.passed for item in scored) / len(scored) if scored else 0.0,
        "pass_hat_3": sum(hats) / len(hats) if hats else 0.0,
        "per_persona": per_persona,
        "per_assertion_fail_counts": dict(fails),
        "total_cost": sum(item.run.cost_usd or 0.0 for item in scored),
        "total_minutes": sum(item.run.duration_s for item in scored) / 60,
    }


def report(scored: list[ScoredRun], title: str) -> dict:
    m = metrics(scored)
    console = Console()
    table = Table(title=title)
    table.add_column("persona")
    table.add_column("passed", justify="right")
    for name, entry in m["per_persona"].items():
        table.add_row(name, f"{entry['passed']}/{entry['runs']}")
    console.print(table)
    if m["per_assertion_fail_counts"]:
        fails = Table(title="failed checks")
        fails.add_column("check")
        fails.add_column("fails", justify="right")
        for name, count in sorted(m["per_assertion_fail_counts"].items(), key=lambda kv: -kv[1]):
            fails.add_row(name, str(count))
        console.print(fails)
    console.print(
        f"pass_rate={m['pass_rate']:.2f}  pass^3={m['pass_hat_3']:.2f}  "
        f"cost=${m['total_cost']:.2f}  minutes={m['total_minutes']:.1f}"
    )
    return m
