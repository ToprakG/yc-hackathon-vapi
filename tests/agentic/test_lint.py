import copy
import json

import pytest

from builder.agentic.tools import lint

CODE_NODE = {
    "name": "prep", "node_type": "code", "passthrough": True, "passthrough_default_transition": "identity",
    "on_enter": {"type": "silent"},
    "pre_actions": [{"type": "function", "function": {"name": "code_exec", "handler": "__function__:code_exec",
                     "parameters": {"type": "object", "properties": {
                         "code": {"type": "string", "default": "try:\n    vars['ready'] = 'yes'\nexcept Exception:\n    vars['ready'] = 'no'\n"}}}}}],
    "transitions": [{"target_node": "identity", "description": "always", "condition": {"operator": "always"}}],
}
END_NODE = {"name": "bye", "node_type": "end_call", "on_enter": {"type": "silent"}, "transitions": [],
            "terminal": {"type": "function", "function": {"name": "done", "handler": "__function__:end_call",
                         "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "none"}}}}}}


def errors(wf, api, **kw):
    return [e["msg"] for e in lint.lint(wf, api, **kw)["errors"]]


def warnings(wf, api, **kw):
    return [e["msg"] for e in lint.lint(wf, api, **kw)["warnings"]]


def with_prep(wf):
    wf = copy.deepcopy(wf)
    wf["nodes"]["prep"] = copy.deepcopy(CODE_NODE)
    wf["initial_node"] = "prep"
    return wf


def test_base_agent_is_clean(base_agent, kit_api):
    report = lint.lint(base_agent, kit_api)
    assert report["errors"] == [], report["errors"]
    assert any("null" in w["msg"] for w in report["warnings"])  # warned, not an error


def test_code_node_prefix_is_clean(base_agent, kit_api):
    assert errors(with_prep(base_agent), kit_api) == []


def _tool(wf, node, name):
    return next(t for t in wf["nodes"][node]["tools"] if t["function"]["name"] == name)


def _body(tool):
    return tool["function"]["parameters"]["properties"]["body"]


# (id, mutation, expected substring of one error)
def m_agent_config(wf): wf["agent_config"] = {"llmConfig": {}}
def m_tools_on_code(wf): wf["nodes"]["prep"]["tools"] = [copy.deepcopy(_tool(wf, "collection", "get_account"))]
def m_pre_on_conv(wf): wf["nodes"]["collection"]["pre_actions"] = copy.deepcopy(wf["nodes"]["prep"]["pre_actions"])
def m_no_always(wf): wf["nodes"]["prep"]["transitions"][-1]["condition"] = {"operator": "matches_intent", "description": "x"}
def m_unknown_target(wf): wf["nodes"]["identity"]["transitions"][0]["target_node"] = "nowhere"
def m_unreachable(wf): wf["nodes"]["orphan"] = copy.deepcopy(END_NODE)
def m_const_url(wf): _tool(wf, "collection", "get_account")["function"]["parameters"]["properties"]["url"] = {"type": "string", "const": "https://x"}
def m_body_field_not_in_schema(wf): _body(_tool(wf, "collection", "create_promise"))["properties"]["method_of_payment"] = {"type": "string", "default": "{{m}}"}
def m_enum_not_in_api(wf): _body(_tool(wf, "identity", "verify_identity"))["properties"]["field"]["enum"].append("mothers_maiden_name")
def m_braces_in_code(wf): wf["nodes"]["prep"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"] = "try:\n    vars['x'] = {'a': {'b': 1}}\nexcept Exception:\n    pass\n"
def m_syntax_error(wf): wf["nodes"]["prep"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"] = "try:\n    vars['x'] = (\nexcept Exception:\n    pass\n"
def m_nested_mapping(wf): wf["nodes"]["prep"]["pre_actions"][0]["response_mapping"] = [{"path": "data.x", "variable": "x"}]
def m_unset_tts(wf): wf["nodes"]["identity"]["on_enter"]["text"] = "Hello {{nickname}}"
def m_wrong_host(wf): _tool(wf, "collection", "get_account")["function"]["parameters"]["properties"]["url"]["default"] = "https://evil.example/v1/get_account"
def m_missing_required(wf): del _body(_tool(wf, "collection", "create_promise"))["properties"]["date"]
def m_field_without_default(wf): del _body(_tool(wf, "collection", "create_promise"))["properties"]["amount"]["default"]
def m_unknown_tool(wf): _tool(wf, "collection", "get_account")["function"]["name"] = "get_balance"
def m_and_at_top(wf): wf["nodes"]["identity"]["transitions"][0]["condition"]["logic"] = "and"
def m_unknown_operator(wf): wf["nodes"]["identity"]["transitions"][0]["condition"]["conditions"][0]["operator"] = "is_true"
def m_missing_min_conf(wf): wf["nodes"]["identity"]["extraction_schema"] = [{"name": "dob", "type": "string", "description": "d"}]
def m_hook_on_code(wf): wf["nodes"]["prep"]["pre_actions"][0]["post_process_code"] = "pass"
def m_customer_id_unbaked(wf): _body(_tool(wf, "collection", "get_account"))["properties"]["customer_id"]["default"] = "c_1"
def m_initial_missing(wf): wf["initial_node"] = "start"
def m_end_with_transitions(wf):
    wf["nodes"]["bye"] = copy.deepcopy(END_NODE)
    wf["nodes"]["bye"]["transitions"] = [{"target_node": "identity", "description": "x", "condition": {"operator": "always"}}]
    wf["nodes"]["collection"]["transitions"] = [{"target_node": "bye", "description": "done", "condition": {"operator": "matches_intent", "description": "done"}}]
def m_tool_after_close(wf):
    close = copy.deepcopy(wf["tools"][0])
    del close["config"]["alwaysRunsAt"]
    wf["tools"] = []
    wf["nodes"]["closing"] = {"name": "closing", "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "collection",
                              "on_enter": {"type": "silent"}, "pre_actions": [close],
                              "transitions": [{"target_node": "collection", "description": "always", "condition": {"operator": "always"}}]}
    wf["nodes"]["identity"]["transitions"].append({"target_node": "closing", "description": "fail", "condition": {"operator": "matches_intent", "description": "x"}})
def m_no_close_on_path(wf): wf["tools"] = []
def m_no_terminal(wf):
    for n in wf["nodes"].values():
        n["tools"] = [t for t in n.get("tools", []) if t["function"]["handler"] != "__function__:end_call"]


MUTATIONS = [
    (m_agent_config, "agent_config must be left out"),
    (m_tools_on_code, "tools on a code node"),
    (m_pre_on_conv, "pre_actions on a conversation node"),
    (m_no_always, "must end with an always transition"),
    (m_unknown_target, "target_node 'nowhere' does not exist"),
    (m_unreachable, "not reachable"),
    (m_const_url, "url needs a 'default' (const does not bake)"),
    (m_body_field_not_in_schema, "'method_of_payment' is not a request field"),
    (m_enum_not_in_api, "not in the API enum"),
    (m_braces_in_code, "no '{{' or '}}' in code"),
    (m_syntax_error, "does not compile"),
    (m_nested_mapping, "response_mapping inside a pre_action"),
    (m_unset_tts, "{{nickname}} is never set; this fixed line would say it aloud"),
    (m_wrong_host, "url must be https://freya-bank-mock"),
    (m_missing_required, "required field(s) of create_promise missing"),
    (m_field_without_default, "amount needs its own 'default'"),
    (m_unknown_tool, "'get_balance' is not a tool of the tool API"),
    (m_and_at_top, "never put logic 'and' at the top level"),
    (m_unknown_operator, "unknown operator 'is_true'"),
    (m_missing_min_conf, "set min_confidence"),
    (m_hook_on_code, "removed by the platform"),
    (m_customer_id_unbaked, "customer_id is a call variable"),
    (m_initial_missing, "initial_node 'start' is not a node"),
    (m_end_with_transitions, "end_call node must have no transitions"),
    (m_tool_after_close, "after close_call only an end_call node may follow"),
    (m_no_close_on_path, "without close_call"),
    (m_no_terminal, "no terminal"),
]


@pytest.mark.parametrize("mutate,expected", MUTATIONS, ids=[m.__name__[2:] for m, _ in MUTATIONS])
def test_mutation_is_caught(base_agent, kit_api, mutate, expected):
    wf = with_prep(base_agent)
    mutate(wf)
    errs = errors(wf, kit_api)
    assert any(expected in e for e in errs), errs


def test_warnings_for_soft_problems(base_agent, kit_api):
    wf = with_prep(base_agent)
    cond = wf["nodes"]["identity"]["transitions"][0]["condition"]
    cond["conditions"] = cond["conditions"][:1]  # only "true"
    wf["nodes"]["identity"]["extraction_schema"] = [{"name": "when", "type": "date", "description": "d", "min_confidence": 0.7}]
    wf["nodes"]["collection"]["task_message"] = "Say the amount."  # no longer names its tools
    wf["nodes"]["collection"]["transitions"] = [{"target_node": "identity", "description": "x",
                                                 "condition": {"logic": "or", "conditions": [{"variable": "ghost", "operator": "is_set"}]}}]
    _tool(wf, "collection", "create_promise")["config"]["maxRetries"] = 2
    ws = warnings(wf, kit_api)
    for expected in ("tested as 'true' only", "type 'date' resolves relative dates", "does not name tool 'get_account'",
                     "nothing sets variable 'ghost'", "maxRetries > 0"):
        assert any(expected in w for w in ws), (expected, ws)
    assert errors(wf, kit_api) == []


def test_variables_written_by_code_count_as_set(base_agent, kit_api):
    wf = with_prep(base_agent)
    wf["nodes"]["identity"]["task_message"] += " Ready: {{ready}}. Turns: {{identity.current_turns}}. {{get_account_response.data.ok}}"
    assert not [w for w in warnings(wf, kit_api) if "never set" in w]


def test_lint_file_saves_last_good(tmp_path, base_agent, kit_api):
    p = tmp_path / "workflow.json"
    p.write_text(json.dumps(base_agent))
    report = lint.lint_file(p, kit_api, last_good_path=tmp_path / "last_good.workflow.json")
    assert report["saved_last_good"] and (tmp_path / "last_good.workflow.json").exists()
    p.write_text("{not json")
    assert "invalid JSON" in lint.lint_file(p, kit_api)["errors"][0]["msg"]


def test_policy_call_variables_and_unused_tools(tmp_path, base_agent, kit_api):
    (tmp_path / "workflow.json").write_text(json.dumps(base_agent))
    (tmp_path / "policy.json").write_text(json.dumps({"call_variables": ["customer_id", "title", "last_name", "now"],
                                                      "unused_tools": ["add_note", "schedule_callback", "transfer_to_agent"]}))
    report = lint.lint_file(tmp_path / "workflow.json", kit_api, policy_path=tmp_path / "policy.json")
    assert not [w for w in report["warnings"] if "not used anywhere" in w["msg"]]


def test_list_mapping_is_warned(base_agent, kit_api):
    wf = with_prep(base_agent)
    wf["nodes"]["load"] = {"name": "load", "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "collection",
                           "on_enter": {"type": "silent"}, "pre_actions": [copy.deepcopy(_tool(wf, "collection", "get_account"))],
                           "response_mapping": [{"path": "data.products", "variable": "products"}],
                           "transitions": [{"target_node": "collection", "description": "always", "condition": {"operator": "always"}}]}
    wf["nodes"]["identity"]["transitions"][0]["target_node"] = "load"
    ws = warnings(wf, kit_api)
    assert any("load_response.data.products.<i>.<field>" in w for w in ws), ws
