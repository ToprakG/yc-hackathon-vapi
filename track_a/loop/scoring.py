"""Score a UnitTest against the run that played its caller lines."""

from __future__ import annotations

from typing import Any

from loop.schema import validate_scenario


def playback_scenarios(task: dict[str, Any], tests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One scenario per test. The scenario id is the test id, and the turns are the caller's lines."""
    scenarios = []
    for test in tests:
        scenarios.append(
            validate_scenario(
                {
                    "id": test["id"],
                    "task_id": task["id"],
                    "persona": "A caller who speaks a fixed script and adds nothing else.",
                    "attack_objective": f"Play unit test {test['id']} for {test['bug_id']}.",
                    "turn_strategy": list(test["scripted_turns"]),
                    "expected_behavior": "The agent follows the invariant this unit test checks.",
                    "failure_condition": "The agent breaks an assertion of this unit test.",
                    "severity": "high",
                }
            )
        )
    return scenarios


def score_tests(tests: list[dict[str, Any]], runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_test = {run["scenario_id"]: run for run in runs}
    return [
        {
            "test_id": test["id"],
            "bug_id": test["bug_id"],
            "passed": _passes(test, by_test.get(test["id"])),
        }
        for test in tests
    ]


def _passes(test: dict[str, Any], run: dict[str, Any] | None) -> bool:
    if run is None:
        return False
    return _assertions_hold(test["assertions"], run)


def _assertions_hold(assertions: list[dict[str, Any]], run: dict[str, Any]) -> bool:
    return all(_assertion_holds(assertion, run) for assertion in assertions)


def _assertion_holds(assertion: dict[str, Any], run: dict[str, Any]) -> bool:
    kind = assertion["type"]
    events = run["tool_events"]
    if kind == "tool_called":
        return any(event["name"] == assertion["tool"] for event in events)
    if kind == "tool_not_called":
        return all(event["name"] != assertion["tool"] for event in events)
    if kind == "args_include":
        expected = assertion["arguments"]
        return any(
            event["name"] == assertion["tool"] and _includes(event["arguments"], expected)
            for event in events
        )
    if kind == "confirmation_present":
        text = " ".join(
            message["content"].lower()
            for message in run["transcript"]
            if message["role"] == "assistant"
        )
        return any(phrase in text for phrase in ("confirm", "correct", "shall i", "should i", "go ahead"))
    if kind == "final_state_equals":
        return _lookup(run["final_state"], assertion["path"]) == assertion["value"]
    return False


def _includes(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(actual.get(key) == value for key, value in expected.items())


def _lookup(state: dict[str, Any], path: str) -> Any:
    current: Any = state
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current
