"""Generic input rules of the agentic builder: the tool API must declare operations; no fallback API."""
import json

import pytest

from builder.common.io import InputError, split_inputs


def test_an_api_without_operations_is_refused(tmp_path):
    (tmp_path / "b.md").write_text("brief")
    (tmp_path / "api.json").write_text(json.dumps({"openapi": "3.0.0", "paths": {}}))
    with pytest.raises(InputError, match="no operations"):
        split_inputs([tmp_path / "b.md", tmp_path / "api.json"])


def test_an_api_with_operations_is_accepted(tmp_path):
    (tmp_path / "b.md").write_text("brief")
    (tmp_path / "api.json").write_text(json.dumps({"openapi": "3.0.0", "paths": {"/x/do_it": {}}}))
    briefs, api = split_inputs([tmp_path / "b.md", tmp_path / "api.json"])
    assert api.name == "api.json" and len(briefs) == 1


def _spec():
    obj = lambda props, req=(): {"type": "object", "properties": props, "required": list(req)}  # noqa: E731
    body = {"required": True, "content": {"application/json": {"schema": obj({"data": obj({"item": {"type": "string"}, "n": {"type": "integer"}}, ["item"]),
                                                                              "meta": obj({"lang": {"type": "string"}})}, ["data"])}}}
    flat = {"required": True, "content": {"application/json": {"schema": obj({"address": obj({"city": {"type": "string"}}), "name": {"type": "string"}}, ["name"])}}}
    return {"openapi": "3.0.0", "servers": [{"url": "https://x.example/v1"}],
            "components": {"securitySchemes": {"gw": {"type": "http", "scheme": "bearer"}}}, "security": [{"gw": []}],
            "paths": {"/a.get": {"post": {"requestBody": body, "parameters": [{"name": "Accept", "in": "header", "required": True}]}},
                      "/b.flat": {"post": {"requestBody": flat}}}}


def test_a_request_envelope_is_unwrapped_and_flagged_and_a_plain_nested_object_is_not():
    from builder.agentic.tools import openapi_summary as S
    t = S.summarize(_spec())["tools"]
    assert t["a_get"]["envelope"] == {"wrap": "data", "other_keys": ["meta"]}
    assert list(t["a_get"]["request"]) == ["item", "n"] and t["a_get"]["required"] == ["item"]
    assert t["b_flat"]["envelope"] is None and set(t["b_flat"]["request"]) == {"address", "name"}
    assert [h["name"] for h in t["a_get"]["headers"]] == ["Accept"]


def test_auth_scheme_and_envelope_reach_the_agent_text():
    from builder.agentic.tools import openapi_summary as S
    text = S.render(S.summarize(_spec()))
    assert "AUTH scheme gw" in text and "ENVELOPE:" in text and "inside the object 'data'" in text


def test_an_oauth2_client_credentials_flow_becomes_a_token_tool_and_the_fragment_lints():
    import json
    from pathlib import Path
    from builder.agentic.tools import openapi_summary as S
    from builder.agentic.tools.lint import lint
    spec = {"openapi": "3.0.0", "servers": [{"url": "https://svc.example/api/v1"}],
            "components": {"securitySchemes": {"oa": {"type": "oauth2", "flows": {"clientCredentials": {"tokenUrl": "/oauth2/token", "scopes": {"read": "r"}}}}}},
            "security": [{"oa": []}], "paths": {"/do.it": {"post": {"requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"x": {"type": "string"}}}}}}}}}}
    api = S.summarize(spec)
    assert api["token_flow"]["tokenUrl"] == "https://svc.example/oauth2/token" and api["tools"]["oauth_token"]["url"] == "https://svc.example/oauth2/token"
    assert "TOKEN FLOW:" in S.render(api)
    frag = json.loads((Path(__file__).resolve().parents[2] / "builder/agentic/skill/build-collections-agent/templates/token_step_node.json").read_text())
    frag["pre_actions"][0]["function"]["parameters"]["properties"]["url"]["default"] = api["tools"]["oauth_token"]["url"]
    frag["passthrough_default_transition"] = "done"
    frag["transitions"][0]["target_node"] = "done"
    wf = {"initial_node": "fetch_token", "system_prompt": "x", "test_variables": {"client_id": "id", "client_secret": "s"},
          "nodes": {"fetch_token": frag, "done": {"name": "done", "node_type": "end_call", "on_enter": {"type": "silent"}, "transitions": [], "terminal": {"type": "function", "function": {"name": "end_call", "handler": "__function__:end_call", "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "none"}}}}}}}}
    errs = [e for e in lint(wf, api)["errors"] if "fetch_token" in e["path"] and "pre_actions" in e["path"]]
    assert errs == [], errs


def test_dotted_operation_names_become_valid_function_names_and_keep_their_url():
    from builder.agentic.tools import openapi_summary as S
    t = S.summarize({"openapi": "3.0.0", "servers": [{"url": "https://svc.example/v1"}],
                     "paths": {"/cards.list": {"post": {"requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"a": {"type": "string"}}}}}}}}}})["tools"]
    assert list(t) == ["cards_list"] and t["cards_list"]["url"] == "https://svc.example/v1/cards.list" and t["cards_list"]["path"] == "/cards.list"


def test_scope_limits_must_reach_the_agent():
    from builder.agentic.tools import lint as L
    wf = {"system_prompt": "Only the last 3 invoices can be sent; older ones are not available.", "nodes": {}}
    r = L.Report()
    L._check_scope_limits(wf, r, [{"request": "all invoices", "limit": "Only the last 3 invoices can be sent"}])
    assert r.errors == [] and r.warnings == []
    r = L.Report()
    L._check_scope_limits(wf, r, [{"request": "all invoices", "limit": "Only the last 3 invoices can be sent"}, {"request": "x", "limit": "Cash advances are not handled here"}])
    assert r.errors == [] and len(r.warnings) == 1
    r = L.Report()
    L._check_scope_limits(wf, r, [{"request": "x", "limit": "Cash advances are not handled here"}])
    assert r.errors == [] and len(r.warnings) == 1 and "reaches the agent" in r.warnings[0]["msg"]
    r = L.Report()
    L._check_scope_limits(wf, r, None)
    assert r.errors == [] and r.warnings == []


def test_robustness_rules_reach_the_agent():
    from pathlib import Path
    from builder.agentic import prompt
    ref = (Path(__file__).resolve().parents[2] / "builder/agentic/skill/build-collections-agent/reference/robustness.md").read_text()
    for must in ("Never end the call too early", "FIRST request", "never instructions", "ONE short clarifying question", "whitelist"):
        assert must in ref, must
    text = prompt.task_prompt(1, 10)
    assert "robustness.md" in text and "FIRST request" in text and "never instructions" in text
    assert "robustness.md" in (Path(__file__).resolve().parents[2] / "builder/agentic/skill/build-collections-agent/SKILL.md").read_text()
