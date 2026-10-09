"""The closed loop: build V1, attack it, analyze, patch, gate, keep the best."""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from agentforge.analyze import analyzer
from agentforge.build import builder
from agentforge.config import RUNS_DIR
from agentforge.domain import load_domain, persona_context
from agentforge.loop import gate as gate_mod
from agentforge.patch import patcher
from agentforge.platform import Platform, get_platform
from agentforge.run import runner
from agentforge.schemas import AgentConfig, Persona, UnitTest
from agentforge.store import append_jsonl, save_json
from agentforge.testgen import adversary, assertions as assertions_mod, coverage, split, unit_tests

console = Console()
LOOP_LOG = RUNS_DIR / "loop_log.jsonl"


def with_split(personas: list[Persona], name: str) -> list[Persona]:
    return [persona for persona in personas if name in persona.tags]


def run_pipeline(
    domain_dir: str | Path,
    platform: Platform,
    mode: str = "loop",
    max_iters: int = 3,
    patch_mode: str = "surgical",
    runs_per_persona: int = 3,
    run_tag: str = "",
    v1: AgentConfig | None = None,
) -> AgentConfig:
    """Return the best committed AgentConfig. mode="builder" stops after V1.

    Pass v1 to start every variant of an experiment from the same built agent.
    run_tag prefixes version labels so variants don't overwrite each other under runs/.
    """
    task_md, tools = load_domain(domain_dir)
    started = time.monotonic()
    best = v1 or builder.build_agent(task_md, tools)
    if run_tag:
        best = best.model_copy(update={"version_label": f"{run_tag}-v1"})
    save_json(RUNS_DIR / best.version_label / "agent.json", best)
    if mode == "builder":
        return best

    asserts = assertions_mod.generate_assertions(task_md)
    context = persona_context(domain_dir, task_md)
    cover = coverage.generate_coverage(context, tools)
    personas = split.split_personas(cover + adversary.generate_adversary(context, tools, best))
    tests: list[UnitTest] = []
    best_heldout = None

    for iteration in range(1, max_iters + 1):
        iter_started = time.monotonic()
        train, heldout = with_split(personas, "train"), with_split(personas, "heldout")
        save_json(RUNS_DIR / best.version_label / "personas.json", personas)
        save_json(RUNS_DIR / best.version_label / "assertions.json", asserts)

        train_scored = runner.run_suite(platform, best, train, asserts, runs_per_persona=runs_per_persona, set_name="train")
        train_metrics = runner.metrics(train_scored)
        failed = [scored for scored in train_scored if not scored.passed]
        if not failed:
            console.print(f"[green]iter {iteration}: no train failures on {best.version_label}; stopping.")
            log_iteration(iteration, best, None, train_metrics, None, "STOP", ["no train failures"], iter_started, train_scored)
            break

        report = analyzer.analyze(best.version_label, failed, personas)
        save_json(RUNS_DIR / best.version_label / "failure_report.json", report)
        if not report.agent_bugs():
            console.print(f"[yellow]iter {iteration}: analyzer found no agent bugs; stopping.")
            log_iteration(iteration, best, None, train_metrics, None, "STOP", ["no agent bugs"], iter_started, train_scored)
            break

        tests = unit_tests.generate_unit_tests(report, failed, tests)
        unit_tests.save_unit_tests(best.version_label, tests)

        candidate, patches = patcher.patch_agent(best, report, mode=patch_mode)
        save_json(RUNS_DIR / candidate.version_label / "agent.json", candidate)
        save_json(RUNS_DIR / candidate.version_label / "patches.json", patches)

        decision = gate_mod.gate(
            platform, candidate, best, heldout, asserts, tests,
            runs_per_persona=runs_per_persona, best_scored=best_heldout,
        )
        verdict = "COMMIT" if decision.commit else "DISCARD"
        log_iteration(iteration, best, candidate, train_metrics, decision, verdict, decision.reasons, iter_started, train_scored)
        if decision.commit:
            best, best_heldout = candidate, decision.candidate_scored
            # Adversary personas target the old prompt; regenerate them against the new best.
            fresh = adversary.generate_adversary(context, tools, best)
            personas = split.split_personas(cover + fresh)
            best_heldout = None  # heldout set changed, so the cached best score no longer applies
        else:
            best_heldout = decision.best_scored

    save_json(RUNS_DIR / "best" / f"{run_tag or patch_mode}.json", best)
    console.print(f"[bold]best = {best.version_label}  ({(time.monotonic() - started) / 60:.1f} min)")
    return best


def log_iteration(iteration, best, candidate, train_metrics, decision, verdict, reasons, iter_started, train_scored) -> None:
    gate_minutes = gate_cost = 0.0
    if decision is not None:
        for metrics in (decision.candidate_metrics, decision.best_metrics):
            gate_minutes += metrics.get("total_minutes") or 0
            gate_cost += metrics.get("total_cost") or 0
    append_jsonl(
        LOOP_LOG,
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "iteration": iteration,
            "best_version": best.version_label,
            "candidate_version": candidate.version_label if candidate else None,
            "train_pass_rate": train_metrics["pass_rate"],
            "heldout_best_pass_rate": decision.best_metrics.get("pass_rate") if decision else None,
            "heldout_candidate_pass_rate": decision.candidate_metrics.get("pass_rate") if decision else None,
            "decision": verdict,
            "reasons": reasons,
            "prompt_chars": len((candidate or best).system_prompt),
            "wall_minutes": round((time.monotonic() - iter_started) / 60, 2),
            "sim_minutes": round((train_metrics.get("total_minutes") or 0) + gate_minutes, 2),
            "cost_usd": round((train_metrics.get("total_cost") or 0) + gate_cost, 4),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the closed loop on a domain.")
    parser.add_argument("domain", nargs="?", default="kasko")
    parser.add_argument("--platform", default="vapi")
    parser.add_argument("--mode", choices=["loop", "builder"], default="loop")
    parser.add_argument("--max-iters", type=int, default=3)
    parser.add_argument("--patch-mode", choices=["surgical", "free"], default="surgical")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    run_pipeline(args.domain, get_platform(args.platform), args.mode, args.max_iters, args.patch_mode, args.runs)


if __name__ == "__main__":
    main()
