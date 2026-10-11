"""The Claude Code session log of the builder run is copied next to the trace with secrets redacted; the login token reaches claude -p."""
import json
import os
import re

from builder.common import session_log as S


def test_project_dir_name_matches_claude_codes_encoding(tmp_path):
    ws = tmp_path / "fb-build-ab_c"
    ws.mkdir()
    d = S.project_dir(ws, home=tmp_path / "home")
    assert d.parent == tmp_path / "home" / ".claude" / "projects"
    assert re.fullmatch(r"[A-Za-z0-9-]+", d.name) and d.name.endswith("fb-build-ab-c")


def test_logs_are_copied_and_redacted(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    home = tmp_path / "home"
    src = S.project_dir(ws, home)
    src.mkdir(parents=True)
    tok = "sk-" + "ant-oat01-" + "A" * 30                      # built at run time: no key-shaped literal in the repo
    mine = "my" + "-long-secret-value-" + "1234"
    (src / "s1.jsonl").write_text(json.dumps({"m": f"token {tok} and {mine} and Bearer " + "x" * 24}) + "\n")
    out = S.copy_session_logs(ws, tmp_path / "trace", home=home, values=[mine])
    text = (tmp_path / "trace" / "claude-session" / "s1.jsonl").read_text()
    assert out == ["s1.jsonl"] and "[REDACTED]" in text and tok not in text and mine not in text and "x" * 24 not in text


def test_no_session_dir_gives_an_empty_list(tmp_path):
    assert S.copy_session_logs(tmp_path / "none", tmp_path / "t", home=tmp_path / "h") == []


def test_oauth_token_survives_the_cleaned_environment_of_claude_p(monkeypatch):
    import subprocess
    from builder.template_cc import llm
    seen = {}

    def fake_run(cmd, **kw):
        seen["env"] = kw["env"]
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "dummy-value-not-a-key")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    try:
        llm._claude_cli("s", "u", "sonnet", 100, 5)
    except Exception:  # noqa: BLE001
        pass
    assert seen["env"].get("CLAUDE_CODE_OAUTH_TOKEN") == "dummy-value-not-a-key" and "CLAUDE_CODE_ENTRYPOINT" not in seen["env"]


def test_the_agentic_export_is_committed_under_workflows_and_saved_is_that_path(tmp_path, monkeypatch):
    import builder.build as B
    monkeypatch.setattr(B, "REPO", tmp_path)
    exp = tmp_path / "out" / "slot-x.workflow.json"
    exp.parent.mkdir()
    exp.write_text("{}")
    rep = {"exported": str(exp), "saved": {"workflow_id": "w", "agent_id": "a"}}
    B._commit_export(rep, "slot-x")
    assert rep["saved"] == str(tmp_path / "workflows" / "slot-x.workflow.json") and rep["saved_ids"]["workflow_id"] == "w" and (tmp_path / "workflows" / "slot-x.workflow.json").exists()


def test_sim_gate_waits_while_a_simulation_runs_and_never_cancels(monkeypatch):
    from builder.common import sim_gate as G
    states = iter([[("theirs", 3.0, "abcd1234")], [("theirs", 3.5, "abcd1234")], []])
    monkeypatch.setattr(G, "running_simulations", lambda f: next(states))
    said = []
    assert G.wait_until_idle(object(), sleep=lambda s: None, say=said.append) is True and len(said) == 2 and "ask the other user to pause" in said[0]
    monkeypatch.setattr(G, "running_simulations", lambda f: [("theirs", 1.0, "x")])
    assert G.wait_until_idle(object(), max_wait_s=0, sleep=lambda s: None, say=lambda m: None) is False
    monkeypatch.setattr(G, "running_simulations", lambda f: (_ for _ in ()).throw(RuntimeError("api down")))
    assert G.wait_until_idle(object(), sleep=lambda s: None, say=lambda m: None) is True   # a failing list never stops a build


def test_build_stops_early_without_a_freya_key_and_dotenv_fills_missing_vars(tmp_path, monkeypatch, capsys):
    import builder.build as B
    monkeypatch.setattr(B, "REPO", tmp_path)
    (tmp_path / ".env").write_text("export SOME_TEST_VAR_X=abc\nFREYA_API_KEY=\n# c\n")
    monkeypatch.delenv("SOME_TEST_VAR_X", raising=False)
    monkeypatch.delenv("FREYA_API_KEY", raising=False)
    B._load_dotenv()
    assert B.os.environ.get("SOME_TEST_VAR_X") == "abc" and not B.os.environ.get("FREYA_API_KEY")
    (tmp_path / "b.md").write_text("x")
    (tmp_path / "api.json").write_text('{"openapi": "3.0.0", "paths": {"/a": {}}}')
    assert B.main([str(tmp_path / "b.md"), str(tmp_path / "api.json"), "--variant", "agentic", "--save", "freya"]) == 2
    assert "FREYA_API_KEY is not set" in capsys.readouterr().err
