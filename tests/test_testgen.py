import pytest

from agentforge import llm
from agentforge.schemas import AgentConfig, Persona, ToolDef
from agentforge.testgen.adversary import generate_adversary
from agentforge.testgen.assertions import generate_assertions
from agentforge.testgen.coverage import generate_coverage
from agentforge.testgen.split import split_personas

TOOLS = [ToolDef(name="verify_identity", description="Verify caller.")]
CFG = AgentConfig(version_label="v1", system_prompt="Sen bir sigorta asistanısın.", first_message="Merhaba", model="openai:gpt-4o")


def scripted(monkeypatch, *replies):
    calls = []
    queue = list(replies)

    def fake(system, user, model=None, json_schema=None, temperature=0.2, **kwargs):
        calls.append((system, user, json_schema))
        return queue.pop(0)

    monkeypatch.setattr(llm, "call_llm", fake)
    return calls


def persona_items(n, key="failure_mode"):
    return [{key: f"mode {i}", "name": f"Caller {i}", "prompt": "Ben Ayşe.", "successCriteria": "verify first"} for i in range(n)]


def test_adversary_two_calls_and_tags(monkeypatch):
    modes = [{"slug": f"m{i}", "description": "d", "why_this_agent": "w", "likelihood": i / 10} for i in range(6)]
    calls = scripted(monkeypatch, {"failure_modes": modes}, {"personas": persona_items(4)})
    personas = generate_adversary("SOP", TOOLS, CFG, n=4)
    assert len(calls) == 2
    assert "m5" in calls[1][1] and "m0" not in calls[1][1]  # top-likelihood modes only
    assert len(personas) == 4
    assert personas[0].tags == ["adversary", "fm:mode-0"]
    assert personas[0].name == "adv-caller-0"


def test_coverage_tags(monkeypatch):
    scripted(monkeypatch, {"personas": persona_items(6, key="path")})
    personas = generate_coverage("SOP", TOOLS, n=6)
    assert len(personas) == 6
    assert personas[2].tags == ["coverage", "path:mode-2"]


def test_assertions_include_tool_calls(monkeypatch):
    scripted(monkeypatch, {"assertions": [{"name": "no_pii", "prompt": "Never read full TCKN."}]})
    [assertion] = generate_assertions("SOP")
    assert assertion.contextConfig.includeToolCalls


def make(name, *tags):
    return Persona(name=name, prompt="p", successCriteria="s", tags=list(tags))


def test_split_is_stratified_and_deterministic():
    personas = [make(f"adv{i}", "adversary", f"fm:{i}") for i in range(4)] + [
        make(f"cov{i}", "coverage", f"path:{i}", "heldout") for i in range(6)
    ]
    first = split_personas(personas)
    assert first == split_personas(personas)
    assert all(sum(t in ("train", "heldout", "blind") for t in p.tags) == 1 for p in first)
    for kind, total in (("adversary", 4), ("coverage", 6)):
        held = [p for p in first if kind in p.tags and p.split == "heldout"]
        assert 1 <= len(held) < total
    assert sum(p.split == "heldout" for p in first) == 4  # 40% of 10


def test_split_stratifies_repeated_modes():
    personas = [make(f"a{i}", "adversary", "fm:order") for i in range(2)] + [make("b", "adversary", "fm:pii")]
    splits = {p.name: p.split for p in split_personas(personas)}
    assert sorted([splits["a0"], splits["a1"]]) == ["heldout", "train"]
