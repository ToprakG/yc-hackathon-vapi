"""Write the five brief folders from the catalog. accounts.json is not read by the builder."""

from __future__ import annotations

import json
from pathlib import Path

from agentforge.build.extract import extract
from agentforge.config import DOMAIN_DIR
from agentforge.domain.collections.catalog import BRIEFS
from agentforge.domain.collections.personas import build_personas, build_unit_tests
from agentforge.schemas import ToolDef

ACCOUNTS = [
    {
        "account_id": "A-100",
        "name": "Ada Lovelace",
        "balance": 480,
        "id_last4": "4242",
        "birth_date": "1985-12-10",
    }
]


def write_briefs(root: Path | None = None) -> list[Path]:
    base = root or (DOMAIN_DIR / "collections")
    written: list[Path] = []
    for name, brief in BRIEFS.items():
        folder = base / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "sop.md").write_text(brief["sop"], encoding="utf-8")
        (folder / "tools.json").write_text(json.dumps(brief["tools"], indent=2) + "\n", encoding="utf-8")
        (folder / "accounts.json").write_text(json.dumps(ACCOUNTS, indent=2) + "\n", encoding="utf-8")
        tools = [ToolDef.model_validate(tool) for tool in brief["tools"]]
        policy = extract(brief["sop"], tools)
        personas = [item.model_dump(mode="json") for item in build_personas(policy)]
        tests = [item.model_dump(mode="json") for item in build_unit_tests(policy)]
        (folder / "personas.json").write_text(json.dumps(personas, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (folder / "unit_tests.json").write_text(json.dumps(tests, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(folder)
    return written


if __name__ == "__main__":
    for path in write_briefs():
        print(path)
