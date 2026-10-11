"""F9: a create_promise amount or date the model passed in words is read with the spoken-number helpers."""
import json
from pathlib import Path

from builder.template_cc import compiler
from builder.template_cc.apimodel import ApiModel
from builder.template_cc.compiler import runtime as R

from .helpers import after_setup_and_facts, run_pre

FIX = Path(__file__).resolve().parent / "fixtures"
NOW = "2031-03-05T10:00"  # a Wednesday in the fixture's calendar


def _compiled(features):
    pol = json.loads((FIX / "invented.policy.json").read_text())
    api = ApiModel.load(FIX / "invented.openapi.json")
    wf, _ = compiler.compile(pol, api, features=features)
    return wf, compiler.policy_check.complete(pol, api)


def test_runtime_helpers_match_the_research_module():
    assert R.amount_from_speech("four hundred and fifty-five") == (455.0, True)
    assert R.amount_from_speech("two hundred and ten, sorry, two twenty") == (220.0, True)
    assert R.date_from_speech("the twenty-second", "2026-10-14T11:00") == ("2026-10-22", True)
    assert R.date_from_speech("next Friday", "2026-10-14T11:00")[1] is True


def test_promise_pre_hook_reads_words_with_f9():
    wf, p = _compiled(frozenset({"f9_number_input"}))
    v = after_setup_and_facts(wf, p, NOW, 2)
    _, cfg = run_pre(wf, "negotiate", "create_promise", v,
                     {"item_ref": "q1", "amount_minor": "one hundred and thirty-seven pounds fifty", "pay_on": "the seventh"})
    assert cfg["body"]["amount_minor"] == 13750
    assert cfg["body"]["pay_on"] == "2031-03-07"


def test_promise_pre_hook_digits_unchanged_with_f9():
    wf, p = _compiled(frozenset({"f9_number_input"}))
    v = after_setup_and_facts(wf, p, NOW, 2)
    _, cfg = run_pre(wf, "negotiate", "create_promise", v, {"item_ref": "q1", "amount_minor": "137.50", "pay_on": "07.03.2031"})
    assert cfg["body"]["amount_minor"] == 13750 and cfg["body"]["pay_on"] == "2031-03-07"


def test_without_f9_the_hook_has_no_speech_helpers():
    wf, _ = _compiled(frozenset())
    code = json.dumps(wf)
    assert "amount_from_speech" not in code and "date_from_speech" not in code
