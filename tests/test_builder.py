from agentforge import llm
from agentforge.build import builder
from agentforge.domain import load_domain


def test_build_agent_merges_tool_descriptions(monkeypatch):
    seen = {}

    def fake_call_llm(system, user, model=None, json_schema=None, temperature=0.2, max_tokens=4096):
        seen["system"], seen["user"], seen["schema"] = system, user, json_schema
        return {
            "system_prompt": "Sen bir kasko asistanısın.\nKesin kurallar: ...",
            "first_message": "Merhaba, ben yapay zeka asistanıyım. Size nasıl yardımcı olabilirim?",
            "tool_descriptions": {"get_policy": "Sadece kimlik doğrulandıktan sonra çağır."},
        }

    monkeypatch.setattr(llm, "call_llm", fake_call_llm)
    task_md, tools = load_domain("kasko")
    cfg = builder.build_agent(task_md, tools, model="anthropic:test")

    assert cfg.version_label == "v1" and cfg.parent_version is None
    assert "yapay zeka" in cfg.first_message
    by_name = {t.name: t for t in cfg.tools}
    assert by_name["get_policy"].description.startswith("Sadece kimlik")
    assert by_name["verify_identity"].description == tools[0].description
    assert "Kesin kurallar" in seen["system"] and "verify_identity" in seen["user"]
    assert seen["schema"]["required"] == ["system_prompt", "first_message", "tool_descriptions"]


def test_cli_saves_agent(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        llm,
        "call_llm",
        lambda *a, **k: {"system_prompt": "p", "first_message": "Merhaba", "tool_descriptions": {}},
    )
    monkeypatch.setattr(builder, "RUNS_DIR", tmp_path)
    builder.main(["domain/kasko"])
    assert (tmp_path / "v1" / "agent.json").exists()
    assert "system prompt" in capsys.readouterr().out
