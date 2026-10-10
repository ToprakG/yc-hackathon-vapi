"""Collections domain packs, mock backend, decision judge, paired statistics and the section-0 experiments; offline."""

import json

import pytest

from agentforge.domain.collections import (brief_dir, list_briefs, load_accounts, load_personas, load_policy,
                                           load_unit_tests)
from agentforge.domain.collections.__main__ import check
from agentforge.domain.collections.cases import CASES, CRITICAL_GROUPS, plan_offer
from agentforge.domain.collections.tools_server import CollectionsBackend, promise_violations
from agentforge.experiments import agreement as agreement_mod
from agentforge.experiments import ranking
from agentforge.platform.local import fill_variables, prefix_messages
from agentforge.run import decision
from agentforge.schemas import AgentConfig, Persona, RunResult, ToolCallRecord, Turn
from agentforge.stats import critical_veto, paired, sign_test, verdict, wilcoxon

TODAY = "2026-10-10"
NO_IS_GOOD = ("Before identity verification", "Did the agent threaten", "After the customer said")


def compliant_judge(question, context):
    """Stands in for the decision model: the agent did everything right."""
    return (not question.startswith(NO_IS_GOOD)), None


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setenv("COLLECTIONS_TODAY", TODAY)


# --- packs ------------------------------------------------------------------------------------------------------


def test_five_briefs_and_every_pack_is_consistent():
    briefs = list_briefs()
    assert len(briefs) >= 5
    for brief in briefs:
        assert check(brief) == [], brief


def test_pack_formats_differ_as_the_plan_asks():
    policies = {b: load_policy(brief_dir(b)) for b in list_briefs()}
    assert any(p.strict for p in policies.values())
    assert any(not p.allow_plans for p in policies.values())
    assert any(p.tool_names for p in policies.values())
    assert any("Bu" in (brief_dir(b) / "sop.md").read_text() or "ve" in (brief_dir(b) / "sop.md").read_text().split()
               for b in policies)  # at least one Turkish brief


def test_personas_cover_16_case_types_with_freya_tags_and_variables():
    personas = load_personas("marmara_standard")
    assert len(personas) == 16 == len(CASES)
    assert {p.tags[0] for p in personas} == {f"case:{c.key}" for c in CASES}
    critical = [p for p in personas if "critical" in p.tags]
    assert {t.split(":")[1] for p in critical for t in p.tags if t.startswith("group:")} == set(CRITICAL_GROUPS)
    assert all(p.variables["today"] == TODAY and p.variables["customer_name"] for p in personas)


def test_plan_offered_to_plan_personas_is_inside_every_brief_limit():
    for brief in list_briefs():
        policy, accounts = load_policy(brief_dir(brief)), load_accounts(brief)
        if not policy.allow_plans:
            continue
        account = accounts[1]
        n, first = plan_offer(policy, account)
        args = {"amount_tl": first, "date": "2026-10-11", "installments": n}
        assert promise_violations(policy, account, args, __import__("datetime").date(2026, 10, 10)) == [], brief


def test_unit_tests_use_the_brief_tool_names():
    tests = load_unit_tests("trakya_oddformat")
    assert len(tests) == 4
    names = {a.tool for t in tests for a in t.tool_assertions}
    assert names <= {"hesap_getir", "odeme_sozu_kaydet", "aranmasin_isaretle"}
    messages = prefix_messages(tests[1].prefix_turns)  # verified prefix: tool calls paired with results
    assert [m["role"] for m in messages].count("tool") == 2


# --- mock backend -----------------------------------------------------------------------------------------------


def _verify(backend, session, account):
    return backend.run_tool(session, backend.policy.tool("verify_identity"),
                            {"tckn_last4": account["tckn"][-4:], "birth_date": account["birth_date"]})


def test_backend_needs_verification_and_enforces_limits():
    backend = CollectionsBackend("marmara_standard")
    account = backend.accounts[3]  # 27,500 TL overdue
    assert "error" in backend.run_tool("s", "get_account", {"account_id": account["account_id"]})
    assert _verify(backend, "s", account)["verified"]
    assert backend.run_tool("s", "get_account", {"account_id": account["account_id"]})["overdue_amount_tl"] == 27500.0
    bad = backend.run_tool("s", "log_promise_to_pay", {"account_id": account["account_id"], "amount_tl": 0,
                                                      "date": "2026-11-30", "installments": 12})
    assert bad["logged"] is False and len(bad["violations"]) >= 3
    good = backend.run_tool("s", "log_promise_to_pay", {"account_id": account["account_id"], "amount_tl": 5500,
                                                       "date": "2026-10-15", "installments": 6})
    assert good["logged"] is True


def test_backend_no_plan_bank_and_renamed_tools():
    noplan = CollectionsBackend("karadeniz_noplan")
    account = noplan.accounts[0]
    _verify(noplan, "s", account)
    result = noplan.run_tool("s", "log_promise_to_pay", {"account_id": account["account_id"], "amount_tl": 1000,
                                                        "date": "2026-10-12", "installments": 2})
    assert "payment plans are not allowed" in result["violations"]
    renamed = CollectionsBackend("trakya_oddformat")
    assert _verify(renamed, "t", renamed.accounts[0])["verified"]
    assert "overdue_amount_tl" in renamed.run_tool("t", "hesap_getir", {"account_id": renamed.accounts[0]["account_id"]})


def test_backend_caps_verification_attempts():
    backend = CollectionsBackend("ege_strict")
    for _ in range(backend.policy.max_verification_attempts):
        backend.run_tool("s", "verify_identity", {"tckn_last4": "0000", "birth_date": "1990-01-01"})
    account = backend.accounts[0]
    assert _verify(backend, "s", account)["verified"] is False


# --- statistics -------------------------------------------------------------------------------------------------


def test_sign_test_matches_the_numbers_in_the_plan_review():
    assert sign_test(7, 1) == pytest.approx(0.0703, abs=1e-4)
    assert sign_test(6, 2) == pytest.approx(0.2891, abs=1e-4)
    assert sign_test(0, 0) == 1.0


def test_wilcoxon_exact_and_ties():
    assert wilcoxon([1, 1, 1, 1, 1]) == pytest.approx(2 / 32)
    assert wilcoxon([0, 0, 0]) == 1.0
    assert wilcoxon([1, -1]) == 1.0


def test_paired_ignores_ties_and_veto_blocks_critical_collapse():
    a = {"x": (3, 3), "y": (0, 3), "z": (1, 3), "c": (3, 3)}
    b = {"x": (3, 3), "y": (3, 3), "z": (3, 3), "c": (0, 3)}
    result = paired(a, b)
    assert (result.wins, result.losses, result.ties) == (2, 1, 1)
    veto = critical_veto(a, b, {"c": "third_party", "x": "routing", "y": "promise", "z": "promise"}, CRITICAL_GROUPS)
    assert veto and verdict(result, veto) == "loss"


# --- decision judge ---------------------------------------------------------------------------------------------


def _run(persona, calls, texts=("Merhaba, yapay zeka asistanıyım.",)):
    transcript = [Turn(role="assistant", text=t, turn_idx=i) for i, t in enumerate(texts)]
    return RunResult(persona_name=persona.name, agent_version="v", transcript=transcript, tool_calls=calls, ended_reason="caller-ended")


def test_code_checks_read_the_tool_log(monkeypatch):
    monkeypatch.setattr(decision, "decide", compliant_judge)
    policy = load_policy(brief_dir("marmara_standard"))
    persona = next(p for p in load_personas("marmara_standard") if p.name.endswith(":full_payment"))
    account = next(a for a in load_accounts("marmara_standard") if a["account_id"] == persona.variables["account_id"])
    verify = ToolCallRecord(name="verify_identity", args={}, result={"verified": True}, turn_idx=2)
    read = ToolCallRecord(name="get_account", args={}, result={"overdue_amount_tl": account["overdue_amount_tl"]}, turn_idx=3)
    promise = ToolCallRecord(name="log_promise_to_pay", result={"logged": True}, turn_idx=5,
                             args={"amount_tl": account["overdue_amount_tl"], "date": "2026-10-12", "installments": 1})
    good = decision.score_decisions(_run(persona, [verify, read, promise]), persona, policy)
    assert good.passed, [v for v in good.verdicts if not v.passed]

    early = read.model_copy(update={"turn_idx": 1})
    over = promise.model_copy(update={"args": {"amount_tl": 10, "date": "2026-12-30", "installments": 24}})
    bad = decision.score_decisions(_run(persona, [early, verify, over]), persona, policy)
    failed = {v.check_name for v in bad.verdicts if not v.passed}
    assert {"account_read_after_verification", "promises_within_limits"} <= failed


def test_amount_spoken_before_verification_is_caught(monkeypatch):
    monkeypatch.setattr(decision, "decide", compliant_judge)
    policy = load_policy(brief_dir("marmara_standard"))
    persona = next(p for p in load_personas("marmara_standard") if p.name.endswith(":third_party"))
    whole = persona.variables["overdue_amount_tl"].split(".")[0]
    run = _run(persona, [], texts=("Merhaba.", f"Eşinizin {int(whole):,} TL borcu var.".replace(",", ".")))
    verdicts = {v.check_name: v.passed for v in decision.score_decisions(run, persona, policy).verdicts}
    assert verdicts["amount_not_spoken_before_verification"] is False


def test_llm_failure_counts_as_a_judge_error(monkeypatch):
    monkeypatch.setattr(decision, "decide", lambda q, c: (None, None))
    policy = load_policy(brief_dir("ege_strict"))
    persona = load_personas("ege_strict")[0]
    scored = decision.score_decisions(_run(persona, []), persona, policy)
    assert not scored.passed and any(v.reason.startswith("ERROR: judge failed") for v in scored.verdicts)


# --- agreement and ranking --------------------------------------------------------------------------------------


def test_freya_verdict_shapes_and_branch():
    assert agreement_mod.freya_verdict({"freya_close": {"successCriteriaResult": {"passed": True},
                                                        "assertionResults": [{"result": "pass"}]}}) is True
    assert agreement_mod.freya_verdict({"freya_close": {"successCriteriaResult": "fail"}}) is False
    assert agreement_mod.freya_verdict({}) is None
    pairs = [(g, True, True) for g in CRITICAL_GROUPS for _ in range(9)] + [("promise", True, False)]
    stats = agreement_mod.agreement(pairs)
    assert stats["local_lenient"] == 1 and agreement_mod.branch(stats) == "local+gepa"
    stats = agreement_mod.agreement(pairs + [("third_party", False, True)] * 3)
    assert agreement_mod.branch(stats) == "fallback"


def test_ranking_counts_only_pairs_freya_separates():
    clear = {"A": {f"c{i}": [0, 3] for i in range(8)}, "B": {f"c{i}": [3, 3] for i in range(8)}}
    noise = {"A": {"c0": [1, 3]}, "B": {"c0": [2, 3]}}
    pairs = [{"name": f"p{i}", "unit": {"A": 0.2, "B": 0.8}, "freya": clear} for i in range(8)]
    pairs.append({"name": "noise", "unit": {"A": 0.9, "B": 0.1}, "freya": noise})
    result = ranking.check(pairs)
    assert result["clear_pairs"] == 8 and result["agreement"] == 1.0
    assert result["decision"].startswith("unit tests screen")


# --- platform plumbing ------------------------------------------------------------------------------------------


def test_variables_fill_like_freya():
    assert fill_variables("Merhaba {{customer_name}}, {{ unknown }}", {"customer_name": "Ayşe"}) == "Merhaba Ayşe, {{ unknown }}"


def test_freya_bodies_carry_customer_variables():
    from agentforge.platform.freya import FreyaPlatform

    platform = FreyaPlatform(client=object(), api_key="k", base_url="https://x", workspace_id="ws", sleep=lambda s: None)
    test = load_unit_tests("marmara_standard")[0]
    body = platform.unit_test_body(test, "ver-1")
    assert body["input"]["customerVariables"]["customer_name"]
    assert body["assertions"][0]["type"] == "tool_call"


# --- experiments end to end with a scripted platform -----------------------------------------------------------


class ScriptedCollections:
    """Agent B fixes the vague-promise case; everything else behaves the same for A and B."""

    def __init__(self, brief):
        self.brief = brief

    def run_conversation(self, cfg, persona, run_idx):
        calls = []
        if persona.name.endswith(":vague_promise") and cfg.version_label == "A":
            calls = [ToolCallRecord(name="verify_identity", result={"verified": True}, turn_idx=1),
                     ToolCallRecord(name="log_promise_to_pay", result={"logged": True}, turn_idx=2,
                                    args={"amount_tl": 1, "date": TODAY, "installments": 1})]
        return _run(persona, calls)


@pytest.fixture
def scripted(monkeypatch, tmp_path):
    from agentforge.experiments import col_common

    monkeypatch.setattr(col_common, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(col_common, "get_platform", lambda name, brief=None: ScriptedCollections(brief))
    monkeypatch.setattr("agentforge.run.runner.RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(decision, "decide", compliant_judge)
    for label in ("A", "B"):
        cfg = AgentConfig(version_label=label, system_prompt=f"x-{label}", first_message="y", model="m")
        (tmp_path / f"{label}.json").write_text(cfg.model_dump_json())
        for brief in list_briefs():  # a builder change gives every brief its own agent
            (tmp_path / brief).mkdir(exist_ok=True)
            (tmp_path / brief / f"{label}.json").write_text(cfg.model_dump_json())
    return tmp_path


def test_baseline_caches_and_splits_cases(scripted):
    from agentforge.experiments import baseline

    first = baseline.main(["--brief", "marmara_standard", "--agent", str(scripted / "A.json"), "--repeats", "2", "--runs", "1"])
    assert "marmara_standard:vague_promise" in first["always_fail"]
    assert "marmara_standard:vague_promise" in first["dev_set"]
    assert first["regression_set"] and set(first["dev_set"]).isdisjoint(first["regression_set"])
    again = baseline.main(["--brief", "marmara_standard", "--agent", str(scripted / "A.json"), "--repeats", "2", "--runs", "1"])
    assert again["cache_key"] == first["cache_key"]


def test_paired_gate_runs_practice_and_fakes(scripted):
    from agentforge.experiments import paired as paired_mod

    summary = paired_mod.main(["--best", str(scripted / "{brief}" / "A.json"), "--candidate", str(scripted / "{brief}" / "B.json"),
                               "--practice", "marmara_standard", "--runs", "3"])
    practice = summary["practice"]
    assert practice["paired"]["wins"] == 1 and practice["paired"]["losses"] == 0
    assert practice["verdict"] == "equal"  # one fixed case is not enough evidence at p < 0.1
    assert summary["accepted"] and not summary["win"]
    assert len(summary["fakes"]) == 4
    assert json.loads(next(scripted.rglob("paired_vs_A.json")).read_text())["candidate"] == "B"


def test_paired_without_per_brief_agents_is_not_accepted(scripted):
    from agentforge.experiments import paired as paired_mod

    summary = paired_mod.main(["--best", str(scripted / "A.json"), "--candidate", str(scripted / "B.json"),
                               "--practice", "marmara_standard", "--runs", "1"])
    assert not summary["fakes"] and not summary["accepted"]
    assert summary["decision"] == "not accepted: fewer than 3 fake briefs tested"


def test_persona_upload_drops_variables():
    persona = Persona(name="n", prompt="p", successCriteria="s", variables={"a": "b"})
    assert "variables" not in persona.model_dump(exclude_none=True, exclude={"variables"})
