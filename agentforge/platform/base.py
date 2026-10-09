"""The only interface the pipeline uses to talk to a voice platform."""

from __future__ import annotations

from abc import ABC, abstractmethod

from agentforge.schemas import AgentConfig, Persona, RunResult, UnitTest, Verdict


class Platform(ABC):
    @abstractmethod
    def upsert_agent(self, cfg: AgentConfig) -> str:
        """Create or update the agent and return the platform id."""

    @abstractmethod
    def run_conversation(self, cfg: AgentConfig, persona: Persona, run_idx: int) -> RunResult:
        """Run one simulated conversation between the agent and a persona."""

    @abstractmethod
    def run_unit_test(self, cfg: AgentConfig, test: UnitTest) -> Verdict:
        """Replay test.prefix_turns and judge the agent's next move."""
