import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("claude_agent_sdk")
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock  # noqa: E402

from builder.agentic import run as run_mod  # noqa: E402
from tests.agentic.conftest import REPO  # noqa: E402

FIX = REPO / "tests" / "agentic" / "fixtures"
NO_VALIDATE = staticmethod(lambda wf, name: {"skipped": "no key"})


class FakeFreya:
    def __init__(self):
        self.calls = []

    def save_workflow(self, slot, wf, state_file=".freya-agents.json"):
        self.calls.append(("save", slot, state_file, wf))
        return {"workflow_id": "wf_1", "agent_id": "ag_1", "version": 2}

    def export_workflow(self, workflow_id, path):
        self.calls.append(("export", workflow_id, path))
        Path(path).write_text("{}")
        return path

    def __getattr__(self, name):  # any other Freya call is a test failure
        raise AssertionError(f"unexpected Freya call {name}")


def fake_query(write):
    """An SDK stand-in: writes the agent's files into the workspace and yields real message objects."""

    async def query(prompt, options):
        out = Path(options.cwd) / "out"
        write(out)
        yield AssistantMessage(content=[TextBlock("Reading the brief."), ToolUseBlock("t1", "mcp__fb__lint_workflow", {})],
                               model="claude-test")
        yield ResultMessage(subtype="success", duration_ms=1200, duration_api_ms=900, is_error=False, num_turns=3,
                            session_id="s", total_cost_usd=0.12, usage={"input_tokens": 10, "output_tokens": 5})

    return query


def opts(tmp_path, save="none", **kw):
    return run_mod.BuildOptions(briefs=[REPO / "briefs" / "brief-a.md"], api=FIX / "pattern_demo.openapi.json",
                                slot="agentic-test", out_dir=tmp_path / "out", save=save, **kw)


def go(tmp_path, write, save="none", freya=None, **kw):
    return run_mod.run(opts(tmp_path, save, **kw), query_fn=fake_query(write), freya_mod=freya,
                       validate_fn=lambda wf, name: {"skipped": "no key"}, trace_root=tmp_path / "traces")


def good(out):
    shutil.copyfile(FIX / "pattern_demo.workflow.json", out / "workflow.json")
    (out / "policy.json").write_text("{}")
    (out / "rules.json").write_text("[]")


def broken_with_last_good(out):
    shutil.copyfile(FIX / "pattern_demo.workflow.json", out / "last_good.workflow.json")
    wf = json.loads((FIX / "pattern_demo.workflow.json").read_text())
    wf["nodes"]["facts"]["tools"] = wf["nodes"]["negotiate"]["tools"]  # tools on a code node: a lint error
    (out / "workflow.json").write_text(json.dumps(wf))


def test_last_good_is_used_when_the_final_file_is_broken(tmp_path):
    report = go(tmp_path, broken_with_last_good)
    assert report["status"] == "ok" and report["fallback_used"] and report["lint_agent_output"]["errors"] > 0
    assert json.loads((tmp_path / "out" / "workflow.json").read_text()) == json.loads((FIX / "pattern_demo.workflow.json").read_text())
    assert (tmp_path / "out" / "workflow.rejected.json").exists()


def test_save_none_touches_no_freya(tmp_path):
    freya = FakeFreya()
    report = go(tmp_path, good, save="none", freya=freya)
    assert report["status"] == "ok" and freya.calls == [] and report["saved"] is None
    assert json.loads((tmp_path / "out" / "build_report.json").read_text())["status"] == "ok"
    for name in ("workflow.json", "policy.json", "rules.json"):
        assert (tmp_path / "out" / name).exists()


def test_save_freya_uses_the_absolute_state_file_and_exports(tmp_path):
    freya = FakeFreya()
    report = go(tmp_path, good, save="freya", freya=freya)
    save, export = freya.calls
    assert save[0] == "save" and save[1] == "agentic-test" and save[2] == str(REPO / ".freya-agents.json")
    assert Path(save[2]).is_absolute() and "agent_config" not in save[3]
    assert export == ("export", "wf_1", str(tmp_path / "out" / "agentic-test.workflow.json"))
    assert report["saved"]["agent_id"] == "ag_1" and report["status"] == "ok"


def test_agent_config_is_stripped(tmp_path, monkeypatch):
    def with_config(out):
        wf = json.loads((FIX / "pattern_demo.workflow.json").read_text())
        wf["agent_config"] = {"llmConfig": {"model": "x"}}
        (out / "workflow.json").write_text(json.dumps(wf))

    real = run_mod.lint.lint_file
    monkeypatch.setattr(run_mod.lint, "lint_file", lambda *a, **k: {**real(*a, **k), "errors": []})
    report = go(tmp_path, with_config)
    assert report["status"] == "ok" and "agent_config" not in json.loads((tmp_path / "out" / "workflow.json").read_text())


def test_no_workflow_fails_with_exit_status(tmp_path):
    report = go(tmp_path, lambda out: None)
    assert report["status"] == "failed" and "no lint-clean workflow" in report["message"]


def test_trace_has_times_model_lines_and_the_no_simulation_note(tmp_path):
    report = go(tmp_path, good)
    trace_dir = Path(report["trace"])
    assert trace_dir.parent == tmp_path / "traces" and trace_dir.name.startswith("agentic-test-")
    text = (trace_dir / "trace.txt").read_text()
    assert text.splitlines()[0].split(" ", 1)[1].startswith("start ") and " end " in text.splitlines()[-1]
    assert "model claude-test: Reading the brief." in text and "tool mcp__fb__lint_workflow" in text
    assert "Simulations: none" in text and "cost $0.12" in text and "freya: nothing created" in text
    kinds = [json.loads(line)["type"] for line in (trace_dir / "messages.jsonl").read_text().splitlines()]
    assert kinds[0] == "start" and kinds[-1] == "end" and "AssistantMessage" in kinds and "ResultMessage" in kinds


def test_timeout_stops_the_agent_and_still_finalizes(tmp_path):
    async def slow(prompt, options):
        import anyio

        good(Path(options.cwd) / "out")
        await anyio.sleep(30)
        yield None  # never reached

    report = run_mod.run(opts(tmp_path, max_minutes=0.01, review=False), query_fn=slow, validate_fn=lambda wf, n: {"skipped": "no key"},
                         trace_root=tmp_path / "traces")
    assert report["agent"]["timed_out"] and report["status"] == "ok"
    assert "timeout" in (Path(report["trace"]) / "trace.txt").read_text()


def test_workspace_is_removed_unless_kept(tmp_path):
    report = go(tmp_path, good)
    assert "workspace" not in report
    report = go(tmp_path, good, keep_workspace=True)
    assert Path(report["workspace"]).is_dir() and (Path(report["workspace"]) / "input" / "brief-1.md").exists()
    shutil.rmtree(report["workspace"])


def test_kill_pids_terminates_a_child(tmp_path):
    import subprocess
    import sys

    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    assert run_mod.kill_pids([p.pid], grace_s=2) == 1
    assert p.poll() is not None or p.wait(timeout=2) is not None
