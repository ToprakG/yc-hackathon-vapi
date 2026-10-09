"""Regression gate. A patch commits only when every rule below holds."""

from __future__ import annotations

from typing import Any


def evaluate_gate(
    *,
    task_id: str,
    parent_version: str,
    candidate_version: str,
    failure_report: dict[str, Any],
    parent_tests: list[dict[str, Any]],
    candidate_tests: list[dict[str, Any]],
    parent_runs: list[dict[str, Any]],
    candidate_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    reasons: list[str] = []
    parent_by_test = {item["test_id"]: item for item in parent_tests}
    candidate_by_test = {item["test_id"]: item for item in candidate_tests}
    parent_by_scenario = {item["scenario_id"]: item for item in parent_runs}
    candidate_by_scenario = {item["scenario_id"]: item for item in candidate_runs}

    targeted_bugs = [bug["id"] for bug in failure_report["bugs"]]
    for bug_id in targeted_bugs:
        targeted = [item for item in candidate_tests if item["bug_id"] == bug_id]
        if not targeted:
            reasons.append(f"Bug {bug_id} has no candidate test result.")
        elif any(not item["passed"] for item in targeted):
            reasons.append(f"Targeted tests for {bug_id} failed on the candidate.")

    for test_id, parent_result in parent_by_test.items():
        if not parent_result["passed"]:
            continue
        candidate_result = candidate_by_test.get(test_id)
        if candidate_result is None:
            reasons.append(f"Parent-passing test {test_id} is missing on the candidate.")
        elif not candidate_result["passed"]:
            reasons.append(f"Test {test_id} regressed.")

    evidence: list[str] = []
    for bug in failure_report["bugs"]:
        for scenario_id in bug["evidence_scenario_ids"]:
            if scenario_id not in evidence:
                evidence.append(scenario_id)

    for scenario_id in evidence:
        parent_run = parent_by_scenario.get(scenario_id)
        candidate_run = candidate_by_scenario.get(scenario_id)
        if parent_run is None or candidate_run is None:
            reasons.append(f"Targeted scenario {scenario_id} is missing from the replay.")
            continue
        parent_failed = (not parent_run["passed"]) or parent_run["severe_failure"]
        candidate_ok = candidate_run["passed"] and not candidate_run["severe_failure"]
        if parent_failed and not candidate_ok:
            reasons.append(f"Targeted scenario {scenario_id} did not improve.")

    for scenario_id, candidate_run in candidate_by_scenario.items():
        parent_run = parent_by_scenario.get(scenario_id)
        parent_severe = False if parent_run is None else parent_run["severe_failure"]
        if candidate_run["severe_failure"] and not parent_severe:
            reasons.append(f"New severe failure on {scenario_id}.")

    test_ids = list(dict.fromkeys([*parent_by_test.keys(), *candidate_by_test.keys()]))
    test_deltas = []
    for test_id in test_ids:
        parent_result = parent_by_test.get(test_id)
        candidate_result = candidate_by_test.get(test_id)
        bug_id = (candidate_result or parent_result)["bug_id"]
        test_deltas.append(
            {
                "test_id": test_id,
                "bug_id": bug_id,
                "parent_passed": None if parent_result is None else parent_result["passed"],
                "candidate_passed": None if candidate_result is None else candidate_result["passed"],
            }
        )

    scenario_ids = list(dict.fromkeys([*parent_by_scenario.keys(), *candidate_by_scenario.keys()]))
    simulation_deltas = []
    for scenario_id in scenario_ids:
        parent_run = parent_by_scenario.get(scenario_id)
        candidate_run = candidate_by_scenario.get(scenario_id)
        simulation_deltas.append(
            {
                "scenario_id": scenario_id,
                "parent_passed": None if parent_run is None else parent_run["passed"],
                "candidate_passed": None if candidate_run is None else candidate_run["passed"],
                "parent_severe": None if parent_run is None else parent_run["severe_failure"],
                "candidate_severe": None if candidate_run is None else candidate_run["severe_failure"],
            }
        )

    if reasons:
        decision = "discard"
        reason = " ".join(reasons)
    else:
        decision = "commit"
        reason = (
            "Targeted tests passed, existing tests held, targeted simulations improved, "
            "and no new severe failure appeared."
        )

    return {
        "task_id": task_id,
        "parent_version": parent_version,
        "candidate_version": candidate_version,
        "test_deltas": test_deltas,
        "simulation_deltas": simulation_deltas,
        "decision": decision,
        "reason": reason,
    }
