"""Section 2 (behaviour bundle, bisection, one-at-a-time tests) with a scripted agent; offline."""

import json

import pytest

from agentforge.build import addons
from agentforge.build.builder import builder_system
from agentforge.domain.collections import brief_dir, load_accounts, load_policy
from agentforge.domain.collections.cases import case_of
from agentforge.experiments import section2
from agentforge.run import decision
from agentforge.schemas import AgentConfig, RunResult, ScoredRun, ToolCallRecord, Turn, Verdict

TODAY = "2026-10-10"
NO_IS_GOOD = ("Before identity verification", "Did the agent threaten", "After the customer said")
FORGETS_TO_LOG = {"full_payment", "dispute", "already_paid", "do_not_call", "callback_request", "wrong_number"}


def compliant_judge(question, context):
    return (not question.startswith(NO_IS_GOOD)), None


class AddonAwareAgent:
    """Does everything right, except: without say_and_log it forgets to log in six cases; with short_turns it reads
    the account for the spouse (a critical failure)."""

    def __init__(self, brief):
        self.brief = brief
        self.policy = load_policy(brief_dir(brief))
        self.accounts = {a["account_id"]: a for a in load_accounts(brief)}

    def run_conversation(self, cfg, persona, run_idx):
        p, case = self.policy, case_of(persona.name)
        has = lambda key: addons.ADDONS[key].text(p) in cfg.system_prompt  # noqa: E731
        account = self.accounts[persona.variables["account_id"]]
        calls = []
        wanted = case.must_call(p)
        if case.key in FORGETS_TO_LOG and not has("say_and_log"):
            wanted = []
        if case.key == "third_party" and has("short_turns"):
            calls.append(ToolCallRecord(name=p.tool("get_account"), result={"overdue_amount_tl": 1}, turn_idx=1))
        for i, name in enumerate(wanted, start=2):
            args = {"amount_tl": account["overdue_amount_tl"], "date": TODAY, "installments": 1} if name == "log_promise_to_pay" else {}
            result = {"verified": True} if name == "verify_identity" else {"logged": True}
            calls.append(ToolCallRecord(name=p.tool(name), args=args, result=result, turn_idx=i))
        transcript = [Turn(role="assistant", text="Merhaba, yapay zeka asistanıyım.", turn_idx=0)]
        return RunResult(persona_name=persona.name, agent_version=cfg.version_label, run_idx=run_idx,
                         transcript=transcript, tool_calls=calls, ended_reason="caller-ended")


@pytest.fixture
def lab(monkeypatch, tmp_path):
    from agentforge.experiments import col_common

    monkeypatch.setenv("COLLECTIONS_TODAY", TODAY)
    monkeypatch.setattr(col_common, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(col_common, "get_platform", lambda name, brief=None: AddonAwareAgent(brief))
    monkeypatch.setattr("agentforge.run.runner.RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(section2, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(addons, "LOCKED_PATH", tmp_path / "locked.json")
    monkeypatch.setattr(decision, "decide", compliant_judge)
    briefs = ["marmara_standard", "ege_strict", "anadolu_tr", "karadeniz_noplan", "trakya_oddformat"]
    for brief in briefs:
        cfg = AgentConfig(version_label=f"col-{brief}-v1", system_prompt="Sen bir tahsilat asistanısın.", first_message="Merhaba", model="m")
        path = tmp_path / "runs" / cfg.version_label / "agent.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cfg.model_dump_json())
    return tmp_path


def test_addons_render_with_the_brief_tool_names_and_limits():
    policy = load_policy(brief_dir("trakya_oddformat"))
    text = addons.render(policy, ["closing_checklist", "limits_sentence"])
    assert "odeme_sozu_kaydet" in text and "log_promise_to_pay" not in text
    assert "12 taksit" in text and "250 TL" in text
    noplan = load_policy(brief_dir("karadeniz_noplan"))
    assert "taksit yok" in addons.ADDONS["limits_sentence"].text(noplan)
    cfg = AgentConfig(version_label="v1", system_prompt="x" * 100, first_message="y", model="m")
    variant = addons.apply_addons(cfg, policy, ["short_turns"])
    assert variant.parent_version == "v1" and variant.version_label == "v1+short_turns"
    assert addons.growth(cfg, policy, "examples") > 0.3


def test_builder_options_change_only_what_they_name():
    assert builder_system() == builder_system("tr", None)
    assert "in English" in builder_system("en") and "conservatively" in builder_system(reading="conservative")


def test_lock_keeps_order_and_dedupes(tmp_path):
    path = tmp_path / "locked.json"
    addons.lock(["say_and_log"], "a", path)
    assert addons.lock(["short_turns", "say_and_log", "bogus"], "b", path) == ["say_and_log", "short_turns"]
    addons.lock_builder_option("reading", "conservative", "c", path)
    assert addons.load_builder_options(path) == {"reading": "conservative"}


def test_failure_clusters_pick_the_items_that_target_them():
    failed = lambda name: Verdict(check_name=name, passed=False, reason="code check")  # noqa: E731
    runs = [ScoredRun(run=RunResult(persona_name="b:vague_promise", agent_version="v"), passed=False,
                      verdicts=[failed("specific_date_and_amount_asked"), failed("forbidden_tools_not_called")])] * 3
    clusters = section2.failure_clusters(runs)
    assert clusters["top"][0]["fails"] == 3 and clusters["top"][0]["cases"] == {"vague_promise": 3}
    assert section2.choose_items(clusters) == ["confirm_then_call"]
    assert section2.choose_items({"runs": 0, "top": []}) == addons.P1


def test_find_culprit_bisects_to_the_breaking_item():
    def evaluate(keys):
        bad = "short_turns" in keys
        return {"verdict": "loss" if bad else "equal", "paired": {"mean_diff": -0.3 if bad else 0.0, "p": 0.05}}

    culprit, trace = section2.find_culprit(list(addons.P1), evaluate)
    assert culprit == ["short_turns"] and len(trace) == 6


def test_p1_loss_bisects_drops_the_culprit_and_locks_the_rest(lab):
    result = section2.main(["p1", "--best", str(lab / "runs" / "col-{brief}-v1" / "agent.json"),
                            "--practice", "marmara_standard", "--items", "all"])
    assert result["p1"]["practice"]["verdict"] == "loss" and result["p1"]["practice"]["veto"]
    assert result["harmful"] == ["short_turns"]
    assert result["next_gate"]["win"], result["next_gate"]["decision"]
    locked = json.loads((lab / "locked.json").read_text())["addons"]
    assert "short_turns" not in locked and "say_and_log" in locked


def test_single_test_without_effect_locks_nothing(lab):
    result = section2.main(["single", "--test", "T2.4", "--best", str(lab / "runs" / "col-{brief}-v1" / "agent.json"),
                            "--practice", "marmara_standard"])
    assert result["gate"]["practice"]["verdict"] == "equal" and result["locked"] is None
    assert not (lab / "locked.json").exists()


# --- offline checks of the add-ons against the briefs -----------------------------------------------------------


def test_addons_never_contradict_a_brief():
    karadeniz, anadolu, ege = (load_policy(brief_dir(b)) for b in ("karadeniz_noplan", "anadolu_tr", "ege_strict"))
    assert addons.ADDONS["plan_first"].skip(karadeniz) and addons.ADDONS["plan_first"].skip(anadolu)  # order fixed / no plans
    assert "küçük ilk ödemeli planı" in addons.ADDONS["route_and_end"].text(anadolu)  # hardship -> plan in anadolu
    assert "pazarlığı yapma" in addons.ADDONS["no_fake_confirmation"].text(karadeniz)
    assert "kelimesi kelimesine" in addons.ADDONS["short_turns"].text(ege)
    assert "3 gün" in addons.ADDONS["limits_sentence"].text(anadolu)
    assert "tamamını" in addons.ADDONS["examples"].text(karadeniz) and "bin lira" not in addons.ADDONS["examples"].text(karadeniz)


def test_only_skipped_addons_leave_the_prompt_unchanged():
    policy = load_policy(brief_dir("marmara_standard"))
    cfg = AgentConfig(version_label="v1", system_prompt="base", first_message="m", model="m")
    same = addons.apply_addons(cfg, policy, ["plan_first"], label="v1+plan_first")
    assert same.system_prompt == "base" and same.version_label == "v1+plan_first"
    assert addons.render(policy, ["plan_first", "short_turns"]).count("\n- ") == 1


def test_discount_window_is_enforced():
    import datetime

    from agentforge.domain.collections.tools_server import promise_violations

    policy, account = load_policy(brief_dir("anadolu_tr")), {"overdue_amount_tl": 1000.0}
    on = datetime.date(2026, 10, 10)
    assert promise_violations(policy, account, {"amount_tl": 900, "date": "2026-10-12", "installments": 1, "discount_pct": 10}, on) == []
    late = promise_violations(policy, account, {"amount_tl": 900, "date": "2026-10-18", "installments": 1, "discount_pct": 10}, on)
    assert late == ["discount only if paid within 3 days"]


def test_gate_does_not_run_briefs_where_nothing_changes(lab):
    result = section2.main(["single", "--test", "T2.2", "--best", str(lab / "runs" / "col-{brief}-v1" / "agent.json"),
                            "--practice", "marmara_standard"])
    assert result["gate"]["decision"].startswith("nothing to test") and result["locked"] is None
    assert not list((lab / "runs").glob("**/marmara_standard_ab_*.jsonl"))


def test_dry_run_plan_needs_no_model(lab, monkeypatch):
    monkeypatch.setattr("agentforge.llm.call_llm", lambda *a, **k: pytest.fail("plan must not call a model"))
    result = section2.main(["plan", "--practice", "marmara_standard", "--best", str(lab / "runs" / "col-{brief}-v1" / "agent.json")])
    assert not result["tests"]["T2.2"]["decidable"] and result["tests"]["P1"]["decidable"]
    assert result["tests"]["T2.3"]["conversations"][0] == 5 * 2 * 5 * 3  # 5 briefs, 2 arms, 5 promise cases, 3 runs
    assert result["addons"]["marmara_standard"]["examples"]["growth"] > 1  # vs the 39-char stand-in prompt
