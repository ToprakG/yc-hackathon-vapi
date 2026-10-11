"""F18 side answers then the step resumes, F19 declined identity questions: explain once, close at the limit."""
import copy
import json
from pathlib import Path

from builder.template_cc import compiler
from builder.template_cc.apimodel import ApiModel

from .helpers import call_vars, run_code, run_post

REPO = Path(__file__).resolve().parents[2]
GOLD = Path(__file__).resolve().parent / "golden"
NOW = "2031-03-05T10:00"
BASE = "f1,f2,f3,f7,f8"


def build(features, edit=None):
    pol = json.loads((GOLD / "brief-a.policy.json").read_text())
    if edit:
        pol = copy.deepcopy(pol)
        edit(pol)
    wf, _ = compiler.compile(pol, ApiModel.load(REPO / "tools" / "openapi.json"), features=features)
    return wf, pol


def start(wf, pol, **kw):
    v = run_code(wf, "setup", call_vars(pol, NOW))
    v.update(kw)
    return v


def test_a_refusal_sentence_is_not_a_partial_answer_with_f19():
    wf, pol = build(BASE + ",f19")
    v = start(wf, pol, id_intent="refuses", id_answer_text="I am not comfortable giving that over the phone")
    assert run_code(wf, "id_check", v)["id_route"] == "refuse"
    wf0, pol0 = build(BASE)
    assert run_code(wf0, "id_check", start(wf0, pol0, id_intent="refuses", id_answer_text="I am not comfortable giving that"))["id_route"] == "ask"


def test_a_complete_answer_wins_over_a_refusal_intent():
    wf, pol = build(BASE + ",f19")
    v = start(wf, pol, id_intent="asks_question", id_answer_text="the tenth of April nineteen eighty", id_q="date_of_birth")
    assert run_code(wf, "id_check", v)["id_route"] == "send"


def test_every_refusal_counts_explain_once_then_close():
    wf, pol = build(BASE + ",f19")
    assert pol["ask_limits"]["id_decline"] >= 1
    v = start(wf, pol, id_intent="asks_question")
    v = run_code(wf, "id_refusal_count", v)
    assert v["id_route"] == "explain" and v["id_say"].startswith(pol["lines"]["id_reason"]["text"])
    v["id_intent"] = "refuses"
    assert run_code(wf, "id_refusal_count", v)["id_route"] == "decline"
    wf2, pol2 = build(BASE)  # f2 only: the first question back is answered without counting
    v2 = run_code(wf2, "id_refusal_count", start(wf2, pol2, id_intent="asks_question"))
    assert v2["id_route"] == "ask" and v2["id_declines"] == "0"


def test_no_id_decline_parameter_means_no_explanation_node():
    def zero(p):
        p["ask_limits"]["id_decline"] = 0
    wf, pol = build(BASE + ",f19", zero)
    assert "identity_explain" not in wf["nodes"]
    assert run_code(wf, "id_refusal_count", start(wf, pol, id_intent="refuses"))["id_route"] == "decline"


def test_robot_question_with_an_answer_is_answered_and_the_answer_processed():
    wf, pol = build(BASE + ",f18")
    ai = pol["lines"]["ai"]["text"]
    assert wf["nodes"]["identity"]["transitions"][-1]["target_node"] == "id_resume"
    firsts = [t["target_node"] for t in wf["nodes"]["identity"]["transitions"]]
    assert firsts.index("id_aside") < firsts.index("id_check")
    v = start(wf, pol, turn_intent="asks_robot", id_intent="answer", id_answer_text="May twenty third", id_q="date_of_birth")
    v = run_code(wf, "id_aside", v)
    assert v["id_route"] == "answer" and v["aside_line"] == ai and v["turn_intent"] == "none"
    v = run_code(wf, "id_check", v)  # incomplete answer: the question for the rest, with the disclosure in front
    assert v["id_route"] == "ask" and v["id_say"].startswith(ai) and v["aside_line"] == ""


def test_a_pure_robot_question_resumes_the_pending_question():
    wf, pol = build(BASE + ",f18")
    v = start(wf, pol, turn_intent="asks_robot", id_intent="other", id_q="phone_last4")
    v = run_code(wf, "id_aside", v)
    assert v["id_route"] == "resume"
    v = run_code(wf, "id_resume", v)
    assert v["id_say"] == pol["lines"]["ai"]["text"] + " " + pol["identity"]["prompts"]["phone_last4"]
    v = run_code(wf, "id_resume", dict(v, aside_line=""))  # filler: the same question, no free model turn
    assert v["id_say"].endswith(pol["identity"]["prompts"]["phone_last4"])


def test_a_robot_question_with_the_last_answer_is_carried_to_the_first_debt_line():
    from .helpers import fake_products
    wf, pol = build(BASE + ",f18")
    v = start(wf, pol, aside_line="I am Freya Bank's digital assistant.")
    v["products_raw"] = fake_products(pol, 1)
    out = run_code(wf, "facts", v)
    assert out["debt_statement"].startswith("I am Freya Bank's digital assistant.") and out["aside_line"] == ""


def test_without_a_policy_line_or_the_flag_nothing_changes():
    from builder.template_cc.compiler.graph import Graph
    from builder.template_cc import features as FT
    api = ApiModel.load(REPO / "tools" / "openapi.json")
    pol = compiler.policy_check.complete(copy.deepcopy(json.loads((GOLD / "brief-a.policy.json").read_text())), api)
    pol["lines"]["ai"] = {"text": "", "verbatim": False}  # complete() refills a missing line, so the graph is built directly
    pol["lines"]["scam"] = {"text": "", "verbatim": False}
    wf, _ = Graph(pol, api, features=FT.parse(BASE + ",f18")).build()
    assert "id_aside" not in wf["nodes"] and "id_resume" not in wf["nodes"]
    wf, _ = build(BASE)
    assert "id_aside" not in wf["nodes"]
    wf, _ = build("f1,f2,f18")  # no router: no turn_intent to read
    assert "id_aside" not in wf["nodes"]
    for feats in (BASE + ",f18,f19", BASE + ",f18"):
        wf, pol = build(feats)
        assert compiler.lint(wf, pol, api)["errors"] == []
