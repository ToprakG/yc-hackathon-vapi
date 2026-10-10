import asyncio
import os

import pytest

from builder.agentic import guard


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "ws"
    for d in ("input", "docs", "out"):
        (root / d).mkdir(parents=True)
    (root / "input" / "brief-1.md").write_text("brief")
    (root / "docs" / "workflow-format.md").write_text("doc")
    (tmp_path / "secret.txt").write_text("outside")
    os.symlink(tmp_path / "secret.txt", root / "input" / "link.md")
    return root


@pytest.mark.parametrize("tool,inp", [
    ("Read", {"file_path": "../testbed/fake_briefs/f1/config.json"}),
    ("Read", {"file_path": "/etc/passwd"}),
    ("Read", {"file_path": "input/link.md"}),  # symlink escaping the workspace
    ("Read", {"file_path": "input/cases.json"}),
    ("Read", {"file_path": "docs/config.json"}),
    ("Read", {"file_path": "~/.env"}),
    ("Write", {"file_path": "input/brief-1.md", "content": "x"}),  # writes only under out/
    ("Edit", {"file_path": "docs/workflow-format.md", "old_string": "a", "new_string": "b"}),
    ("Write", {"file_path": "out/../input/x.json", "content": "x"}),
    ("Glob", {"pattern": "../**/*.json"}),
    ("Glob", {"pattern": "/tmp/*"}),
    ("Glob", {"pattern": "*.md", "path": ".."}),
    ("Grep", {"pattern": "oracle", "path": "/"}),
    ("Grep", {"pattern": "x", "glob": "../*"}),
    ("Bash", {"command": "ls"}),
    ("WebFetch", {"url": "https://example.com"}),
    ("Read", {}),
])
def test_denied(ws, tool, inp):
    allowed, reason = guard.check(tool, inp, ws)
    assert not allowed, reason


@pytest.mark.parametrize("tool,inp", [
    ("Read", {"file_path": "input/brief-1.md"}),
    ("Read", {"file_path": "docs/workflow-format.md"}),
    ("Write", {"file_path": "out/workflow.json", "content": "{}"}),
    ("Edit", {"file_path": "out/rules.json", "old_string": "a", "new_string": "b"}),
    ("Glob", {"pattern": "input/*"}),
    ("Glob", {"pattern": "**/*.md"}),
    ("Grep", {"pattern": "oracle"}),  # a regex over contents, not a path
    ("mcp__fb__lint_workflow", {}),
    ("Skill", {"skill": "build-collections-agent"}),
])
def test_allowed(ws, tool, inp):
    allowed, reason = guard.check(tool, inp, ws)
    assert allowed, reason


def test_absolute_path_inside_workspace_is_allowed(ws):
    assert guard.check("Read", {"file_path": str(ws / "input" / "brief-1.md")}, ws)[0]


def test_hook_denies_and_logs(ws):
    events = []
    hook = guard.make_hook(ws, on_event=lambda kind, detail: events.append((kind, detail)))
    out = asyncio.run(hook({"tool_name": "Read", "tool_input": {"file_path": "../x"}}, "t1", {"signal": None}))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny" and events[0][0] == "denied"
    assert asyncio.run(hook({"tool_name": "Read", "tool_input": {"file_path": "input/brief-1.md"}}, "t2", {"signal": None})) == {}
