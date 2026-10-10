"""F11: the model never fills create_promise; code validates what was said, the customer confirms a read-back."""
import json
from pathlib import Path

import pytest

from builder.template_cc import compiler
from builder.template_cc.apimodel import ApiModel

from .helpers import after_setup_and_facts, run_code, run_post

REPO = Path(__file__).resolve().parents[2]
GOLD = Path(__file__).resolve().parent / "golden"
FEATS = "f1,f2,f3,f4,f9,f11"
NOW = "2031-03-05T10:00"  # a Wednesday


def build(name="brief-a", api_path=None, features=FEATS):
    pol = json.loads((GOLD / f"{name}.policy.json").read_text())
    api = ApiModel.load(api_path or (REPO / "tools" / "openapi.json"))
    wf, _ = compiler.compile(pol, api, features=features)
    return wf, pol, api


@pytest.fixture(scope="module")
def a():
    wf, pol, api = build()
    return wf, pol, api, after_setup_and_facts(wf, pol, NOW, 1)


def check(wf, v, amount, date, intent="proposes"):
    return run_code(wf, "promise_check", dict(v, offer_intent=intent, offer_amount_text=amount, offer_date_text=date))


def test_shape_no_model_facing_promise_tool_and_lint(a):
    wf, pol, api, _ = a
    for nid in ("negotiate", "negotiate_resume"):
        assert not wf["nodes"][nid].get("tools")
        assert any(t["target_node"] == "promise_check" for t in wf["nodes"][nid]["transitions"])
    assert {"promise_check", "promise_confirm", "promise_write", "after_promise"} <= set(wf["nodes"])
    pw = wf["nodes"]["promise_write"]
    body = pw["pre_actions"][0]["function"]["parameters"]["properties"]["body"]["properties"]
    assert {"{{rb_pid}}", "{{rb_amount}}", "{{rb_date}}"} <= {x.get("default") for x in body.values()}
    assert pw["response_mapping"]
    assert compiler.lint(wf, pol, api)["errors"] == []
    ext = {e["name"]: e.get("enum_values") for e in wf["nodes"]["promise_confirm"]["extraction_schema"]}
    assert ext["rb_answer"] == ["yes", "no", "change", "other"]


def test_valid_words_go_to_a_read_back(a):
    wf, pol, _, v = a
    o = check(wf, v, "three hundred", "Friday the seventh of March")
    assert o["cp_route"] == "confirm" and o["rb_pid"] == "p1" and o["rb_date"] == "2031-03-07" and float(o["rb_amount"]) == 300.0
    assert "300" in o["say_line"] and "7 March" in o["say_line"] and "(2031" not in o["say_line"]
    assert o["offer_intent"] == "none" and o["offer_amount_text"] == "" and o["rb_answer"] == "other"
    o = check(wf, v, "", "the sixth of March", "accepts_offer")  # accepted without an amount: the full amount was asked
    assert o["cp_route"] == "confirm" and float(o["rb_amount"]) == 412.5


def test_cents_are_sent_as_integers():
    wf, pol, api = build("f3-kestrel", REPO / "testbed/fake_briefs/f3-kestrel/tools.openapi.json")
    v = after_setup_and_facts(wf, pol, NOW, 1)
    o = check(wf, v, "one hundred and fifty", "tomorrow")
    if o["cp_route"] == "confirm":
        assert o["rb_amount"] == "15000"


@pytest.mark.parametrize("amount,date,needle", [
    ("one hundred", "the sixth of March", "cannot record less than"),
    ("nine hundred", "the sixth of March", "cannot record more than"),
    ("three hundred", "the eighth of March", "not a business day"),  # a Saturday
    ("three hundred", "the first of April", "latest date I can record"),
])
def test_invalid_terms_come_back_with_a_reason(a, amount, date, needle):
    wf, _, _, v = a
    o = check(wf, v, amount, date)
    assert o["cp_route"] == "back" and needle in o["say_line"] and not o.get("rb_amount")
    assert o["offer_intent"] == "none"


def test_a_vague_day_is_asked_once_then_the_latest_date_is_offered(a):
    wf, pol, _, v = a
    o = check(wf, v, "three hundred", "")
    assert o["cp_route"] == "back" and "which day" in o["say_line"].lower()
    n = int(pol["ask_limits"].get("vague_date", 1))
    for _ in range(n):
        o = check(wf, o, "three hundred", "")
    assert "latest date I can record" in o["say_line"]


def test_confirm_routes_and_write_node(a):
    wf, _, _, v = a
    tr = {t["target_node"]: t["condition"]["conditions"][0]["operand"] for t in wf["nodes"]["promise_confirm"]["transitions"]
          if t["condition"].get("conditions") and t["condition"]["conditions"][0]["variable"] == "rb_answer"}
    assert tr == {"promise_write": "yes", "promise_check": "change", "negotiate_resume": "no"}
    assert wf["nodes"]["promise_confirm"]["on_enter"]["text"] == "{{say_line}}"


def test_post_hook_recorded_retry_then_failed(a):
    wf, _, _, v = a
    v = dict(v, rb_pid="p1")
    out, _ = run_post(wf, "promise_write", "create_promise", v, {"ok": True, "promise_id": "pr1"})
    assert out["cp_state"] == "recorded" and out["say_line"] and out["promises_n"] == "1"
    assert json.loads(out["pstate"])["p1"] == "promised"
    bad = {"ok": False}
    out, _ = run_post(wf, "promise_write", "create_promise", v, bad)
    assert out["cp_state"] == "retry"
    out, _ = run_post(wf, "promise_write", "create_promise", out, bad)
    assert out["cp_state"] == "failed" and "technical problem" in out["say_line"] and "recorded" not in out["say_line"].lower()
    assert json.loads(out["pstate"])["p1"] != "promised"
    out2 = run_code(wf, "after_promise", out)
    assert out2["neg_state"] in ("open", "done")


def test_every_reset_value_is_inside_its_enum(a):
    wf, _, _, _ = a
    import re
    enums = {}
    for n in wf["nodes"].values():
        for e in n.get("extraction_schema") or []:
            if e.get("enum_values"):
                enums.setdefault(e["name"], set()).update(e["enum_values"])
    for nid in ("setup", "promise_check", "human_back", "side_mark", "hardship_mark", "discount_reply", "id_check", "id_refusal_count"):
        node = wf["nodes"].get(nid)
        if not node:
            continue
        code = node["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
        for var, val in re.findall(r"vars\['(\w+)'\] = '([^']*)'", code):
            if var in enums and var != "id_answer_text":
                assert val in enums[var], (nid, var, val)


def test_multi_product_resets_side_product_inside_its_enum():
    import re
    pol = json.loads((GOLD / "brief-b.policy.json").read_text())
    assert pol.get("multi_product")
    api = ApiModel.load(REPO / "tools" / "openapi.json")
    wf, _ = compiler.compile(pol, api, features=FEATS)
    enum = next(e["enum_values"] for e in wf["nodes"]["negotiate"]["extraction_schema"] if e["name"] == "side_product")
    assert "none" in enum
    for nid in ("setup", "side_mark", "hardship_mark", "stop_count", "discount_reply", "resume"):
        code = wf["nodes"][nid]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
        for val in re.findall(r"vars\['side_product'\] = '([^']*)'", code):
            assert val in enum, (nid, val)
