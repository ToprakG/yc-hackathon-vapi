import json

import httpx

from agentforge import llm
from agentforge.platform import vapi as vapi_mod
from agentforge.platform.vapi import VapiPlatform
from agentforge.schemas import AgentConfig, Persona, ToolDef, Turn, UnitTest

TOOL = ToolDef(
    name="get_policy",
    description="Poliçe getirir.",
    parameters={"type": "object", "properties": {"policy_number": {"type": "string"}}},
)
CFG = AgentConfig(version_label="v1", system_prompt="SYS", first_message="Merhaba", tools=[TOOL], model="openai:gpt-4o-mini")
PERSONA = Persona(name="Ali Bey", prompt="Poliçeni sor.", successCriteria="x", tags=["train"])


def make_platform(monkeypatch, tmp_path, handler):
    monkeypatch.setenv("TOOLS_BASE_URL", "https://tools.example.com")
    monkeypatch.setenv("VAPI_API_KEY", "k")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return VapiPlatform(client=client, log_path=tmp_path / "log.jsonl", sleep=lambda s: None)


def test_to_vapi_json(monkeypatch, tmp_path):
    platform = make_platform(monkeypatch, tmp_path, lambda r: httpx.Response(200, json={}))
    body = platform.to_vapi_json(CFG, session_id="s1")
    assert body["firstMessage"] == "Merhaba"
    assert body["model"]["provider"] == "openai" and body["model"]["model"] == "gpt-4o-mini"
    assert body["model"]["messages"][0] == {"role": "system", "content": "SYS"}
    tool = body["model"]["tools"][0]
    assert tool["function"]["name"] == "get_policy"
    assert tool["server"]["url"] == "https://tools.example.com/tools/get_policy?session_id=s1"
    assert body["metadata"]["session_id"] == "s1"


def test_conversation_ends_on_end_token(monkeypatch, tmp_path):
    caller_lines = iter(["Poliçe numaram KSK-1.", "Teşekkürler, hoşça kalın. [END]"])
    monkeypatch.setattr(llm, "call_llm", lambda *a, **k: next(caller_lines))
    chat_bodies = []

    def handler(request: httpx.Request):
        if request.url.path == "/chat":
            chat_bodies.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "id": f"chat{len(chat_bodies)}",
                    "cost": 0.01,
                    "output": [
                        {"role": "assistant", "content": "", "tool_calls": [
                            {"id": "c1", "type": "function", "function": {"name": "get_policy", "arguments": '{"policy_number": "KSK-1"}'}}
                        ]},
                        {"role": "tool", "tool_call_id": "c1", "content": '{"ok": true}'},
                        {"role": "assistant", "content": "Poliçeniz aktif."},
                    ],
                },
            )
        if request.url.path.startswith("/calls/"):
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    run = make_platform(monkeypatch, tmp_path, handler).run_conversation(CFG, PERSONA, run_idx=2)
    assert run.ended_reason == "caller-ended"
    assert len(chat_bodies) == 1 and "previousChatId" not in chat_bodies[0]
    assert [t.role for t in run.transcript] == ["assistant", "user", "assistant", "tool", "assistant", "user"]
    assert run.transcript[-1].text == "Teşekkürler, hoşça kalın."
    assert run.tool_calls[0].name == "get_policy" and run.tool_calls[0].args == {"policy_number": "KSK-1"}
    assert run.tool_calls[0].result == {"ok": True}
    assert run.cost_usd == 0.01 and run.run_idx == 2
    assert (tmp_path / "log.jsonl").exists()


def test_tool_server_log_fills_missing_calls(monkeypatch, tmp_path):
    lines = iter(["Merhaba", "[END]"])
    monkeypatch.setattr(llm, "call_llm", lambda *a, **k: next(lines))

    def handler(request):
        if request.url.path == "/chat":
            return httpx.Response(200, json={"id": "c", "output": [{"role": "assistant", "content": "Tamam."}]})
        return httpx.Response(200, json=[{"session_id": "s", "name": "get_policy", "args": {"policy_number": "X"}, "result": {"ok": 1}}])

    run = make_platform(monkeypatch, tmp_path, handler).run_conversation(CFG, PERSONA, 0)
    assert [c.name for c in run.tool_calls] == ["get_policy"]


def test_retries_on_429(monkeypatch, tmp_path):
    attempts = []

    def handler(request):
        attempts.append(1)
        return httpx.Response(429) if len(attempts) < 3 else httpx.Response(200, json={"id": "a1"})

    platform = make_platform(monkeypatch, tmp_path, handler)
    assert platform.upsert_agent(CFG) == "a1"
    assert len(attempts) == 3


def test_unit_test_polls_until_ended(monkeypatch, tmp_path):
    polls = {"n": 0}
    created = []

    def handler(request: httpx.Request):
        path = request.url.path
        if path == "/eval":
            created.append(json.loads(request.content))
            return httpx.Response(200, json={"id": f"e{len(created)}"})
        if path == "/eval/run" and request.method == "POST":
            body = json.loads(request.content)
            assert body["target"]["type"] == "assistant" and "assistant" in body["target"]
            return httpx.Response(200, json={"id": "r1"})
        if path == "/eval/run/r1":
            polls["n"] += 1
            if polls["n"] % 2:
                return httpx.Response(200, json={"status": "queued"})
            return httpx.Response(200, json={"status": "ended", "endedReason": "mockConversation.done", "results": [{"status": "pass", "messages": []}]})
        return httpx.Response(404)

    test = UnitTest(
        name="asks-identity",
        prefix_turns=[Turn(role="assistant", text="Merhaba", turn_idx=0), Turn(role="user", text="Poliçem ne?", turn_idx=1)],
        expectation="Asks for TCKN last 4 before any policy info.",
        tool_assertions=[{"tool": "verify_identity", "negate": False}, {"tool": "get_policy", "negate": True}],
    )
    verdict = make_platform(monkeypatch, tmp_path, handler).run_unit_test(CFG, test)
    assert verdict.passed
    assert created[0]["type"] == "chat.mockConversation"
    assert created[0]["messages"][-1]["judgePlan"]["type"] == "exact"
    assert created[1]["messages"][-1]["judgePlan"]["type"] == "ai"
    assert "must NOT call the tool get_policy" in created[1]["messages"][-1]["judgePlan"]["model"]["messages"][0]["content"]


def test_unit_test_error_ended_reason(monkeypatch, tmp_path):
    def handler(request):
        if request.url.path == "/eval":
            return httpx.Response(200, json={"id": "e"})
        if request.method == "POST":
            return httpx.Response(200, json={"id": "r"})
        return httpx.Response(200, json={"status": "ended", "endedReason": "assistant-error"})

    test = UnitTest(name="t", prefix_turns=[Turn(role="user", text="x")], expectation="y")
    verdict = make_platform(monkeypatch, tmp_path, handler).run_unit_test(CFG, test)
    assert not verdict.passed and verdict.reason.startswith("ai: ERROR")


def test_mock_messages_tool_calls():
    msgs = vapi_mod.mock_messages([Turn(role="assistant", text="", tool_calls=[{"name": "get_policy", "args": {"a": 1}}], turn_idx=3)])
    assert msgs[0]["tool_calls"][0]["function"] == {"name": "get_policy", "arguments": '{"a": 1}'}
