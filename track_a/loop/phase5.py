"""Phase 5: replay the personas on V2, score the tests, commit or discard."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loop.gate import evaluate_gate
from loop.paths import shared
from loop.phase2 import run_path, scenarios_path
from loop.phase3 import generalized_report, load_runs, report_path
from loop.phase4 import tests_path
from loop.schema import dump_json, load_json, validate_agent, validate_failure_report, validate_gate_decision, validate_run, validate_unit_test
from loop.scoring import playback_scenarios, score_tests
from loop.store import load_binding, load_development_tasks, save_binding
from loop.vapi_runtime import VapiRuntime


def run_phase5(
    root: Path,
    *,
    runtime: VapiRuntime | None = None,
    task_filter: str | None = None,
) -> int:
    tasks = [task for task in load_development_tasks(root) if not task_filter or task["id"] == task_filter]
    decided = False
    for task in tasks:
        report_file = report_path(root, task["id"], "v1")
        if not report_file.exists():
            print(f"missing failure report for {task['id']}. Run phase3 first.")
            return 1
        stored_report = load_json(report_file)
        report = generalized_report(
            validate_failure_report(
                {key: stored_report[key] for key in ("id", "task_id", "agent_version", "bugs")}
            )
        )
        parent = validate_agent(load_json(shared(root) / "versions" / task["id"] / "v1" / "agent_config.json"), task)
        if not report["bugs"]:
            print(f"{parent['id']} stays BEST. The analyzer found no generalized bug.")
            continue
        candidate_path = shared(root) / "versions" / task["id"] / "v2" / "agent_config.json"
        if not candidate_path.exists():
            print(f"missing V2 for {task['id']}. Run phase4 first.")
            return 1
        candidate = validate_agent(load_json(candidate_path), task)
        tests = [
            validate_unit_test(test)
            for test in load_json(tests_path(root, task["id"]))["tests"]
        ]
        parent_runs = load_runs(root, task["id"], parent["id"])
        if len(parent_runs) < 3:
            print(f"{parent['id']} has no V1 transcripts. Run phase2 --simulate first.")
            return 1
        if runtime is None:
            runtime = VapiRuntime.from_env()
        parent_binding = _published(root, runtime, parent)
        candidate_binding = _published(root, runtime, candidate)
        scenarios = load_json(scenarios_path(root, task["id"], "v1"))["scenarios"]
        candidate_runs = _scenario_runs(root, runtime, candidate, scenarios, candidate_binding["assistant_id"], task)
        parent_test_runs = _play_tests(root, runtime, parent, task, tests, parent_binding["assistant_id"])
        candidate_test_runs = _play_tests(root, runtime, candidate, task, tests, candidate_binding["assistant_id"])
        decision = evaluate_gate(
            task_id=task["id"],
            parent_version=parent["id"],
            candidate_version=candidate["id"],
            failure_report=report,
            parent_tests=score_tests(tests, parent_test_runs),
            candidate_tests=score_tests(tests, candidate_test_runs),
            parent_runs=parent_runs,
            candidate_runs=candidate_runs,
        )
        decision = validate_gate_decision(decision)
        decision_path = shared(root) / "versions" / task["id"] / "v2" / "gate_decision.json"
        dump_json(decision_path, decision)
        if decision["decision"] == "commit":
            best = shared(root) / "versions" / task["id"] / "BEST"
            best.write_text("v2\n")
        print(f"{decision['decision'].upper()} {candidate['id']}: {decision['reason']}")
        decided = True
    if not decided:
        print("no patch reached the gate. BEST stays the V1 for every task.")
    return 0


def _published(root: Path, runtime: VapiRuntime, config: dict[str, Any]) -> dict[str, Any]:
    binding = load_binding(root, config)
    existing_id = binding.get("assistant_id") if binding else None
    binding = runtime.publish(config, existing_id=existing_id)
    save_binding(root, config, binding)
    print(f"published {config['id']} -> {binding['assistant_id']}")
    return binding


def _scenario_runs(
    root: Path,
    runtime: VapiRuntime,
    config: dict[str, Any],
    scenarios: list[dict[str, Any]],
    assistant_id: str,
    task: dict[str, Any],
) -> list[dict[str, Any]]:
    directory = shared(root) / "runs" / task["id"] / config["id"]
    paths = [directory / f"{scenario['id']}.json" for scenario in scenarios]
    if paths and all(path.exists() for path in paths):
        print(f"using {len(paths)} stored transcripts for {config['id']}")
        return [validate_run(load_json(path)) for path in paths]
    return _store_runs(
        root,
        runtime.simulate(config, scenarios, assistant_id, task, attempts=150, interval=5),
    )


def _play_tests(
    root: Path,
    runtime: VapiRuntime,
    config: dict[str, Any],
    task: dict[str, Any],
    tests: list[dict[str, Any]],
    assistant_id: str,
) -> list[dict[str, Any]]:
    if not tests:
        return []
    return _store_runs(
        root,
        runtime.simulate(
            config,
            playback_scenarios(task, tests),
            assistant_id,
            task,
            attempts=150,
            interval=5,
            verbatim=True,
        ),
    )


def _store_runs(root: Path, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stored = []
    for run in runs:
        saved = validate_run(run)
        path = run_path(root, saved)
        dump_json(path, saved)
        print(f"stored transcript {saved['scenario_id']} -> {path}")
        stored.append(saved)
    return stored
