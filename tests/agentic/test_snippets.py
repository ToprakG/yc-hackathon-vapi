import copy
import json

from builder.agentic.tools.snippets import run_snippet
from tests.agentic.test_lint import CODE_NODE, _tool, with_prep


def code_wf(base_agent, code):
    wf = with_prep(base_agent)
    wf["nodes"]["prep"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"] = code
    return wf


def test_code_node_writes_vars_and_sees_test_variables(base_agent):
    wf = code_wf(base_agent, "try:\n    vars['greeting'] = 'Hi ' + vars.get('last_name', '')\n    print('ran')\nexcept Exception:\n    pass\n")
    res = run_snippet(wf, "prep", {"extra": 1})
    assert res["vars_written"] == {"greeting": "Hi Reyes"} and res["stdout"] == "ran\n" and res["exception"] is None


def test_post_hook_adds_what_to_do_next(base_agent):
    wf = copy.deepcopy(base_agent)
    _tool(wf, "identity", "verify_identity")["post_process_code"] = (
        "try:\n    result.pop('header', None)\n    d = result.get('data')\n    if isinstance(d, dict):\n"
        "        d['what_to_do_next'] = 'Ask the next question.' if d.get('verified') else 'Ask again.'\n"
        "        vars['last_check'] = 'ok' if d.get('verified') else 'wrong'\nexcept Exception:\n    pass\n")
    res = run_snippet(wf, "identity", {}, kind="post_hook", tool="verify_identity", result={"verified": False})
    assert res["result"]["data"]["what_to_do_next"] == "Ask again." and "header" not in res["result"]
    assert res["vars_written"] == {"last_check": "wrong"}


def test_pre_hook_converts_amount_to_cents(base_agent):
    wf = copy.deepcopy(base_agent)
    _tool(wf, "collection", "create_promise")["pre_process_code"] = (
        "try:\n    b = config.get('body')\n    if isinstance(b, dict) and 'amount' in b:\n"
        "        b['amount'] = int(round(float(b['amount']) * 100))\nexcept Exception:\n    pass\n")
    res = run_snippet(wf, "collection", {"amount": "123.45", "date": "2031-03-07", "product_id": "p1", "customer_id": "c9"},
                      kind="pre_hook", tool="create_promise")
    assert res["config"]["body"] == {"date": "2031-03-07", "amount": 12345, "product_id": "p1", "customer_id": "c9"}
    assert res["config"]["url"].endswith("/create_promise")


def test_unresolved_single_placeholder_field_is_dropped(base_agent):
    res = run_snippet(base_agent, "workflow", {"outcome": "no_promise"}, kind="pre_hook", tool="close_call")
    assert "reason" not in res["config"]["body"] and res["config"]["body"]["outcome"] == "no_promise"


def test_raising_snippet_is_reported(base_agent):
    res = run_snippet(code_wf(base_agent, "vars['x'] = 1\nraise ValueError('boom')\n"), "prep", {})
    assert "ValueError: boom" in res["exception"] and res["vars_written"] == {"x": 1}


def test_timeout_is_enforced(base_agent):
    res = run_snippet(code_wf(base_agent, "while True:\n    pass\n"), "prep", {}, timeout=1)
    assert "timeout" in res["error"]


def test_bad_addresses(base_agent):
    assert "no node" in run_snippet(base_agent, "nope", {})["error"]
    assert "no tool" in run_snippet(base_agent, "identity", {}, kind="post_hook", tool="get_account")["error"]
    assert "no pre_hook" in run_snippet(base_agent, "identity", {}, kind="pre_hook", tool="verify_identity")["error"]
    assert json.dumps(CODE_NODE)  # the shared fixture stays serialisable


def _demo():
    from tests.agentic.conftest import REPO

    return json.loads((REPO / "tests" / "agentic" / "fixtures" / "pattern_demo.workflow.json").read_text())


ITEMS = [{"item_ref": "r1", "kind": "kind_a", "ending": "1234", "overdue": 412.5, "days_over": 25, "floor_amount": 80},
         {"item_ref": "r2", "kind": "kind_b", "overdue": 1000, "days_over": 3, "floor_amount": 100}]


def test_calendar_code_node_on_a_friday_before_a_holiday_week():
    facts = json.loads(run_snippet(_demo(), "facts", {"items": ITEMS, "now": "2031-03-07T11:00"})["vars_written"]["facts_json"])
    # Friday 7 March: attempt 1 moves to next week; next Friday (14th) is a holiday, so Thursday 13th
    assert [f["deadline"] for f in facts] == ["2031-03-12", "2031-03-17"]  # 3 and 5 business days, skipping the 14th
    assert [f["attempt1"] for f in facts] == ["2031-03-12", "2031-03-13"]  # capped at the deadline / holiday Friday
    assert [f["attempts"] for f in facts] == [2, 1]


def test_calendar_code_node_with_json_string_list_late_in_the_week():
    res = run_snippet(_demo(), "facts", {"items": json.dumps(ITEMS[:1]), "now": "2031-03-13T16:00"})
    facts = json.loads(res["vars_written"]["facts_json"])
    assert facts[0]["deadline"] == "2031-03-19" and facts[0]["attempt1"] == "2031-03-19"
    assert res["vars_written"]["item_count"] == "1" and "Thursday 13 March" in res["vars_written"]["facts_text"]


def test_setup_node_callback_window_after_cutoff():
    out = run_snippet(_demo(), "setup", {"now": "2031-03-13T17:30"})["vars_written"]
    assert "today" not in out["callback_window_text"].split("Today")[0] and out["callback_next_day_iso"] == "2031-03-17"


def test_facts_node_reads_the_flattened_list_the_platform_delivers():
    flat = {"now": "2031-03-07T11:00"}
    for i, item in enumerate(ITEMS):
        for k, v in item.items():
            flat[f"load_account_response.data.items.{i}.{k}"] = v
    res = run_snippet(_demo(), "facts", flat)
    assert res["vars_written"]["facts_state"] == "ok" and res["vars_written"]["item_count"] == "2"


def _loop(wf, state, answer):
    state = {**state, "offer_answer": answer}
    state.update(run_snippet(wf, "next_offer", state)["vars_written"])
    return state


def test_offer_loop_never_exceeds_the_attempts_per_item():
    wf = _demo()
    state = {"now": "2031-03-07T11:00", "items": ITEMS}  # r1: 2 attempts, r2: 1 attempt
    state.update(run_snippet(wf, "facts", state)["vars_written"])
    state = _loop(wf, state, "stay")  # first entry
    assert state["offer_state"] == "offer" and state["offer_ref"] == "r1" and "412.50" in state["offer_text"]
    state = _loop(wf, state, "refused")
    assert state["offer_state"] == "offer" and "80" in state["offer_text"] and "remaining amount" in state["offer_text"]
    state = _loop(wf, state, "refused")
    assert state["offer_state"] == "out_of_attempts" and state["note_ref"] == "r1"
    state = _loop(wf, state, "noted")
    assert state["offer_state"] == "offer" and state["offer_ref"] == "r2"
    state = _loop(wf, state, "refused")  # r2 allows one attempt only
    assert state["offer_state"] == "out_of_attempts" and state["note_ref"] == "r2"
    assert _loop(wf, state, "noted")["offer_state"] == "done"


def test_offer_loop_moves_on_after_a_recorded_promise():
    wf = _demo()
    state = {"now": "2031-03-07T11:00", "items": ITEMS}
    state.update(run_snippet(wf, "facts", state)["vars_written"])
    state = _loop(wf, state, "stay")
    state = _loop(wf, state, "recorded")
    assert state["offer_state"] == "offer" and state["offer_ref"] == "r2" and state["offer_answer"] == "stay"
    assert _loop(wf, state, "recorded")["offer_state"] == "done"
