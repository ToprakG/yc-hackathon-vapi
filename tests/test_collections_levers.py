"""Collections levers: briefs, template, self-check, gates, and the sign test."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge.build.best_of_k import ScoringBlocked, best_of_k
from agentforge.build.extract import extract
from agentforge.build.self_check import self_check
from agentforge.build.template import opener_text, render
from agentforge.build.variants import stage_order_ok
from agentforge.domain import load_domain
from agentforge.domain.collections.catalog import BRIEFS
from agentforge.experiments.sign_test import CRITICAL_TAGS, CaseScore, is_drop, is_win
from agentforge.schemas import Persona, UnitTest

DEBT_WORDS = ("debt", "amount", "creditor", "balance", "borç", "bakiye", "tutar", "alacak")
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", list(BRIEFS))
def test_briefs_load(name: str) -> None:
    task_md, tools = load_domain(f"collections/{name}")
    assert "Disclosure" in task_md
    assert tools
    assert "Ada Lovelace" not in task_md
    folder = ROOT / "agentforge" / "domain" / "collections" / name
    personas = [Persona.model_validate(item) for item in _json(folder / "personas.json")]
    tests = [UnitTest.model_validate(item) for item in _json(folder / "unit_tests.json")]
    assert {persona.name for persona in personas} >= {"third_party_spouse", "vague_promise", "dont_call"}
    assert {test.name for test in tests} == {"third_party", "vague_promise", "dont_call", "plan_outside_limits"}
    spouse = next(persona for persona in personas if persona.name == "third_party_spouse")
    assert "third_party" in spouse.tags
    assert "train" in spouse.tags


def test_renamed_template_uses_its_own_tool_names() -> None:
    policy, tools, config = _rendered("renamed")
    prompt = config.system_prompt
    assert "confirm_caller" in prompt
    assert "fetch_balance" in prompt
    assert "record_payment_pledge" in prompt
    for canonical in ("verify_identity", "get_account", "log_promise_to_pay", "schedule_callback"):
        assert canonical not in prompt
    assert [tool.name for tool in config.tools] == [tool.name for tool in tools]
    assert policy.tool_name("verify") == "confirm_caller"
    assert policy.tool_name("account") == "fetch_balance"
    required = {tool.name: tool.parameters["required"] for tool in tools}
    assert required["confirm_caller"] == ["national_id_suffix", "dob"]
    assert required["record_payment_pledge"] == ["due_on", "pledged_sum"]


def test_no_callback_brief_does_not_invent_a_tool() -> None:
    policy, tools, config = _rendered("no_callback")
    assert policy.roles["callback"] is None
    assert "callback" in policy.gaps
    assert "hard_cases" in policy.gaps
    assert "schedule_callback" not in config.system_prompt
    assert all(tool.name != "schedule_callback" for tool in tools)
    assert all(tool.name != "schedule_callback" for tool in config.tools)
    assert "no callback tool" in config.system_prompt


def test_template_names_verify_before_account() -> None:
    policy, _tools, config = _rendered("strict")
    verify = policy.tool_name("verify")
    account = policy.tool_name("account")
    assert verify == "verify_identity"
    assert account == "get_account"
    assert stage_order_ok(config.system_prompt, verify, account)
    assert "Role" in config.system_prompt
    assert config.system_prompt.index("## Stages") < config.system_prompt.index("## Hard rules")
    assert config.system_prompt.index("## Hard rules") < config.system_prompt.index("## Visible compliance")
    assert config.system_prompt.index("## Visible compliance") < config.system_prompt.index("## Hard cases")


def test_generic_opener_does_not_name_the_debt() -> None:
    for name in BRIEFS:
        policy, _tools, config = _rendered(name, opener="generic")
        lowered = config.first_message.lower()
        assert "Ada Lovelace" not in config.system_prompt
        assert not any(word in lowered for word in DEBT_WORDS)
        fixed = opener_text(policy, "fixed").lower()
        assert not any(word in fixed for word in DEBT_WORDS)


def test_self_check_default_asks_the_llm_client(monkeypatch: pytest.MonkeyPatch) -> None:
    policy, _tools, config = _rendered("strict")
    seen: list[str] = []

    def fake_call_llm(_system: str, user: str, **_kwargs):
        seen.append(user)
        rule = user.split("\n\nPrompt:", 1)[0].removeprefix("Rule:\n")
        return {"passes": rule != policy.rules[0]}

    monkeypatch.setattr("agentforge.llm.call_llm", fake_call_llm)
    repaired, gaps = self_check(policy, config, repair=True)
    assert len(seen) == len(policy.rules)
    assert gaps == [f"rule failed: {policy.rules[0]}"]
    assert repaired.system_prompt.count(policy.rules[0]) == config.system_prompt.count(policy.rules[0]) + 1


def test_self_check_repairs_a_limit_and_a_failed_rule() -> None:
    policy, _tools, config = _rendered("strict")
    broken = config.model_copy(update={"system_prompt": config.system_prompt.replace("250", "XXX")})
    failed_rule = policy.rules[0]

    def ask(rule: str, _prompt: str) -> bool:
        return rule != failed_rule

    repaired, gaps = self_check(policy, broken, repair=True, ask=ask)
    assert any("250" in gap for gap in gaps)
    assert f"rule failed: {failed_rule}" in gaps
    assert "The minimum payment is 250." in repaired.system_prompt
    assert repaired.system_prompt.count(failed_rule) == broken.system_prompt.count(failed_rule) + 1

    left, still = self_check(policy, broken, repair=False, ask=ask)
    assert "250" not in left.system_prompt
    assert still


def test_levers_cli_writes_configs_and_does_not_score_without_a_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agentforge.experiments.levers.RESULTS_DIR", tmp_path)
    monkeypatch.setattr("agentforge.llm.call_llm", lambda *_args, **_kwargs: {"passes": True})
    from agentforge.experiments.levers import main

    assert main(["collections/strict", "--score", "simulation", "--platform", "freya"]) == 2
    written = _json(tmp_path / "levers" / "strict.json")
    assert written["template_versus_one_call"] == "template"
    assert "template-fixed-rewritten" in written["variants"]
    assert "template-generic-raw" in written["variants"]
    assert not (tmp_path / "sim_fidelity.json").exists()
    assert not (tmp_path / "judge_agreement.json").exists()
    assert not (tmp_path / "ranking_agreement.json").exists()


def test_best_of_k_refuses_simulation_without_fidelity(tmp_path: Path) -> None:
    _policy, _tools, config = _rendered("strict")

    def score(_config) -> float:
        raise AssertionError("the scorer must not run without the fidelity file")

    with pytest.raises(ScoringBlocked, match="sim_fidelity.json"):
        best_of_k([config], score, kind="simulation", results_dir=tmp_path)


def test_sign_test_accepts_a_win_and_rejects_a_critical_drop() -> None:
    best = [_case(f"c{i}", 0) for i in range(10)]
    candidate = [_case(f"c{i}", 3) for i in range(10)]
    repeat = [_case(f"c{i}", 2) for i in range(10)]
    assert is_win(candidate, best, repeat)

    wide_best = [_case(f"c{i}", 0) for i in range(30)]
    wide_best += [_case(f"t{i}", 3, ("third_party",)) for i in range(8)]
    dropped = [_case(f"c{i}", 1) for i in range(30)]
    dropped += [_case(f"t{i}", 0, ("third_party",)) for i in range(8)]
    assert not is_win(dropped, wide_best, dropped)
    assert is_drop(
        [_case(f"t{i}", 0, ("third_party",)) for i in range(8)],
        [_case(f"t{i}", 3, ("third_party",)) for i in range(8)],
    )
    quiet = [_case(f"c{i}", 2) for i in range(10)]
    one_miss = quiet[:-1] + [_case("c9", 1)]
    assert not is_drop(one_miss, quiet)
    assert "promise_to_pay" in CRITICAL_TAGS


def _rendered(name: str, *, opener: str = "fixed"):
    task_md, tools = load_domain(f"collections/{name}")
    policy = extract(task_md, tools)
    config = render(policy, tools, opener=opener, model="openai:gpt-4o-mini")
    return policy, tools, config


def _case(case_id: str, passes: int, tags: tuple[str, ...] = ()) -> CaseScore:
    return CaseScore(case_id, passes, tags)


def _json(path: Path):
    import json

    return json.loads(path.read_text(encoding="utf-8"))
