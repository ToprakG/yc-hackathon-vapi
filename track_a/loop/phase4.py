"""Phase 4: one FailureReport feeds tests and a V2 patch. They do not see each other."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from loop.builder import assemble, load_builder_prompt
from loop.llm import LLMClient, make_llm_client, repairing_json
from loop.paths import shared, track_b
from loop.phase3 import generalized_report, report_path
from loop.schema import (
    ASSERTION_FIELDS,
    SchemaError,
    dump_json,
    load_json,
    validate_agent,
    validate_failure_report,
    validate_unit_test,
)
from loop.store import load_development_tasks, save_agent


def tests_path(root: Path, task_id: str) -> Path:
    return shared(root) / "versions" / task_id / "v1" / "unit_tests.json"


def run_phase4(root: Path, *, llm: LLMClient | None = None, task_filter: str | None = None) -> int:
    tasks = [task for task in load_development_tasks(root) if not task_filter or task["id"] == task_filter]
    test_version, test_prompt = load_builder_prompt(track_b(root) / "prompts" / "test_generator" / "v1.md")
    patch_version, patch_prompt = load_builder_prompt(track_b(root) / "prompts" / "patcher" / "v1.md")
    if llm is None:
        llm = make_llm_client()
    for task in tasks:
        path = report_path(root, task["id"], "v1")
        if not path.exists():
            print(f"missing failure report for {task['id']}. Run phase3 first.")
            return 1
        stored = load_json(path)
        report = generalized_report(
            validate_failure_report({key: stored[key] for key in ("id", "task_id", "agent_version", "bugs")})
        )
        parent = validate_agent(load_json(shared(root) / "versions" / task["id"] / "v1" / "agent_config.json"), task)
        if not report["bugs"]:
            dump_json(tests_path(root, task["id"]), {"prompt_version": test_version, "tests": []})
            print(f"{parent['id']} has no bugs. No tests and no V2.")
            continue
        generated = repairing_json(
            llm,
            system=test_prompt,
            user=_test_user(task, report),
            accept=lambda payload, task=task, report=report: _accept_tests(task, report, payload),
        )
        dump_json(
            tests_path(root, task["id"]),
            {
                "prompt_version": test_version,
                "tests": generated["tests"],
                "untestable_bug_ids": generated["untestable_bug_ids"],
            },
        )
        print(f"stored {len(generated['tests'])} tests for {task['id']}")
        if generated["untestable_bug_ids"]:
            skipped = ", ".join(item["bug_id"] for item in generated["untestable_bug_ids"])
            print(f"untestable bugs for {task['id']}: {skipped}")
        # The patcher reads the report and the current agent. It does not read the tests.
        draft = repairing_json(
            llm,
            system=patch_prompt,
            user=_patch_user(task, parent, report),
            accept=lambda payload: payload,
        )
        _log_changes(draft)
        config = assemble(task, draft, patch_version)
        config["id"] = f"{task['id']}-v2"
        config["version"] = "v2"
        config["parent_id"] = parent["id"]
        saved = validate_agent(config, task)
        out = save_agent(root, saved)
        print(f"stored {saved['id']} -> {out}")
    return 0


def _test_user(task: dict[str, Any], report: dict[str, Any]) -> str:
    return json.dumps({"task": task, "failure_report": report}, indent=2)


def _patch_user(task: dict[str, Any], parent: dict[str, Any], report: dict[str, Any]) -> str:
    return json.dumps({"task": task, "agent": parent, "failure_report": report}, indent=2)


def _log_changes(draft: Any) -> None:
    if not isinstance(draft, dict) or not isinstance(draft.get("changes"), list):
        return
    for change in draft["changes"]:
        if isinstance(change, dict):
            print(f"patch {change.get('bug_id')}: {change.get('edit')}")


def _accept_tests(task: dict[str, Any], report: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SchemaError(["test generator must return an object"])
    tests = payload.get("tests")
    untestable = payload.get("untestable_bug_ids") or []
    if not isinstance(tests, list):
        raise SchemaError(["tests must be a list"])
    if not isinstance(untestable, list):
        raise SchemaError(["untestable_bug_ids must be a list"])
    bug_ids = {bug["id"] for bug in report["bugs"]}
    accepted = []
    covered: set[str] = set()
    for index, test in enumerate(tests, start=1):
        if not isinstance(test, dict):
            raise SchemaError([f"tests[{index}] must be an object"])
        validated = validate_unit_test(_normalize_test(task, test, index))
        bug = next((item for item in report["bugs"] if item["id"] == validated["bug_id"]), None)
        if bug is not None:
            reproduced = _assertion_reproduces_bug(task, bug, validated)
            if reproduced:
                raise SchemaError([reproduced])
        if validated["bug_id"] not in bug_ids:
            raise SchemaError([f"unknown bug_id {validated['bug_id']}"])
        if validated["task_id"] != task["id"]:
            raise SchemaError([f"test {validated['id']} task_id must be {task['id']}"])
        accepted.append(validated)
        covered.add(validated["bug_id"])
    skipped = []
    for index, item in enumerate(untestable):
        if not isinstance(item, dict):
            raise SchemaError([f"untestable_bug_ids[{index}] must be an object"])
        bug_id = item.get("bug_id")
        reason = item.get("reason")
        if not isinstance(bug_id, str) or not bug_id.strip() or not isinstance(reason, str) or not reason.strip():
            raise SchemaError([f"untestable_bug_ids[{index}] needs bug_id and reason"])
        if bug_id not in bug_ids:
            raise SchemaError([f"unknown untestable bug {bug_id}"])
        if bug_id in covered:
            raise SchemaError([f"{bug_id} is both tested and untestable"])
        skipped.append({"bug_id": bug_id, "reason": reason.strip()})
        covered.add(bug_id)
    missing = [bug["id"] for bug in report["bugs"] if bug["id"] not in covered]
    if missing:
        raise SchemaError([f"missing a unit test or untestable entry for {missing}"])
    return {"tests": accepted, "untestable_bug_ids": skipped}


def _assertion_reproduces_bug(task: dict[str, Any], bug: dict[str, Any], test: dict[str, Any]) -> str | None:
    write_tools = {tool["name"] for tool in task["tools"] if tool.get("side_effects") == "write"}
    text = f"{bug.get('statement', '')} {bug.get('suggested_invariant', '')}".lower()
    if _explicit_yes(test.get("scripted_turns") or []):
        return None
    for assertion in test["assertions"]:
        if assertion.get("type") != "tool_called":
            continue
        tool = assertion.get("tool")
        if tool not in write_tools or tool.lower() not in text:
            continue
        if any(
            phrase in text
            for phrase in ("without", "before", "noncommittal", "never", "only after", "only called", "no explicit", "unconfirmed")
        ):
            return (
                f"test {test['id']} asserts {tool} was called, which is the bug. "
                "Assert tool_not_called unless a scripted turn is an explicit yes."
            )
    return None


def _explicit_yes(turns: list[Any]) -> bool:
    pattern = re.compile(
        r"\b(yes|yeah|yep)\b|that(?:'s| is) (?:correct|right)|go ahead|book it|please book",
        re.IGNORECASE,
    )
    return any(isinstance(turn, str) and pattern.search(turn) for turn in turns)


def _normalize_test(task: dict[str, Any], test: dict[str, Any], index: int) -> dict[str, Any]:
    test = dict(test)
    if not test.get("id"):
        test["id"] = f"{test.get('bug_id') or 'bug'}-test-{index}"
    if not test.get("task_id"):
        test["task_id"] = task["id"]
    assertions = test.get("assertions")
    if isinstance(assertions, list):
        test["assertions"] = [_normalize_assertion(assertion, task) for assertion in assertions]
    return test


def _normalize_assertion(assertion: Any, task: dict[str, Any]) -> Any:
    if not isinstance(assertion, dict):
        return assertion
    assertion = dict(assertion)
    if not isinstance(assertion.get("tool"), str):
        for key in ("tool_name", "toolName", "name", "function"):
            if isinstance(assertion.get(key), str) and assertion[key].strip():
                assertion["tool"] = assertion[key].strip()
                break
    kind = assertion.get("type")
    if kind in ASSERTION_FIELDS:
        allowed = {"type"} | ASSERTION_FIELDS[kind]
        assertion = {key: value for key, value in assertion.items() if key in allowed}
    if kind in {"tool_called", "tool_not_called", "args_include"} and not assertion.get("tool"):
        blob = json.dumps(assertion).lower()
        found = [tool["name"] for tool in task["tools"] if tool["name"].lower() in blob]
        if len(found) == 1:
            assertion["tool"] = found[0]
    if kind == "args_include" and not isinstance(assertion.get("arguments"), dict):
        assertion["arguments"] = {}
    return assertion
