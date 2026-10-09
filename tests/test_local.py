"""LocalPlatform with a scripted OpenAI client and simulator; no network."""

from types import SimpleNamespace as NS

from agentforge import llm
from agentforge.platform.local import LocalPlatform, prefix_messages
from agentforge.schemas import AgentConfig, Persona, ToolDef, Turn, UnitTest


def reply(content=None, calls=None):
    tool_calls = [NS(id=f"c{i}", function=NS(name=n, arguments=a)) for i, (n, a) in enumerate(calls or [])]
    message = NS(content=content, tool_calls=tool_calls or None)
    return NS(choices=[NS(message=message)], usage=NS(prompt_tokens=100, completion_tokens=20))


class ScriptedClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.replies.pop(0)


CFG = AgentConfig(version_label="v1", system_prompt="Sigorta asistanı.", first_message="Merhaba, yapay zeka asistanıyım.",
                  tools=[ToolDef(name="verify_identity", description="d")], model="openai:gpt-4o-mini")


def test_conversation_runs_tools_in_process(monkeypatch):
    lines = iter(["Kimliğimi doğrula: 8904, 1985-03-14.", "Teşekkürler [END]"])
    monkeypatch.setattr(llm, "call_llm", lambda *a, **k: next(lines))
    client = ScriptedClient([reply(calls=[("verify_identity", '{"tckn_last4": "8904"}')]), reply("Doğrulandı.")])
    seen = []
    platform = LocalPlatform(run_tool=lambda sid, name, args: seen.append((name, args)) or {"verified": True}, client=client)

    run = platform.run_conversation(CFG, Persona(name="p", prompt="x", successCriteria="y"), 0)

    assert seen == [("verify_identity", {"tckn_last4": "8904"})]
    assert [c.name for c in run.tool_calls] == ["verify_identity"]
    assert run.ended_reason == "caller-ended"
    assert [t.role for t in run.transcript] == ["assistant", "user", "assistant", "tool", "assistant", "user"]
    assert len(client.requests) == 2 and any(m["role"] == "tool" for m in client.requests[1]["messages"])


def test_unit_test_checks_tool_assertions(monkeypatch):
    monkeypatch.setattr(llm, "call_llm", lambda *a, **k: {"passed": True, "reason": "ok"})
    test = UnitTest(name="t", prefix_turns=[Turn(role="user", text="Poliçemi söyle", turn_idx=1)],
                    expectation="asks for identity", tool_assertions=[{"tool": "get_policy", "negate": True}])
    bad = LocalPlatform(run_tool=lambda *a: {}, client=ScriptedClient([reply(calls=[("get_policy", "{}")]), reply("Tamam")]))
    good = LocalPlatform(run_tool=lambda *a: {}, client=ScriptedClient([reply("Önce kimliğinizi doğrulayalım.")]))
    assert bad.run_unit_test(CFG, test).passed is False
    assert good.run_unit_test(CFG, test).passed is True


def test_prefix_messages_pairs_tool_results():
    turns = [Turn(role="assistant", text="", tool_calls=[{"name": "get_policy", "args": {"p": 1}}], turn_idx=2),
             Turn(role="tool", text='{"ok": true}', turn_idx=3)]
    msgs = prefix_messages(turns)
    assert msgs[1]["tool_call_id"] == msgs[0]["tool_calls"][0]["id"]
