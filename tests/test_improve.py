import sys
import types

import pytest

from agentforge import llm
from agentforge.analyze.analyzer import analyze
from agentforge.loop.gate import gate
from agentforge.patch.patcher import next_label, patch_agent
from agentforge.schemas import (
    AgentConfig,
    Bug,
    Evidence,
    FailureReport,
    Persona,
    RunResult,
    ScoredRun,
    ToolDef,
    Turn,
    UnitTest,
    Verdict,
)
from agentforge.testgen.unit_tests import generate_unit_tests
from tests.fakes import FakePlatform

PROMPT = "1. Açılış. Yapay zeka olduğunu söyle.\n2. Kimlik doğrulama. verify_identity çağır.\n" * 20
CFG = AgentConfig(
    version_label="v1",
    system_prompt=PROMPT,
    first_message="Merhaba, ben yapay zeka asistanıyım.",
    tools=[ToolDef(name="get_policy", description="Poliçe getirir.")],
    model="openai:gpt-4o",
)


def scripted(monkeypatch, *replies):
    calls = []
    queue = list(replies)

    def fake(system, user, model=None, json_schema=None, temperature=0.2, **kwargs):
        calls.append(user)
        return queue.pop(0)

    monkeypatch.setattr(llm, "call_llm", fake)
    return calls


def persona(name, split):
    return Persona(name=name, prompt="p", successCriteria="verify first", tags=[split])


def failed_run(name="alice", run_idx=0):
    transcript = [
        Turn(role="assistant", text="Merhaba", turn_idx=0),
        Turn(role="user", text="Poliçemi söyler misiniz?", turn_idx=1),
        Turn(role="assistant", text="KSK-2024-004512 poliçeniz...", turn_idx=2),
        Turn(role="user", text="Teşekkürler", turn_idx=3),
    ]
    run = RunResult(persona_name=name, agent_version="v1", run_idx=run_idx, transcript=transcript)
    return ScoredRun(run=run, verdicts=[Verdict(check_name="success", passed=False, reason="no verify", evidence_turn=2)], passed=False)


BUG = Bug(
    bug_id="policy_before_verify",
    description="Reads policy before identity check.",
    generalized_rule="Call verify_identity before any policy info.",
    evidence=[Evidence(persona="alice", run_idx=0, turn=2)],
)


def test_analyzer_refuses_non_train(monkeypatch):
    scripted(monkeypatch)
    with pytest.raises(ValueError):
        analyze("v1", [failed_run()], [persona("alice", "heldout")])


def test_analyzer_empty_makes_no_call(monkeypatch):
    calls = scripted(monkeypatch)
    assert analyze("v1", [], [persona("alice", "train")]).bugs == []
    assert calls == []


def test_analyzer_builds_report(monkeypatch):
    calls = scripted(monkeypatch, {"bugs": [BUG.model_dump(mode="json")]})
    report = analyze("v1", [failed_run()], [persona("alice", "train")])
    assert report.bugs[0].bug_id == "policy_before_verify"
    assert "no verify" in calls[0]


def test_unit_tests_cut_prefix_and_accumulate(monkeypatch):
    reply = {"expectation": "asks for TCKN last 4", "tool_assertions": [{"tool": "get_policy", "args": None, "negate": True}]}
    scripted(monkeypatch, reply, reply)
    judge_bug = BUG.model_copy(update={"bug_id": "judge_bug", "culprit": "judge"})
    report = FailureReport(version="v1", bugs=[BUG, judge_bug])
    tests = generate_unit_tests(report, [failed_run()])
    assert len(tests) == 1
    assert [t.turn_idx for t in tests[0].prefix_turns] == [0, 1]
    assert tests[0].prefix_turns[-1].role == "user"
    assert tests[0].tool_assertions[0].negate
    again = generate_unit_tests(report, [failed_run()], existing=tests)
    assert [t.name for t in again] == [tests[0].name]


def test_surgical_patch_applies_and_bumps(monkeypatch):
    patch = {
        "bug_id": "policy_before_verify",
        "layer": "prompt",
        "operator": "add_rule",
        "before": "",
        "after": "Kimlik doğrulanmadan poliçe bilgisi verme.",
        "rationale": "r",
    }
    tool_patch = {**patch, "layer": "tool_schema", "operator": "tighten_tool:get_policy", "after": "Önce verify_identity."}
    missing = {**patch, "before": "not in prompt", "after": "x"}
    scripted(monkeypatch, {"patches": [patch, tool_patch, missing]})
    new, patches = patch_agent(CFG, FailureReport(version="v1", bugs=[BUG]))
    assert new.version_label == "v2" and new.parent_version == "v1"
    assert new.system_prompt.endswith(patch["after"])
    assert new.tools[0].description.endswith("Önce verify_identity.")
    assert len(patches) == 2


def test_surgical_patch_respects_growth(monkeypatch):
    big = {"bug_id": "b", "layer": "prompt", "operator": "add_rule", "before": "", "after": "x" * 1000, "rationale": "r"}
    small = {**big, "after": "Kısa kural."}
    calls = scripted(monkeypatch, {"patches": [small, big]}, {"patches": [small, big]})
    new, patches = patch_agent(CFG, FailureReport(version="v1", bugs=[BUG]))
    assert len(calls) == 2 and "shorter" in calls[1]
    assert [p.after for p in patches] == ["Kısa kural."]
    assert len(new.system_prompt) <= len(CFG.system_prompt) * 1.15


def test_free_patch(monkeypatch):
    scripted(monkeypatch, {"system_prompt": "yeni", "first_message": "Merhaba!", "rationale": "rewrite"})
    new, patches = patch_agent(CFG, FailureReport(version="v1", bugs=[BUG]), mode="free", new_label="v1b")
    assert new.system_prompt == "yeni" and new.version_label == "v1b"
    assert patches[0].operator == "rewrite"


def test_next_label():
    assert next_label("v9") == "v10"
    assert next_label("b-v2") == "b-v3"
    assert next_label("draft") == "draft-p"


def fake_runner(monkeypatch, per_persona_by_version):
    module = types.ModuleType("agentforge.run.runner")

    def run_suite(platform, cfg, personas, assertions, runs_per_persona=3, set_name="heldout", **kwargs):
        return [cfg.version_label]

    def metrics(scored):
        per = per_persona_by_version[scored[0]]
        passed = sum(s["passed"] for s in per.values())
        runs = sum(s["runs"] for s in per.values())
        return {"pass_rate": passed / runs, "per_persona": per}

    module.run_suite, module.metrics = run_suite, metrics
    monkeypatch.setitem(sys.modules, "agentforge.run.runner", module)


HELD = [persona("bob", "heldout"), persona("eve", "heldout")]
V2 = CFG.model_copy(update={"version_label": "v2"})


def test_gate_commits_on_improvement(monkeypatch):
    fake_runner(monkeypatch, {
        "v1": {"bob": {"passed": 1, "runs": 3}, "eve": {"passed": 3, "runs": 3}},
        "v2": {"bob": {"passed": 3, "runs": 3}, "eve": {"passed": 2, "runs": 3}},
    })
    decision = gate(FakePlatform(), V2, CFG, HELD, [], [])
    assert decision.commit, decision.reasons


def test_gate_discards_on_persona_regression(monkeypatch):
    fake_runner(monkeypatch, {
        "v1": {"bob": {"passed": 0, "runs": 3}, "eve": {"passed": 3, "runs": 3}},
        "v2": {"bob": {"passed": 3, "runs": 3}, "eve": {"passed": 1, "runs": 3}},
    })
    decision = gate(FakePlatform(), V2, CFG, HELD, [], [])
    assert not decision.commit
    assert any("eve" in reason for reason in decision.reasons)


def test_gate_discards_on_unit_test_drop(monkeypatch):
    same = {"bob": {"passed": 3, "runs": 3}, "eve": {"passed": 3, "runs": 3}}
    fake_runner(monkeypatch, {"v1": same, "v2": same})
    platform = FakePlatform(unit_test_passes=lambda cfg, test: cfg.version_label == "v1")
    test = UnitTest(name="t", prefix_turns=[Turn(role="user", text="x")], expectation="e")
    decision = gate(platform, V2, CFG, HELD, [], [test])
    assert not decision.commit


def test_gate_rejects_train_personas(monkeypatch):
    fake_runner(monkeypatch, {})
    with pytest.raises(ValueError):
        gate(FakePlatform(), V2, CFG, [persona("bob", "train")], [], [])
