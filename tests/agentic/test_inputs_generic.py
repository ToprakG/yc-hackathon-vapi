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
    assert t["a.get"]["envelope"] == {"wrap": "data", "other_keys": ["meta"]}
    assert list(t["a.get"]["request"]) == ["item", "n"] and t["a.get"]["required"] == ["item"]
    assert t["b.flat"]["envelope"] is None and set(t["b.flat"]["request"]) == {"address", "name"}
    assert [h["name"] for h in t["a.get"]["headers"]] == ["Accept"]


def test_auth_scheme_and_envelope_reach_the_agent_text():
    from builder.agentic.tools import openapi_summary as S
    text = S.render(S.summarize(_spec()))
    assert "AUTH scheme gw" in text and "ENVELOPE:" in text and "inside the object 'data'" in text
