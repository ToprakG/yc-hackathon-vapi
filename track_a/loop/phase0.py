"""Phase 0: canned V1, failure report, and V2 through the gate. No network."""

from __future__ import annotations

from pathlib import Path

from loop.gate import evaluate_gate
from loop.paths import shared
from loop.schema import (
    dump_json,
    load_json,
    validate_agent,
    validate_failure_report,
    validate_gate_decision,
    validate_run,
    validate_test_results,
    validate_unit_test,
)


def run_fixture(directory: Path) -> dict:
    parent = validate_agent(load_json(directory / "parent_agent.json"))
    candidate = validate_agent(load_json(directory / "candidate_agent.json"))
    report = validate_failure_report(load_json(directory / "failure_report.json"))
    validate_unit_test(load_json(directory / "unit_test.json"))
    parent_tests = validate_test_results(load_json(directory / "parent_tests.json"))
    candidate_tests = validate_test_results(load_json(directory / "candidate_tests.json"))
    parent_runs = [validate_run(run) for run in load_json(directory / "parent_runs.json")["runs"]]
    candidate_runs = [validate_run(run) for run in load_json(directory / "candidate_runs.json")["runs"]]
    decision = evaluate_gate(
        task_id=report["task_id"],
        parent_version=parent["id"],
        candidate_version=candidate["id"],
        failure_report=report,
        parent_tests=parent_tests,
        candidate_tests=candidate_tests,
        parent_runs=parent_runs,
        candidate_runs=candidate_runs,
    )
    return validate_gate_decision(decision)


def run_phase0(root: Path) -> int:
    base = root / "track_a" / "fixtures" / "phase0"
    commit = run_fixture(base / "commit")
    discard = run_fixture(base / "discard")
    output = shared(root) / "runs" / "phase0"
    dump_json(output / "commit.json", commit)
    dump_json(output / "discard.json", discard)
    print(f"phase0 commit fixture: {commit['decision'].upper()}")
    print(f"  {commit['reason']}")
    print(f"phase0 discard fixture: {discard['decision'].upper()}")
    print(f"  {discard['reason']}")
    if commit["decision"] != "commit" or discard["decision"] != "discard":
        print("phase0 failed: the canned fixtures did not take the expected branch")
        return 1
    return 0
