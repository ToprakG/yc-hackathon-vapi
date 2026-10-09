"""Validators for the shared artifacts. Field names stay stable after Phase 0."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SchemaError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


SEVERITIES = {"low", "medium", "high", "severe"}
SIDE_EFFECTS = {"none", "read", "write"}
ASSERTION_FIELDS = {
    "tool_called": {"tool"},
    "tool_not_called": {"tool"},
    "args_include": {"tool", "arguments"},
    "confirmation_present": set(),
    "final_state_equals": {"path", "value"},
}


def load_json(path: Path) -> Any:
    if "holdout" in path.resolve().parts:
        raise RuntimeError(f"refusing to read holdout artifact: {path}")
    with path.open() as handle:
        return json.load(handle)


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaError([f"{label} must be an object"])
    return value


def _errors(label: str, value: dict[str, Any], required: set[str], optional: set[str]) -> list[str]:
    errors: list[str] = []
    missing = required - value.keys()
    unknown = set(value) - required - optional
    if missing:
        errors.append(f"{label} missing {sorted(missing)}")
    if unknown:
        errors.append(f"{label} has unknown fields {sorted(unknown)}")
    return errors


def _string(value: Any, label: str, errors: list[str], minimum: int = 1) -> None:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        errors.append(f"{label} must be a string of at least {minimum} characters")


def _string_list(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        errors.append(f"{label} must be a list of strings")


def _tool(value: Any, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    errors.extend(_errors(label, value, {"name", "description", "parameters", "side_effects", "errors"}, set()))
    if isinstance(value.get("name"), str) and value["name"].isidentifier() and value["name"].islower():
        pass
    else:
        errors.append(f"{label}.name must be a lower_snake identifier")
    _string(value.get("description"), f"{label}.description", errors)
    parameters = value.get("parameters")
    if not isinstance(parameters, dict) or parameters.get("type") != "object":
        errors.append(f"{label}.parameters must be a JSON schema object")
    if value.get("side_effects") not in SIDE_EFFECTS:
        errors.append(f"{label}.side_effects must be one of {sorted(SIDE_EFFECTS)}")
    _string_list(value.get("errors"), f"{label}.errors", errors)
    return errors


def validate_task(payload: Any) -> dict[str, Any]:
    task = _require_object(payload, "TaskSpec")
    errors = _errors(
        "TaskSpec",
        task,
        {"id", "description", "tools", "constraints", "success_criteria"},
        set(),
    )
    _string(task.get("id"), "TaskSpec.id", errors)
    _string(task.get("description"), "TaskSpec.description", errors, minimum=20)
    tools = task.get("tools")
    if not isinstance(tools, list) or not tools:
        errors.append("TaskSpec.tools must be a non-empty list")
    else:
        names: list[str] = []
        for index, tool in enumerate(tools):
            errors.extend(_tool(tool, f"TaskSpec.tools[{index}]"))
            if isinstance(tool, dict) and isinstance(tool.get("name"), str):
                names.append(tool["name"])
        if len(names) != len(set(names)):
            errors.append("TaskSpec.tools names must be unique")
    _string_list(task.get("constraints"), "TaskSpec.constraints", errors)
    _string_list(task.get("success_criteria"), "TaskSpec.success_criteria", errors)
    if isinstance(task.get("constraints"), list) and not task["constraints"]:
        errors.append("TaskSpec.constraints must not be empty")
    if isinstance(task.get("success_criteria"), list) and not task["success_criteria"]:
        errors.append("TaskSpec.success_criteria must not be empty")
    if errors:
        raise SchemaError(errors)
    return task


def validate_agent(payload: Any, task: dict[str, Any] | None = None) -> dict[str, Any]:
    agent = _require_object(payload, "AgentConfig")
    errors = _errors(
        "AgentConfig",
        agent,
        {
            "id",
            "task_id",
            "parent_id",
            "version",
            "prompt_version",
            "system_prompt",
            "first_message",
            "tools",
            "runtime",
        },
        set(),
    )
    _string(agent.get("id"), "AgentConfig.id", errors)
    _string(agent.get("task_id"), "AgentConfig.task_id", errors)
    if agent.get("parent_id") is not None:
        _string(agent.get("parent_id"), "AgentConfig.parent_id", errors)
    _string(agent.get("version"), "AgentConfig.version", errors)
    _string(agent.get("prompt_version"), "AgentConfig.prompt_version", errors)
    _string(agent.get("system_prompt"), "AgentConfig.system_prompt", errors, minimum=40)
    _string(agent.get("first_message"), "AgentConfig.first_message", errors, minimum=8)
    if isinstance(agent.get("first_message"), str) and len(agent["first_message"]) > 500:
        errors.append("AgentConfig.first_message must be at most 500 characters")
    tools = agent.get("tools")
    names: list[str] = []
    if not isinstance(tools, list) or not tools:
        errors.append("AgentConfig.tools must be a non-empty list")
    else:
        for index, tool in enumerate(tools):
            errors.extend(_tool(tool, f"AgentConfig.tools[{index}]"))
            if isinstance(tool, dict) and isinstance(tool.get("name"), str):
                names.append(tool["name"])
        if len(names) != len(set(names)):
            errors.append("AgentConfig.tools names must be unique")
    prompt = agent.get("system_prompt")
    if isinstance(prompt, str):
        for name in names:
            if name not in prompt:
                errors.append(f"AgentConfig.system_prompt must mention tool {name}")
    runtime = agent.get("runtime")
    if not isinstance(runtime, dict):
        errors.append("AgentConfig.runtime must be an object")
    else:
        errors.extend(
            _errors(
                "AgentConfig.runtime",
                runtime,
                {"provider", "model_provider", "model", "voice_provider", "voice_id"},
                set(),
            )
        )
        for key in ("provider", "model_provider", "model", "voice_provider", "voice_id"):
            _string(runtime.get(key), f"AgentConfig.runtime.{key}", errors)
    if task is not None and isinstance(tools, list):
        expected = [tool["name"] for tool in task["tools"]]
        if names != expected:
            errors.append(f"AgentConfig.tools must match the task tools {expected}")
        if agent.get("task_id") != task["id"]:
            errors.append("AgentConfig.task_id must match the task id")
    if errors:
        raise SchemaError(errors)
    return agent


def validate_scenario(payload: Any) -> dict[str, Any]:
    scenario = _require_object(payload, "ScenarioSpec")
    errors = _errors(
        "ScenarioSpec",
        scenario,
        {
            "id",
            "task_id",
            "persona",
            "attack_objective",
            "turn_strategy",
            "expected_behavior",
            "failure_condition",
            "severity",
        },
        set(),
    )
    for key in ("id", "task_id", "persona", "attack_objective", "expected_behavior", "failure_condition"):
        _string(scenario.get(key), f"ScenarioSpec.{key}", errors)
    _string_list(scenario.get("turn_strategy"), "ScenarioSpec.turn_strategy", errors)
    if isinstance(scenario.get("turn_strategy"), list) and not scenario["turn_strategy"]:
        errors.append("ScenarioSpec.turn_strategy must not be empty")
    if scenario.get("severity") not in SEVERITIES:
        errors.append(f"ScenarioSpec.severity must be one of {sorted(SEVERITIES)}")
    if errors:
        raise SchemaError(errors)
    return scenario


def validate_run(payload: Any) -> dict[str, Any]:
    run = _require_object(payload, "RunRecord")
    errors = _errors(
        "RunRecord",
        run,
        {
            "id",
            "task_id",
            "agent_version",
            "scenario_id",
            "transcript",
            "tool_events",
            "final_state",
            "latency_ms",
            "token_usage",
            "cost_estimate_usd",
            "errors",
            "passed",
            "severe_failure",
        },
        set(),
    )
    for key in ("id", "task_id", "agent_version", "scenario_id"):
        _string(run.get(key), f"RunRecord.{key}", errors)
    transcript = run.get("transcript")
    if not isinstance(transcript, list) or not transcript:
        errors.append("RunRecord.transcript must be a non-empty list")
    else:
        for index, turn in enumerate(transcript):
            if not isinstance(turn, dict):
                errors.append(f"RunRecord.transcript[{index}] must be an object")
                continue
            if turn.get("role") not in {"user", "assistant", "tool", "system"}:
                errors.append(f"RunRecord.transcript[{index}].role is invalid")
            _string(turn.get("content"), f"RunRecord.transcript[{index}].content", errors)
    events = run.get("tool_events")
    if not isinstance(events, list):
        errors.append("RunRecord.tool_events must be a list")
    else:
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                errors.append(f"RunRecord.tool_events[{index}] must be an object")
                continue
            _string(event.get("name"), f"RunRecord.tool_events[{index}].name", errors)
            if not isinstance(event.get("arguments"), dict):
                errors.append(f"RunRecord.tool_events[{index}].arguments must be an object")
            if "result" not in event:
                errors.append(f"RunRecord.tool_events[{index}].result is required")
    if not isinstance(run.get("final_state"), dict):
        errors.append("RunRecord.final_state must be an object")
    if not isinstance(run.get("latency_ms"), (int, float)) or isinstance(run.get("latency_ms"), bool):
        errors.append("RunRecord.latency_ms must be a number")
    usage = run.get("token_usage")
    if not isinstance(usage, dict):
        errors.append("RunRecord.token_usage must be an object")
    else:
        for key in ("input", "output"):
            if not isinstance(usage.get(key), int) or isinstance(usage.get(key), bool) or usage.get(key) < 0:
                errors.append(f"RunRecord.token_usage.{key} must be a non-negative integer")
    if not isinstance(run.get("cost_estimate_usd"), (int, float)) or isinstance(run.get("cost_estimate_usd"), bool):
        errors.append("RunRecord.cost_estimate_usd must be a number")
    _string_list(run.get("errors"), "RunRecord.errors", errors)
    if not isinstance(run.get("passed"), bool):
        errors.append("RunRecord.passed must be a boolean")
    if not isinstance(run.get("severe_failure"), bool):
        errors.append("RunRecord.severe_failure must be a boolean")
    if errors:
        raise SchemaError(errors)
    return run


def validate_failure_report(payload: Any) -> dict[str, Any]:
    report = _require_object(payload, "FailureReport")
    errors = _errors(
        "FailureReport",
        report,
        {"id", "task_id", "agent_version", "bugs"},
        set(),
    )
    for key in ("id", "task_id", "agent_version"):
        _string(report.get(key), f"FailureReport.{key}", errors)
    bugs = report.get("bugs")
    if not isinstance(bugs, list):
        errors.append("FailureReport.bugs must be a list")
    else:
        for index, bug in enumerate(bugs):
            label = f"FailureReport.bugs[{index}]"
            if not isinstance(bug, dict):
                errors.append(f"{label} must be an object")
                continue
            errors.extend(
                _errors(
                    label,
                    bug,
                    {"id", "statement", "evidence_scenario_ids", "severity", "suggested_invariant"},
                    set(),
                )
            )
            _string(bug.get("id"), f"{label}.id", errors)
            _string(bug.get("statement"), f"{label}.statement", errors, minimum=20)
            _string_list(bug.get("evidence_scenario_ids"), f"{label}.evidence_scenario_ids", errors)
            if isinstance(bug.get("evidence_scenario_ids"), list) and not bug["evidence_scenario_ids"]:
                errors.append(f"{label}.evidence_scenario_ids must not be empty")
            if bug.get("severity") not in SEVERITIES:
                errors.append(f"{label}.severity must be one of {sorted(SEVERITIES)}")
            _string(bug.get("suggested_invariant"), f"{label}.suggested_invariant", errors, minimum=20)
    if errors:
        raise SchemaError(errors)
    return report


def validate_unit_test(payload: Any) -> dict[str, Any]:
    test = _require_object(payload, "UnitTest")
    errors = _errors(
        "UnitTest",
        test,
        {"id", "bug_id", "task_id", "scripted_turns", "assertions"},
        set(),
    )
    for key in ("id", "bug_id", "task_id"):
        _string(test.get(key), f"UnitTest.{key}", errors)
    _string_list(test.get("scripted_turns"), "UnitTest.scripted_turns", errors)
    if isinstance(test.get("scripted_turns"), list) and not test["scripted_turns"]:
        errors.append("UnitTest.scripted_turns must not be empty")
    assertions = test.get("assertions")
    if not isinstance(assertions, list) or not assertions:
        errors.append("UnitTest.assertions must be a non-empty list")
    else:
        for index, assertion in enumerate(assertions):
            label = f"UnitTest.assertions[{index}]"
            if not isinstance(assertion, dict):
                errors.append(f"{label} must be an object")
                continue
            kind = assertion.get("type")
            if kind not in ASSERTION_FIELDS:
                errors.append(f"{label}.type is invalid")
                continue
            expected = {"type"} | ASSERTION_FIELDS[kind]
            unknown = set(assertion) - expected
            missing = expected - set(assertion)
            if unknown:
                errors.append(f"{label} has unknown fields {sorted(unknown)}")
            if missing:
                errors.append(f"{label} missing {sorted(missing)}")
            if kind in {"tool_called", "tool_not_called", "args_include"}:
                _string(assertion.get("tool"), f"{label}.tool", errors)
            if kind == "args_include" and not isinstance(assertion.get("arguments"), dict):
                errors.append(f"{label}.arguments must be an object")
            if kind == "final_state_equals":
                _string(assertion.get("path"), f"{label}.path", errors)
                if "value" not in assertion:
                    errors.append(f"{label}.value is required")
    if errors:
        raise SchemaError(errors)
    return test


def validate_test_results(payload: Any) -> list[dict[str, Any]]:
    body = _require_object(payload, "test results")
    errors = _errors("test results", body, {"results"}, set())
    results = body.get("results")
    if not isinstance(results, list):
        errors.append("test results.results must be a list")
        raise SchemaError(errors)
    for index, result in enumerate(results):
        label = f"test results.results[{index}]"
        if not isinstance(result, dict):
            errors.append(f"{label} must be an object")
            continue
        errors.extend(_errors(label, result, {"test_id", "bug_id", "passed"}, set()))
        _string(result.get("test_id"), f"{label}.test_id", errors)
        _string(result.get("bug_id"), f"{label}.bug_id", errors)
        if not isinstance(result.get("passed"), bool):
            errors.append(f"{label}.passed must be a boolean")
    if errors:
        raise SchemaError(errors)
    return results


def validate_gate_decision(payload: Any) -> dict[str, Any]:
    decision = _require_object(payload, "GateDecision")
    errors = _errors(
        "GateDecision",
        decision,
        {
            "task_id",
            "parent_version",
            "candidate_version",
            "test_deltas",
            "simulation_deltas",
            "decision",
            "reason",
        },
        set(),
    )
    for key in ("task_id", "parent_version", "candidate_version"):
        _string(decision.get(key), f"GateDecision.{key}", errors)
    if decision.get("decision") not in {"commit", "discard"}:
        errors.append("GateDecision.decision must be commit or discard")
    _string(decision.get("reason"), "GateDecision.reason", errors, minimum=10)
    if not isinstance(decision.get("test_deltas"), list):
        errors.append("GateDecision.test_deltas must be a list")
    if not isinstance(decision.get("simulation_deltas"), list):
        errors.append("GateDecision.simulation_deltas must be a list")
    if errors:
        raise SchemaError(errors)
    return decision
