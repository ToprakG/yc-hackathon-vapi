"""Shared plumbing for the collections experiments (TEST_PLAN sections 0 and 5)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from agentforge.config import RESULTS_DIR, settings
from agentforge.domain.collections import brief_dir, load_personas, load_policy
from agentforge.domain.collections.cases import case_of
from agentforge.platform import get_platform
from agentforge.run.decision import scorer_for
from agentforge.run.runner import check_judge_health, run_suite
from agentforge.schemas import AgentConfig, Persona, ScoredRun
from agentforge.stats import Counts, counts_from_scored
from agentforge.store import load_model


def results_dir(brief: str, label: str) -> Path:
    path = RESULTS_DIR / "collections" / brief / label
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_agent(path: str) -> AgentConfig:
    return load_model(Path(path), AgentConfig)


def cache_key(cfg: AgentConfig, brief: str, platform: str, runs: int) -> str:
    """Changes whenever anything that affects the scores changes: agent, cases, checks, models, platform."""
    folder = brief_dir(brief)
    parts = [cfg.model_dump_json(), (folder / "personas.json").read_text(), (folder / "checks.json").read_text(),
             (folder / "policy.json").read_text(), platform, str(runs), settings().agent_model, settings().simulator_model,
             os.environ.get("DECISION_MODEL") or settings().judge_model]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def groups(brief: str) -> dict[str, str]:
    return {p.name: case.group for p in load_personas(brief) if (case := case_of(p.name))}


def run_cases(cfg: AgentConfig, brief: str, platform_name: str, runs: int, set_name: str,
              cases: list[str] | None = None) -> tuple[list[ScoredRun], Counts]:
    personas: list[Persona] = [p for p in load_personas(brief) if cases is None or p.name in cases]
    if not personas:
        return [], {}
    platform = get_platform(platform_name, brief=brief if platform_name == "local" else None)
    remote_tools = os.environ.get("COLLECTIONS_TOOLS_BASE_URL", "").rstrip("/")
    if platform_name != "local" and remote_tools and hasattr(platform, "tools_base_url"):
        platform.tools_base_url = f"{remote_tools}/{brief}"  # collections tools_server serves /{brief}/tools/{name}
    scored = run_suite(platform, cfg, personas, [], runs_per_persona=runs, set_name=f"{brief}_{set_name}",
                       scorer=scorer_for(load_policy(brief_dir(brief))))
    check_judge_health(scored)
    return scored, counts_from_scored(scored)


def dump(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str) + "\n")
