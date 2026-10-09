"""Phase 3: transcripts + task -> a FailureReport of generalized bugs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loop.builder import load_builder_prompt
from loop.llm import LLMClient, make_llm_client, repairing_json
from loop.paths import shared, track_b
from loop.schema import SchemaError, dump_json, load_json, validate_agent, validate_failure_report, validate_run
from loop.store import load_development_tasks


def generalized_report(report: dict[str, Any]) -> dict[str, Any]:
    bugs = []
    for bug in report["bugs"]:
        evidence = list(dict.fromkeys(bug["evidence_scenario_ids"]))
        if not evidence:
            continue
        bugs.append({**bug, "evidence_scenario_ids": evidence})
    return {**report, "bugs": bugs}


def report_path(root: Path, task_id: str, version: str) -> Path:
    return shared(root) / "versions" / task_id / version / "failure_report.json"


def load_runs(root: Path, task_id: str, agent_version: str) -> list[dict[str, Any]]:
    directory = shared(root) / "runs" / task_id / agent_version
    if not directory.exists():
        return []
    return [validate_run(load_json(path)) for path in sorted(directory.glob("*.json"))]


def run_phase3(root: Path, *, llm: LLMClient | None = None, task_filter: str | None = None) -> int:
    tasks = [task for task in load_development_tasks(root) if not task_filter or task["id"] == task_filter]
    prompt_version, prompt_text = load_builder_prompt(track_b(root) / "prompts" / "analyzer" / "v1.md")
    if llm is None:
        llm = make_llm_client()
    wrote_failure = False
    for task in tasks:
        config = validate_agent(load_json(shared(root) / "versions" / task["id"] / "v1" / "agent_config.json"), task)
        runs = load_runs(root, task["id"], config["id"])
        if len(runs) < 3:
            print(f"{config['id']} has {len(runs)} transcripts. Run phase2 --simulate first.")
            return 1
        report = repairing_json(
            llm,
            system=prompt_text,
            user=_user_message(task, config, runs),
            accept=lambda payload, task=task, config=config: _accept(task, config, payload),
        )
        path = report_path(root, task["id"], "v1")
        dump_json(path, {"prompt_version": prompt_version, **report})
        print(f"stored {len(report['bugs'])} bugs for {config['id']} -> {path}")
        if report["bugs"]:
            wrote_failure = True
    if not wrote_failure:
        print("analyzer found no bugs")
    return 0


def _user_message(task: dict[str, Any], config: dict[str, Any], runs: list[dict[str, Any]]) -> str:
    return json.dumps({"task": task, "agent_version": config["id"], "runs": runs}, indent=2)


def _accept(task: dict[str, Any], config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SchemaError(["FailureReport must be an object"])
    bugs = payload.get("bugs")
    if not isinstance(bugs, list):
        raise SchemaError(["FailureReport.bugs must be a list"])
    kept = []
    for index, bug in enumerate(bugs, start=1):
        if not isinstance(bug, dict):
            raise SchemaError(["each bug must be an object"])
        evidence = bug.get("evidence_scenario_ids")
        if not isinstance(evidence, list):
            raise SchemaError(["each bug needs evidence_scenario_ids"])
        evidence = list(dict.fromkeys(item for item in evidence if isinstance(item, str) and item.strip()))
        if not evidence:
            raise SchemaError(["each bug needs at least one evidence_scenario_id"])
        bug = dict(bug)
        bug["evidence_scenario_ids"] = evidence
        if not bug.get("id"):
            bug["id"] = f"{task['id']}-bug-{index}"
        kept.append(bug)
    report = {
        "id": payload.get("id") or f"report-{config['id']}",
        "task_id": task["id"],
        "agent_version": config["id"],
        "bugs": kept,
    }
    return validate_failure_report(report)
