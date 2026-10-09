"""Read and write versioned artifacts. The loop never reads holdout."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loop.paths import shared, track_b
from loop.schema import dump_json, load_json, validate_agent, validate_task


def load_development_tasks(root: Path) -> list[dict[str, Any]]:
    directory = track_b(root) / "tasks" / "development"
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise RuntimeError(f"no development tasks in {directory}")
    return [validate_task(load_json(path)) for path in paths]


def agent_path(root: Path, task_id: str, version: str) -> Path:
    return shared(root) / "versions" / task_id / version / "agent_config.json"


def save_agent(root: Path, config: dict[str, Any]) -> Path:
    validate_agent(config)
    path = agent_path(root, config["task_id"], config["version"])
    dump_json(path, config)
    if config["parent_id"] is None:
        best = shared(root) / "versions" / config["task_id"] / "BEST"
        best.parent.mkdir(parents=True, exist_ok=True)
        best.write_text(config["version"] + "\n")
    return path


def save_binding(root: Path, config: dict[str, Any], binding: dict[str, Any]) -> Path:
    path = shared(root) / "versions" / config["task_id"] / config["version"] / "runtime_binding.json"
    dump_json(path, binding)
    return path


def load_binding(root: Path, config: dict[str, Any]) -> dict[str, Any] | None:
    path = shared(root) / "versions" / config["task_id"] / config["version"] / "runtime_binding.json"
    if not path.exists():
        return None
    with path.open() as handle:
        return json.load(handle)
