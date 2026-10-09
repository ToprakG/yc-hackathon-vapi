import os

import pytest

from agentforge import llm
from agentforge.run import runner, scorer
from agentforge.run.runner import metrics, run_suite
from agentforge.schemas import Assertion, Persona, RunResult, ScoredRun, Turn, Verdict
from tests.fakes import FakePlatform

PERSONA = Persona(
    name="hasar_normal",
    prompt="Ben Ayşe Kaya. Dün park halindeyken arabama çarptılar. Hasar kaydı açtırmak istiyorum.",
    successCriteria=(
        "Agent calls verify_identity before get_policy, creates a claim with injury=false, "
        "and never reads back the full TCKN."
    ),
    tags=["train"],
)
ASSERTIONS = [
    Assertion.model_validate(
        {"name": "identity_first", "prompt": "verify_identity is called before get_policy.", "contextConfig": {"includeToolCalls": True}}
    ),
    Assertion(name="ai_disclosure", prompt="The agent says it is an AI assistant in its first turn."),
]


def make_run(lines, tool_calls=(), ended_reason="persona_end"):
    return RunResult(
        persona_name=PERSONA.name,
        agent_version="v1",
        transcript=[Turn(role=role, text=text, turn_idx=i) for i, (role, text) in enumerate(lines)],
        tool_calls=list(tool_calls),
        ended_reason=ended_reason,
        duration_s=60,
        cost_usd=0.1,
    )


CLEAR_PASS = make_run(
    [
        ("assistant", "Merhaba, ben yapay zeka asistanıyım. Kasko hasar ihbarı için yardımcı olabilirim."),
        ("user", "Merhaba, dün arabama çarptılar, hasar kaydı açmak istiyorum."),
        ("assistant", "Geçmiş olsun. Önce kimliğinizi doğrulayayım. TC kimlik numaranızın son dört hanesi nedir?"),
        ("user", "Dört beş altı yedi. Doğum tarihim on iki mart seksen beş."),
        ("assistant", "Teşekkürler, kimliğiniz doğrulandı. Poliçe numaranız nedir?"),
        ("user", "KSK 2024 004512."),
        ("assistant", "Yaralanan var mı?"),
        ("user", "Hayır, kimse yaralanmadı."),
        ("assistant", "Hasar kaydınız açıldı. Kayıt numaranız C, 1, 0, 0, 7. Başka bir konuda yardımcı olabilir miyim?"),
        ("user", "Hayır, teşekkürler. Hoşça kalın."),
    ],
    tool_calls=[
        {"name": "verify_identity", "args": {"tckn_last4": "4567", "birth_date": "1985-03-12"}, "result": {"ok": True}, "turn_idx": 4},
        {"name": "get_policy", "args": {"policy_number": "KSK-2024-004512"}, "result": {"ok": True}, "turn_idx": 6},
        {"name": "create_claim", "args": {"policy_number": "KSK-2024-004512", "injury": False}, "result": {"claim_id": "C1007"}, "turn_idx": 8},
    ],
)
CLEAR_FAIL = make_run(
    [
        ("assistant", "Merhaba, size nasıl yardımcı olabilirim?"),
        ("user", "Hasar kaydı açmak istiyorum. Poliçem KSK 2024 004512."),
        ("assistant", "Poliçenizde deprem dahil her şey teminat altında, TC numaranız 12345678901 kayıtlı."),
        ("user", "Tamam, teşekkürler."),
    ],
    tool_calls=[{"name": "get_policy", "args": {"policy_number": "KSK-2024-004512"}, "turn_idx": 2}],
)
AMBIGUOUS = make_run(
    [
        ("assistant", "Merhaba, ben dijital asistanınım. Nasıl yardımcı olabilirim?"),
        ("user", "Arabama çarptılar."),
        ("assistant", "Kimlik bilgilerinizi alabilir miyim?"),
        ("user", "Şu an bulamıyorum, sonra ararım."),
        ("assistant", "Tabii, iyi günler."),
    ]
)


class FakeJudge:
    def __init__(self, passed=True):
        self.calls = []
        self.passed = passed

    def __call__(self, system, user, model=None, json_schema=None, temperature=0.2, **_):
        self.calls.append({"user": user, "temperature": temperature, "schema": json_schema})
        return {"passed": self.passed, "reason": "ok", "evidence_turn": 2}


def test_verdict_wiring(monkeypatch):
    fake = FakeJudge()
    monkeypatch.setattr(llm, "call_llm", fake)
    scored = scorer.score_run(CLEAR_PASS, PERSONA, ASSERTIONS)
    assert [v.check_name for v in scored.verdicts] == ["successCriteria", "identity_first", "ai_disclosure"]
    assert scored.passed and all(v.evidence_turn == 2 for v in scored.verdicts)
    assert all(call["temperature"] == 0 and call["schema"] for call in fake.calls)
    assert "[0] assistant: Merhaba" in fake.calls[0]["user"]


def test_context_config_controls_tool_calls(monkeypatch):
    fake = FakeJudge()
    monkeypatch.setattr(llm, "call_llm", fake)
    scorer.score_run(CLEAR_PASS, PERSONA, ASSERTIONS)
    success, with_tools, without_tools = (call["user"] for call in fake.calls)
    assert "TOOL CALLS" in success and "verify_identity" in success
    assert "TOOL CALLS" in with_tools and "EXTRACTION EVENTS" not in with_tools
    assert "TOOL CALLS" not in without_tools


def test_evaluation_prompt_used(monkeypatch):
    fake = FakeJudge()
    monkeypatch.setattr(llm, "call_llm", fake)
    persona = PERSONA.model_copy(update={"evaluationPrompt": "Only judge the claim creation."})
    scorer.score_run(CLEAR_PASS, persona, [])
    assert fake.calls[0]["user"].startswith("Only judge the claim creation.")


def test_one_failed_check_fails_run(monkeypatch):
    answers = iter([True, False, True])
    monkeypatch.setattr(llm, "call_llm", lambda *a, **k: {"passed": next(answers), "reason": "", "evidence_turn": None})
    assert not scorer.score_run(CLEAR_PASS, PERSONA, ASSERTIONS).passed


def test_judge_exception_fails_check(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(llm, "call_llm", boom)
    scored = scorer.score_run(CLEAR_PASS, PERSONA, [])
    assert not scored.passed and scored.verdicts[0].reason.startswith("ERROR")


def test_error_run_fails_without_judge(monkeypatch):
    fake = FakeJudge()
    monkeypatch.setattr(llm, "call_llm", fake)
    scored = scorer.score_run(make_run([], ended_reason="error: timeout"), PERSONA, ASSERTIONS)
    assert not scored.passed and fake.calls == []


def scored_run(name, passed, check="successCriteria"):
    run = RunResult(persona_name=name, agent_version="v1", duration_s=30, cost_usd=None if passed else 0.5)
    return ScoredRun(run=run, verdicts=[Verdict(check_name=check, passed=passed)], passed=passed)


def test_metrics_pass_hat_3():
    scored = [scored_run("a", True)] * 3 + [scored_run("b", True), scored_run("b", True), scored_run("b", False)]
    scored += [scored_run("c", True)] * 3 + [scored_run("c", False)]  # C(3,3)/C(4,3) = 0.25
    m = metrics(scored)
    assert m["pass_rate"] == pytest.approx(8 / 10)
    assert m["pass_hat_3"] == pytest.approx((1 + 0 + 0.25) / 3)
    assert m["per_persona"]["b"] == {"passed": 2, "runs": 3}
    assert m["per_assertion_fail_counts"] == {"successCriteria": 2}
    assert m["total_cost"] == pytest.approx(1.0)
    assert m["total_minutes"] == pytest.approx(5.0)


def test_metrics_small_n():
    assert metrics([scored_run("a", True), scored_run("a", True)])["pass_hat_3"] == 1.0
    assert metrics([scored_run("a", True), scored_run("a", False)])["pass_hat_3"] == 0.0


class RaisingPlatform(FakePlatform):
    def run_conversation(self, cfg, persona, run_idx):
        if run_idx == 1:
            raise RuntimeError("vapi 500")
        return super().run_conversation(cfg, persona, run_idx)


def test_run_suite(monkeypatch, tmp_path):
    from agentforge.schemas import AgentConfig

    monkeypatch.setattr(runner, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(llm, "call_llm", FakeJudge())
    cfg = AgentConfig(version_label="v9", system_prompt="s", first_message="Merhaba", model="openai:gpt-4o-mini")
    other = PERSONA.model_copy(update={"name": "second"})
    scored = run_suite(RaisingPlatform(), cfg, [PERSONA, other], ASSERTIONS, runs_per_persona=3, concurrency=3)
    assert [(s.run.persona_name, s.run.run_idx) for s in scored] == [
        (p, i) for p in (PERSONA.name, "second") for i in range(3)
    ]
    errored = [s for s in scored if s.run.run_idx == 1]
    assert all(not s.passed and s.run.ended_reason.startswith("error") for s in errored)
    assert sum(s.passed for s in scored) == 4
    assert len((tmp_path / "v9" / "train.jsonl").read_text().splitlines()) == 6


@pytest.mark.skipif(
    not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")),
    reason="needs a judge provider key",
)
def test_live_judge_sanity():
    assert scorer.score_run(CLEAR_PASS, PERSONA, ASSERTIONS).passed
    assert not scorer.score_run(CLEAR_FAIL, PERSONA, ASSERTIONS).passed
    ambiguous = scorer.score_run(AMBIGUOUS, PERSONA, ASSERTIONS)
    print("ambiguous:", [(v.check_name, v.passed, v.reason) for v in ambiguous.verdicts])
    assert not ambiguous.passed  # no claim was created


def test_suite_stops_when_judge_is_broken():
    from agentforge.run.runner import check_judge_health

    broken = Verdict(check_name="successCriteria", passed=False, reason="ERROR: judge failed: no key")
    run = RunResult(persona_name="p", agent_version="v1")
    with pytest.raises(RuntimeError):
        check_judge_health([ScoredRun(run=run, verdicts=[broken], passed=False)])
    check_judge_health([ScoredRun(run=run, verdicts=[Verdict(check_name="x", passed=False, reason="no")], passed=False)])


def test_suite_stops_when_platform_is_broken():
    from agentforge.run.runner import check_judge_health

    run = RunResult(persona_name="p", agent_version="v1", ended_reason="error: POST /chat -> 402")
    verdict = Verdict(check_name="successCriteria", passed=False, reason="run failed")
    with pytest.raises(RuntimeError):
        check_judge_health([ScoredRun(run=run, verdicts=[verdict], passed=False)])
