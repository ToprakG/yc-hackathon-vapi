"""F1: no verify_identity call until the answer is complete."""
import json
from pathlib import Path

import pytest

from builder.template_cc import compiler
from builder.template_cc.apimodel import ApiModel
from builder.template_cc.compiler import runtime as R

from .helpers import call_vars, run_code, run_post

REPO = Path(__file__).resolve().parents[2]
GOLD = Path(__file__).resolve().parent / "golden"
F1 = frozenset({"f1_id_complete"})


@pytest.mark.parametrize("kind,text,value,complete", [
    ("digits:4", "double zero seven seven", "0077", True),
    ("digits:4", "five oh", "", False),
    ("digits:4", "five oh two three", "5023", True),
    ("digits:4", "1636, sorry, I mean 5023", "5023", True),
    ("digits:4", "it is four three two one", "4321", True),
    ("date", "the tenth of April", "", False),
    ("date", "the tenth of April, two thousand", "2000-04-10", True),
    ("date", "30/01/1984", "1984-01-30", True),
    ("date", "thirtieth of January nineteen eighty four", "1984-01-30", True),
    ("year", "nineteen sixty eight", "1968", True),
    ("year", "nineteen", "", False),
    ("alnum_code", "L S six, two H Q", "LS6 2HQ", True),
])
def test_answer_from_speech(kind, text, value, complete):
    got, ok = R.answer_from_speech(kind, text)
    assert ok == complete
    if complete:
        assert got == value


def test_kind_from_description():
    assert R.kind_from_description("phone_last4 For phone_last4: four digits.") == "digits:4"
    assert R.kind_from_description("date_of_birth the date as YYYY-MM-DD") == "date"


@pytest.fixture(scope="module")
def built():
    pol = json.loads((GOLD / "brief-a.policy.json").read_text())
    api = ApiModel.load(REPO / "tools" / "openapi.json")
    wf, _ = compiler.compile(pol, api, features=F1)
    return wf, pol, api


def test_compile_shape_and_lint(built):
    wf, pol, api = built
    n = wf["nodes"]
    assert not n["identity"].get("tools") and not n["identity_explain"].get("tools")
    assert {"id_check", "id_verify", "id_refusal_count"} <= set(n)
    assert n["identity"]["task_message"].startswith("You are speaking with the customer. Check identity first. Say exactly what this line asks")
    assert "{{id_say}}" in n["identity"]["task_message"]
    pre = n["id_verify"]["pre_actions"][0]
    assert pre["function"]["name"] == "verify_identity"
    body = pre["function"]["parameters"]["properties"]["body"]["properties"]
    assert {"{{id_send_field}}", "{{id_send_value}}"} <= {v.get("default") for v in body.values()}
    assert n["id_verify"]["node_type"] == "api_request" and n["id_verify"]["response_mapping"]
    assert compiler.lint(wf, pol, api)["errors"] == []


def _vars(wf, pol):
    v = run_code(wf, "setup", call_vars(pol, "2031-03-05T10:00"))
    assert v["id_q"] and v["id_say"] and v["id_intent"] == "none"
    return v


def test_id_check_partial_then_complete(built):
    wf, pol, _ = built
    v = _vars(wf, pol)
    v["id_q"] = "phone_last4"
    v.update(id_intent="answer", id_answer_text="five oh")
    out = run_code(wf, "id_check", v)
    assert out["id_partial"] == "five oh" and out["id_route"] == "ask" and out["id_intent"] == "none"
    assert out["id_answer_text"] == "" and out["id_say"]
    out.update(id_intent="answer", id_answer_text="two three")
    out = run_code(wf, "id_check", out)
    assert out["id_route"] == "send" and out["id_send_value"] == "5023" and out["id_send_field"] == "phone_last4"
    assert out["id_partial"] == ""


def test_id_check_date_and_empty(built):
    wf, pol, _ = built
    v = _vars(wf, pol)
    v.update(id_intent="answer", id_answer_text="the tenth of April, nineteen eighty")
    out = run_code(wf, "id_check", v)
    assert out["id_route"] == "send" and out["id_send_value"] == "1980-04-10"
    v = _vars(wf, pol)
    v.update(id_intent="answer", id_answer_text="")
    out = run_code(wf, "id_check", v)
    assert out["id_route"] == "ask" and out["id_say"] == pol["identity"]["prompts"][pol["identity"]["questions"][0]]


def test_id_verify_post_writes_say_and_next_question(built):
    wf, pol, _ = built
    v = _vars(wf, pol)
    qs = pol["identity"]["questions"]
    v["id_last_field"] = qs[0]
    data = {"ok": True, "verified": True, "all_verified": False, "wrong_answers_left": 3}
    out, _ = run_post(wf, "id_verify", "verify_identity", v, data)
    assert out["id_state"] == "next" and out["id_q"] == qs[1]
    assert pol["identity"]["prompts"][qs[1]] in out["id_say"] and "(field:" not in out["id_say"]
    data = {"ok": True, "verified": False, "all_verified": False, "wrong_answers_left": 2}
    out, _ = run_post(wf, "id_verify", "verify_identity", v, data)
    assert out["id_state"] == "retry" and "same question" in out["id_say"] and out["id_q"] == v["id_q"]
