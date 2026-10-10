"""Section 4 core logic, offline: Pareto selection, the GEPA-lite loop with a fake runner, workflow graphs, lessons."""

import random
from types import SimpleNamespace as NS

import pytest

from agentforge.build.addons import render_rule
from agentforge.domain.collections import brief_dir, load_policy
from agentforge.optimize import aflow, gepa, lessons
from agentforge.platform.local import LocalPlatform
from agentforge.schemas import AgentConfig, Persona, RunResult, ScoredRun, ToolCallRecord, ToolDef, Verdict


def cand(cid, scores, rules=()):
    return gepa.Candidate(id=cid, rules=list(rules), pareto=scores)


def test_pareto_front_keeps_per_instance_winners_and_drops_dominated():
    a = cand("a", {"x": 1.0, "y": 0.0})
    b = cand("b", {"x": 0.0, "y": 1.0})
    c = cand("c", {"x": 0.5, "y": 0.5})  # best nowhere
    d = cand("d", {"x": 1.0, "y": 0.0})  # ties a
    front = {x.id for x in gepa.pareto_front([a, b, c, d])}
    assert front == {"a", "b", "d"}
    assert gepa.sample_parent([a, b, c], random.Random(0)).id in {"a", "b"}


def test_optimize_accepts_only_children_that_beat_the_parent_on_the_minibatch(tmp_path):
    instances = [f"b:{i}" for i in range(8)]
    state = gepa.start(instances, seed_rules=["r0"])

    def run(candidate, chosen):  # a rule learned on one case fixes every case of the same parity (it generalises)
        fixed = {int(r.split(":")[-1]) % 2 for r in candidate.rules if r.startswith("fix:")}
        rates = {i: 1.0 if int(i.split(":")[1]) % 2 in fixed else 0.0 for i in chosen}
        scored = [ScoredRun(run=RunResult(persona_name=i, agent_version=candidate.id), passed=bool(r), verdicts=[])
                  for i, r in rates.items()]
        return rates, scored

    def propose(parent, failures):
        return parent.rules + [f"fix:{failures[0].run.persona_name}"]

    state = gepa.optimize(state, run, budget=60, path=tmp_path / "s.json", minibatch=3, propose=propose)
    assert state.rollouts <= 60 and len(state.pool) > 1
    assert gepa.top(state.pool)[0].mean > state.pool[0].mean
    assert gepa.State.load(tmp_path / "s.json").iteration == state.iteration  # resumable


def test_rules_are_cleaned_and_rendered_with_brief_tool_names():
    rules = gepa.clean_rules(["  a ", "a", "", "x" * 999] + [f"r{i}" for i in range(20)])
    assert rules[0] == "a" and len(rules[1]) == gepa.MAX_RULE_CHARS and len(rules) == gepa.MAX_RULES
    assert render_rule("Söz için {log_promise_to_pay} çağır.", load_policy(brief_dir("trakya_oddformat"))) == "Söz için odeme_sozu_kaydet çağır."


def test_shapes_are_valid_and_bad_graphs_are_rejected():
    assert [g.name for g in aflow.shapes()] == ["single", "verify_collect", "verify_triage", "verify_collect_close"]
    with pytest.raises(ValueError):
        aflow.Graph(name="x", start="c", nodes=[aflow.Node(id="c", kind="condition", question="q")], edges=[])


def test_cursor_moves_through_verification_and_triage(monkeypatch):
    import agentforge.run.decision as decision

    monkeypatch.setattr(decision, "decide", lambda q, c: (q == aflow.TRIAGE, None))
    graph = aflow.shapes()[2]
    cfg = AgentConfig(version_label="v", system_prompt="base", first_message="m", model="m", workflow=graph.model_dump(),
                      tools=[ToolDef(name=n, description="d") for n in ("verify_identity", "get_account", "log_dispute", "log_promise_to_pay")])
    cursor = aflow.WorkflowCursor(cfg, lambda n: n)
    assert {t.name for t in cursor.node_config().tools} == {"verify_identity"}
    cursor.advance([ToolCallRecord(name="verify_identity", result={"verified": False})], "")
    assert cursor.current == "dogrulama"  # failed verification does not open the gate
    cursor.advance([ToolCallRecord(name="verify_identity", result={"verified": True})], "")
    cursor.advance([ToolCallRecord(name="get_account", result={"overdue_amount_tl": 1})], "")
    assert cursor.current == "yonlendirme" and "log_promise_to_pay" not in {t.name for t in cursor.node_config().tools}
    assert cursor.path == ["dogrulama", "tahsilat_ilk", "triage", "yonlendirme"]


def test_local_platform_runs_a_workflow(monkeypatch):
    from agentforge import llm
    import agentforge.run.decision as decision

    lines = iter(["8904, 1985-03-14", "Tamam [END]"])
    monkeypatch.setattr(llm, "call_llm", lambda *a, **k: next(lines))
    monkeypatch.setattr(decision, "decide", lambda q, c: (False, None))
    seen_tools = []

    class Client:
        def __init__(self):
            self.replies = [[("verify_identity", '{"tckn_last4": "8904", "birth_date": "1985-03-14"}')], None]
            self.chat = NS(completions=NS(create=self.create))

        def create(self, **kw):
            seen_tools.append({t["function"]["name"] for t in kw.get("tools") or []})
            calls = self.replies.pop(0) if self.replies else None
            tool_calls = [NS(id=f"c{i}", function=NS(name=n, arguments=a)) for i, (n, a) in enumerate(calls or [])]
            return NS(choices=[NS(message=NS(content=None if calls else "Doğrulandı.", tool_calls=tool_calls or None))],
                      usage=NS(prompt_tokens=1, completion_tokens=1))

    cfg = AgentConfig(version_label="v", system_prompt="base", first_message="m", model="openai:gpt-4o-mini",
                      workflow=aflow.shapes()[1].model_dump(),
                      tools=[ToolDef(name=n, description="d") for n in ("verify_identity", "get_account")])
    platform = LocalPlatform(run_tool=lambda s, n, a: {"verified": True}, client=Client(), agent_model="openai:gpt-4o-mini")
    run = platform.run_conversation(cfg, Persona(name="p", prompt="x", successCriteria="y"), 0)
    assert seen_tools[0] == {"verify_identity"}  # first node only offers verification
    assert run.raw["workflow_path"] == ["dogrulama", "tahsilat"]


def test_lessons_only_mine_recurring_failures():
    failed = lambda name, reason="code check": Verdict(check_name=name, passed=False, reason=reason)  # noqa: E731
    runs = [ScoredRun(run=RunResult(persona_name=f"b:{i}", agent_version="v"), passed=False,
                      verdicts=[failed("limit_stated"), failed("rule_1", "ERROR: judge failed")]) for i in range(3)]
    runs.append(ScoredRun(run=RunResult(persona_name="b:x", agent_version="v"), passed=False, verdicts=[failed("rare")]))
    assert list(lessons.recurring(runs, min_count=3)) == ["limit_stated"]
