import importlib

import pytest

from agentforge.llm import parse_json
from agentforge.schemas import (
    AgentConfig,
    Assertion,
    Bug,
    FailureReport,
    Persona,
    RunResult,
    ScoredRun,
    ToolDef,
    Turn,
    UnitTest,
    Verdict,
)

MODULES = [
    "agentforge.config",
    "agentforge.llm",
    "agentforge.schemas",
    "agentforge.platform.base",
]


@pytest.mark.parametrize("name", MODULES)
def test_imports(name):
    importlib.import_module(name)


def roundtrip(model):
    assert type(model).model_validate_json(model.model_dump_json()) == model


def test_schema_roundtrip():
    tool = ToolDef(name="get_policy", description="Look up a policy.", preconditions=["identity verified"])
    roundtrip(tool)
    roundtrip(AgentConfig(version_label="v1", system_prompt="s", first_message="Merhaba", tools=[tool], model="openai:gpt-4o"))
    roundtrip(Persona(name="p", prompt="Ben Ali.", successCriteria="Agent verifies identity.", tags=["train"]))
    roundtrip(Assertion.model_validate({"name": "a", "prompt": "No PII", "contextConfig": {"includeToolCalls": True}}))
    turns = [Turn(role="assistant", text="Merhaba", turn_idx=0), Turn(role="user", text="Hasar", turn_idx=1)]
    roundtrip(UnitTest(name="t", prefix_turns=turns, expectation="asks for TCKN", tool_assertions=[{"tool": "get_policy", "negate": True}]))
    run = RunResult(persona_name="p", agent_version="v1", transcript=turns, tool_calls=[{"name": "get_policy", "args": {}}])
    roundtrip(ScoredRun(run=run, verdicts=[Verdict(check_name="success", passed=True)], passed=True))
    report = FailureReport(version="v1", bugs=[Bug(bug_id="b1", description="d", generalized_rule="r", culprit="judge")])
    roundtrip(report)
    assert report.agent_bugs() == []


def test_persona_rejects_two_split_tags():
    with pytest.raises(ValueError):
        Persona(name="p", prompt="x", successCriteria="y", tags=["train", "heldout"])


def test_parse_json_tolerates_fences():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Here: {"a": 2} done') == {"a": 2}
