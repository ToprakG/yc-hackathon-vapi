import asyncio
import json
import shutil

import pytest

from builder.agentic import mcp_server
from builder.agentic.tools.clock import Clock
from builder.common import io
from tests.agentic.conftest import REPO

FIX = REPO / "tests" / "agentic" / "fixtures"
PATHLIKE = ("path", "file", "dir", "filename", "file_path")


@pytest.fixture
def bound(tmp_path):
    ws = tmp_path / "ws"
    brief = tmp_path / "brief.md"
    brief.write_text("1. Ask for the six-digit member code first.\n")
    io.build_workspace(ws, [brief], FIX / "pattern_demo.openapi.json")
    events = []
    tools = mcp_server.BoundTools(ws, Clock(22), on_event=lambda k, d: events.append((k, d)),
                                  validate_fn=lambda wf, name: {"skipped": "no key"})
    return tools, ws, events


def test_no_tool_takes_a_path():
    for name, (_, schema) in mcp_server.TOOL_SPECS.items():
        props = schema.get("properties", {})
        assert not any(any(w in p.lower() for w in PATHLIKE) for p in props), (name, list(props))
        assert schema.get("additionalProperties") is False
    assert mcp_server.tool_names()[0] == "mcp__fb__openapi_summary"


def test_tools_work_on_the_bound_files(bound):
    tools, ws, events = bound
    assert "does not exist yet" in tools.call("lint_workflow")
    assert "does not exist yet" in tools.call("check_coverage")
    assert "base URL: https://api.example-bank.invalid/v1" in tools.call("openapi_summary")
    shutil.copyfile(FIX / "pattern_demo.workflow.json", ws / "out" / "workflow.json")
    assert tools.call("lint_workflow").startswith("0 error(s)") and (ws / "out" / "last_good.workflow.json").exists()
    out = json.loads(tools.call("run_snippet", {"node_id": "setup", "kind": "code", "vars_json": '{"now": "2031-03-07T11:00"}'}))
    assert out["vars_written"]["today_spoken"] == "Friday 7 March"
    (ws / "out" / "rules.json").write_text(json.dumps([{"id": "R1", "kind": "identity", "statement": "s",
        "source_quote": "Ask for the six-digit member code first", "implemented_in": ["node:identity"]}]))
    assert tools.call("check_coverage").startswith("0 error(s)")
    assert json.loads(tools.call("validate_workflow")) == {"skipped": "no key"}
    assert json.loads(tools.call("time_left"))["minutes_left"] > 21
    assert "not valid JSON" in tools.call("run_snippet", {"node_id": "setup", "kind": "code", "vars_json": "{bad"})
    assert any(k == "check" for k, _ in events)


def test_unknown_tool_and_errors_are_text(bound):
    tools, ws, _ = bound
    assert tools.call("rm_rf") == "unknown tool rm_rf"
    (ws / "out" / "workflow.json").write_text("{")
    assert "not valid JSON" in tools.call("run_snippet", {"node_id": "x", "kind": "code"})


def test_sdk_server_wraps_every_tool(bound):
    pytest.importorskip("claude_agent_sdk")
    tools, _, _ = bound
    server = mcp_server.build_server(tools)
    assert server["type"] == "sdk" and server["name"] == "fb"
    from claude_agent_sdk import tool  # noqa: F401  (import only; no model call)

    asyncio.run(asyncio.sleep(0))
