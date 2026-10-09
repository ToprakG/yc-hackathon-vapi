"""Offline wiring test for the loop and the blind-set comparison.

LLM boxes are stubbed; split, runner, gate, unit-test bookkeeping and patch labels run for real.
"""

import json

import pytest

from agentforge.analyze import analyzer
from agentforge.build import builder
from agentforge.experiments import compare as compare_mod
from agentforge.loop import run_loop
from agentforge.patch import patcher
from agentforge.run import runner
from agentforge.schemas import (
    AgentConfig,
    Assertion,
    Bug,
    Evidence,
    FailureReport,
    Patch,
    Persona,
    ScoredRun,
    Verdict,
)
from agentforge.testgen import adversary, assertions, coverage, unit_tests
from tests.fakes import FakePlatform

RULE = "Kimlik doğrulamadan poliçe bilgisi verme."


def persona(name, group):
    return Persona(name=name, prompt=f"Ben {name}.", successCriteria="Agent verifies identity.", tags=[group, f"path:{name}"])


@pytest.fixture
def loop_env(tmp_path, monkeypatch):
    monkeypatch.setattr(run_loop, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(run_loop, "LOOP_LOG", tmp_path / "runs" / "loop_log.jsonl")
    monkeypatch.setattr(runner, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(unit_tests, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(run_loop, "load_domain", lambda domain: ("SOP", []))
    monkeypatch.setattr(run_loop, "persona_context", lambda domain, task_md: task_md)
    v1 = AgentConfig(version_label="v1", system_prompt="Sen bir sigorta asistanısın.", first_message="Merhaba", model="openai:x")
    monkeypatch.setattr(builder, "build_agent", lambda task_md, tools: v1)
    monkeypatch.setattr(assertions, "generate_assertions", lambda task_md: [Assertion(name="no_pii", prompt="No PII")])
    monkeypatch.setattr(coverage, "generate_coverage", lambda task_md, tools: [persona(f"cov{i}", "coverage") for i in range(4)])
    monkeypatch.setattr(adversary, "generate_adversary", lambda task_md, tools, cfg: [persona(f"adv{i}", "adversary") for i in range(3)])

    # The agent passes a run only once the rule is in its prompt.
    def score_run(run, persona, asserts):
        passed = run.agent_version != "v1" and "Kimlik" in run.raw.get("prompt", "")
        return ScoredRun(run=run, verdicts=[Verdict(check_name="successCriteria", passed=passed, evidence_turn=1)], passed=passed)

    platform = FakePlatform()
    original = platform.run_conversation

    def run_conversation(cfg, p, run_idx):
        result = original(cfg, p, run_idx)
        result.raw["prompt"] = cfg.system_prompt
        return result

    platform.run_conversation = run_conversation
    monkeypatch.setattr(runner, "score_run", score_run)

    def analyze(version, failed, personas):
        analyzer.require_split(failed, personas, "train")
        evidence = [Evidence(persona=s.run.persona_name, run_idx=s.run.run_idx, turn=1) for s in failed]
        return FailureReport(version=version, bugs=[Bug(bug_id="no-verify", description="d", generalized_rule=RULE, evidence=evidence)])

    monkeypatch.setattr(analyzer, "analyze", analyze)
    monkeypatch.setattr(unit_tests.llm, "call_llm", lambda *a, **k: {"tests": []})

    def surgical(cfg, report):
        patch = Patch(bug_id="no-verify", layer="prompt", operator="add_rule", after=RULE)
        return patcher.apply_patches(cfg, [patch])

    monkeypatch.setattr(patcher, "surgical", surgical)
    return platform, v1


def test_loop_commits_patch_and_logs(loop_env):
    platform, _ = loop_env
    best = run_loop.run_pipeline("kasko", platform, max_iters=2, runs_per_persona=1)

    assert best.version_label == "v2"
    assert best.parent_version == "v1"
    assert platform.promoted == ["v2"]
    assert RULE in best.system_prompt
    log = [json.loads(line) for line in run_loop.LOOP_LOG.read_text().splitlines()]
    assert [entry["decision"] for entry in log] == ["COMMIT", "STOP"]
    assert log[0]["candidate_version"] == "v2"
    assert log[0]["heldout_candidate_pass_rate"] == 1.0


def test_builder_mode_stops_at_v1(loop_env):
    platform, v1 = loop_env
    assert run_loop.run_pipeline("kasko", platform, mode="builder") == v1


def test_compare_marks_noise(loop_env, tmp_path, monkeypatch):
    platform, v1 = loop_env
    blind = [persona(f"blind{i}", "blind") for i in range(2)]
    monkeypatch.setattr(compare_mod, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(compare_mod, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(compare_mod, "load_blind", lambda domain_dir: (blind, [Assertion(name="no_pii", prompt="x")]))
    monkeypatch.setattr(compare_mod, "get_platform", lambda name: platform)
    monkeypatch.setattr(compare_mod, "load_noise", lambda: {"mean": 0.1, "stdev": 0.05})
    monkeypatch.setattr(compare_mod.builder, "build_agent", lambda task_md, tools: v1)
    monkeypatch.setattr(compare_mod, "load_domain", lambda domain: ("SOP", []))

    result = compare_mod.compare(["A", "B"], max_iters=1, runs=1)

    rows = result["variants"]
    assert rows["A"]["blind_pass_rate"] == 0.0
    assert rows["B"]["agent_version"] == "B-v2"
    assert rows["B"]["blind_pass_rate"] == 1.0
    assert rows["B"]["vs_A"] == {"delta": 1.0, "label": "above noise"}
    assert rows["B"]["committed"] == 1
    assert "above noise" in (tmp_path / "results" / "compare.md").read_text()
