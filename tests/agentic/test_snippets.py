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
