import json

import pytest

from builder.common import io
from tests.agentic.conftest import REPO

API = REPO / "tools" / "openapi.json"


@pytest.fixture
def files(tmp_path):
    out = {}
    for name, text in {"memo.txt": "memo", "thread.eml": "From: x", "codes.csv": "a,b", "brief.md": "# B",
                       "extract.json": json.dumps({"policy": "text"})}.items():
        (tmp_path / name).write_text(text)
        out[name] = tmp_path / name
    (tmp_path / "renamed.api").write_text(API.read_text())
    out["api"] = tmp_path / "renamed.api"
    return out


def test_api_found_by_openapi_key_in_any_position(files):
    briefs, api = io.split_inputs([files["api"], files["memo.txt"], files["thread.eml"]])
    assert api == files["api"] and briefs == [files["memo.txt"], files["thread.eml"]]
    briefs, api = io.split_inputs([files["codes.csv"], files["extract.json"], files["api"], files["brief.md"]])
    assert briefs == [files["codes.csv"], files["extract.json"], files["brief.md"]]  # order kept; JSON brief accepted


def test_zero_or_two_api_files_fail(files, tmp_path):
    with pytest.raises(io.InputError, match="exactly one"):
        io.split_inputs([files["memo.txt"]])
    (tmp_path / "b.json").write_text(API.read_text())
    with pytest.raises(io.InputError, match="exactly one"):
        io.split_inputs([files["memo.txt"], files["api"], tmp_path / "b.json"])
    with pytest.raises(io.InputError, match="at least one brief"):
        io.split_inputs([files["api"]])
    with pytest.raises(io.InputError, match="not a file"):
        io.split_inputs([tmp_path / "missing.md", files["api"]])


def test_slot_names():
    assert io.slot_name([REPO / "briefs" / "brief-a.md"]) == "agentic-brief-a"
    assert io.slot_name([REPO / "briefs" / "brief-a.md", REPO / "briefs" / "brief-b.md"]) == "agentic-brief-b"
    assert io.slot_name([REPO / "testbed" / "fake_briefs" / "f5-halden-email" / "brief.md"]) == "agentic-f5-halden-email"


def test_workspace_has_exactly_the_allowed_files(files, tmp_path):
    ws = tmp_path / "ws"
    io.build_workspace(ws, [files["brief.md"], files["thread.eml"], files["codes.csv"]], files["api"])
    got = sorted(str(p.relative_to(ws)) for p in ws.rglob("*") if p.is_file())
    skill = sorted(".claude/skills/build-collections-agent/" + str(p.relative_to(io.SKILL_DIR))
                   for p in io.SKILL_DIR.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    assert got == sorted(["input/brief-1.md", "input/brief-2.eml", "input/brief-3.csv", "input/tools.openapi.json",
                          "docs/api.md", "docs/tools-and-code.md", "docs/workflow-format.md",
                          "examples/pattern_demo.workflow.json", "examples/pattern_demo.openapi.json", *skill])
    assert (ws / "out").is_dir() and not list((ws / "out").iterdir())
    assert not list(ws.rglob("base-agent.json")) and not list(ws.rglob("config.json")) and not list(ws.rglob("cases.json"))
    assert (ws / "input" / "brief-2.eml").read_text() == "From: x"
