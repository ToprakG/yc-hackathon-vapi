"""Offline Platform for tests. Each persona name maps to a scripted RunResult factory."""

from __future__ import annotations

from typing import Callable

from agentforge.platform.base import Platform
from agentforge.schemas import AgentConfig, Persona, RunResult, Turn, UnitTest, Verdict


class FakePlatform(Platform):
    def __init__(self, unit_test_passes: Callable[[AgentConfig, UnitTest], bool] | None = None):
        self.upserts: list[str] = []
        self.unit_test_passes = unit_test_passes or (lambda cfg, test: True)

    def upsert_agent(self, cfg: AgentConfig) -> str:
        self.upserts.append(cfg.version_label)
        return f"fake-{cfg.version_label}"

    def run_conversation(self, cfg: AgentConfig, persona: Persona, run_idx: int) -> RunResult:
        return RunResult(
            persona_name=persona.name,
            agent_version=cfg.version_label,
            run_idx=run_idx,
            transcript=[
                Turn(role="assistant", text=cfg.first_message, turn_idx=0),
                Turn(role="user", text=persona.prompt[:80], turn_idx=1),
            ],
            ended_reason="fake",
        )

    def run_unit_test(self, cfg: AgentConfig, test: UnitTest) -> Verdict:
        return Verdict(check_name=test.name, passed=self.unit_test_passes(cfg, test))
