"""Domain packs: one folder per task with sop.md and tools.json."""

from __future__ import annotations

from pathlib import Path

from pydantic import TypeAdapter

from agentforge.config import DOMAIN_DIR
from agentforge.schemas import ToolDef


def resolve_domain(domain: str | Path) -> Path:
    path = Path(domain)
    if path.is_dir():
        return path
    for candidate in (DOMAIN_DIR / path.name, DOMAIN_DIR.parent / path):
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"domain not found: {domain}")


def load_domain(domain: str | Path) -> tuple[str, list[ToolDef]]:
    """Return (task_md, tools) from sop.md and tools.json. Never reads blind_* files."""
    path = resolve_domain(domain)
    task_md = (path / "sop.md").read_text()
    tools = TypeAdapter(list[ToolDef]).validate_json((path / "tools.json").read_text())
    return task_md, tools
