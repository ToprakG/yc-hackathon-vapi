"""Shared data shapes. Persona and Assertion mirror Freya so they upload unchanged."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

SPLIT_TAGS = ("train", "heldout", "blind")


class ExtractionField(BaseModel):
    name: str
    type: str = "string"
    description: str = ""
    required: bool = False


class ToolDef(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    extraction_schema: list[ExtractionField] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)


class AgentConfig(BaseModel):
    version_label: str
    system_prompt: str
    first_message: str
    tools: list[ToolDef] = Field(default_factory=list)
    model: str
    parent_version: str | None = None
    notes: str = ""


class Persona(BaseModel):
    name: str
    prompt: str
    successCriteria: str
    evaluationPrompt: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def one_split_tag(cls, tags: list[str]) -> list[str]:
        found = [tag for tag in tags if tag in SPLIT_TAGS]
        if len(found) > 1:
            raise ValueError(f"persona has more than one split tag: {found}")
        return tags

    @property
    def split(self) -> str | None:
        return next((tag for tag in self.tags if tag in SPLIT_TAGS), None)


class ContextConfig(BaseModel):
    includeToolCalls: bool = False
    includeExtractionEvents: bool = False
    includeRoutingEvents: bool = False


class Assertion(BaseModel):
    name: str
    prompt: str
    contextConfig: ContextConfig = Field(default_factory=ContextConfig)


class Turn(BaseModel):
    role: Literal["user", "assistant", "tool"]
    text: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    turn_idx: int = 0


class ToolAssertion(BaseModel):
    tool: str
    args: dict[str, Any] | None = None
    negate: bool = False


class UnitTest(BaseModel):
    name: str
    prefix_turns: list[Turn]
    expectation: str
    tool_assertions: list[ToolAssertion] = Field(default_factory=list)


class ToolCallRecord(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    turn_idx: int = 0


class ExtractionEvent(BaseModel):
    field: str
    value: Any = None
    turn_idx: int = 0


class RunResult(BaseModel):
    persona_name: str
    agent_version: str
    run_idx: int = 0
    mode: str = "chat"
    transcript: list[Turn] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    extraction_events: list[ExtractionEvent] = Field(default_factory=list)
    ended_reason: str = ""
    duration_s: float = 0.0
    cost_usd: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class Verdict(BaseModel):
    check_name: str
    passed: bool
    reason: str = ""
    evidence_turn: int | None = None


class ScoredRun(BaseModel):
    run: RunResult
    verdicts: list[Verdict] = Field(default_factory=list)
    passed: bool


class Evidence(BaseModel):
    persona: str
    run_idx: int = 0
    turn: int | None = None


class Bug(BaseModel):
    bug_id: str
    description: str
    generalized_rule: str
    evidence: list[Evidence] = Field(default_factory=list)
    culprit: Literal["agent", "simulator", "judge"] = "agent"
    layer: Literal["prompt", "tool_schema", "first_message"] = "prompt"


class FailureReport(BaseModel):
    version: str
    bugs: list[Bug] = Field(default_factory=list)

    def agent_bugs(self) -> list[Bug]:
        return [bug for bug in self.bugs if bug.culprit == "agent"]


class Patch(BaseModel):
    bug_id: str
    layer: Literal["prompt", "tool_schema", "first_message"]
    operator: str
    before: str = ""
    after: str = ""
    rationale: str = ""
