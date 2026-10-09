import json

import httpx
import pytest

from agentforge import llm
from agentforge.platform.freya import FreyaError, FreyaPlatform, parse_tool_calls, unwrap
from agentforge.schemas import AgentConfig, ExtractionField, Persona, ToolDef, Turn, UnitTest


def ok(result, status=200):
    return httpx.Response(status, json={"success": True, "data": {"message": "Success", "result": result}})


def make_platform(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return FreyaPlatform(client=client, api_key="k", base_url="https://freya.test/api/v2", workspace_id="ws", sleep=lambda s: None)


def config(label="v1", parent=None):
    tool = ToolDef(
        name="create_claim",
        description="Create a claim.",
        parameters={"type": "object", "properties": {"injury": {"type": "boolean"}}},
        extraction_schema=[ExtractionField(name="injury", type="bool", required=True)],
    )
    return AgentConfig(
        version_label=label, system_prompt="Sen bir sigorta asistanısın.", first_message="Merhaba, ben yapay zeka asistanıyım.",
        tools=[tool], model="openai:gpt-4o-mini", parent_version=parent,
    )


class Recorder:
    """Routes requests by (method, path) and records them."""

    def __init__(self, routes):
        self.routes = routes
        self.calls: list[tuple[str, str, dict, dict]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v2")
        body = json.loads(request.content) if request.content else {}
        self.calls.append((request.method, path, body, dict(request.url.params)))
        route = self.routes[(request.method, path)]
        return route(body) if callable(route) else route

    def bodies(self, method, path):
        return [body for m, p, body, _ in self.calls if (m, p) == (method, path)]


def test_unwrap_envelope_and_errors():
    assert unwrap(ok({"a": 1}), "GET /x") == {"a": 1}
    with pytest.raises(FreyaError, match="bad token"):
        unwrap(httpx.Response(401, json={"success": False, "data": {"message": "bad token", "result": None}}), "GET /x")
    with pytest.raises(FreyaError):
        unwrap(httpx.Response(200, json={"success": False, "data": {"message": "nope", "result": None}}), "GET /x")


def test_retries_on_429():
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(429, json={"success": False, "data": {"message": "slow down"}})
        return ok({"config": {"llmConfig": {}}})

    platform = make_platform(handler)
    assert platform._request("GET", "/agents/defaults") == {"config": {"llmConfig": {}}}
    assert len(attempts) == 3


def test_upsert_caches_and_branches_candidates():
    routes = Recorder(
        {
            ("GET", "/agents/defaults"): ok({"config": {"llmConfig": {"temperature": 0.3}, "ttsConfig": {"provider": "x", "voiceId": "y"}}}),
            ("POST", "/agents"): ok({"agent": {"id": "agent-1"}}, 201),
            ("GET", "/versions/agent/agent-1"): ok({"versions": [{"id": "ver-1", "versionNumber": 1}, {"id": "ver-0", "versionNumber": 0}]}),
            ("POST", "/branches"): ok({"success": True, "branchId": "br-2", "branchName": "v2", "headVersionId": "ver-2", "headVersionNumber": 2}),
            ("POST", "/branches/br-2/rebase"): ok({"success": True, "newVersionId": "ver-3", "conflicts": []}),
        }
    )
    platform = make_platform(routes)

    assert platform.upsert_agent(config()) == "ver-1"
    assert platform.upsert_agent(config()) == "ver-1"
    assert len(routes.bodies("POST", "/agents")) == 1
    agent_body = routes.bodies("POST", "/agents")[0]
    llm_config = agent_body["config"]["llmConfig"]
    assert llm_config["systemPrompt"].startswith("Sen bir")
    assert llm_config["provider"] == "openai" and llm_config["model"] == "gpt-4o-mini"
    assert llm_config["temperature"] == 0.3  # defaults survive
    assert agent_body["config"]["ttsConfig"]["voiceId"] == "y"
    assert llm_config["tools"][0]["extraction_schema"][0]["type"] == "boolean"
    assert all(params.get("workspaceId") == "ws" for *_, params in routes.calls)

    candidate = config("v2", parent="v1")
    assert platform.upsert_agent(candidate) == "ver-2"
    assert routes.bodies("POST", "/branches")[0]["baseVersionId"] == "ver-1"
    platform.promote(candidate)
    assert platform.version_ids["v2"] == "ver-3"


def test_conversation_loop(monkeypatch):
    caller_lines = iter(["Merhaba, kaza yaptım.", "Teşekkürler, hoşça kalın. [END]"])
    monkeypatch.setattr(llm, "call_llm", lambda *args, **kwargs: next(caller_lines))
    call_details = {
        "call": {
            "id": "call-1",
            "workspaceId": "ws",
            "cost": 0.02,
            "messages": [{"role": "assistant", "message": "x", "toolCalls": [{"function": {"name": "create_claim", "arguments": '{"injury": false}'}}]}],
            "insights": {"injury": False},
            "assertionResults": [{"name": "no_pii", "success": True, "reason": "fine"}],
            "successCriteriaResult": {"success": True},
        }
    }
    routes = Recorder(
        {
            ("GET", "/agents/defaults"): ok({"config": {"llmConfig": {}}}),
            ("POST", "/agents"): ok({"agent": {"id": "agent-1"}}, 201),
            ("GET", "/versions/agent/agent-1"): ok({"versions": [{"id": "ver-1", "versionNumber": 1}]}),
            ("POST", "/chat/message"): ok({"response": "Geçmiş olsun. Kimliğinizi doğrulayayım.", "callId": "call-1", "messageId": "m1"}),
            ("POST", "/chat/end"): ok({"callId": "call-1", "ended": True, "endedReason": "closed"}),
            ("GET", "/call/call-1"): ok(call_details),
        }
    )
    platform = make_platform(routes)
    persona = Persona(name="kaza", prompt="Ben Ayşe, küçük bir kaza yaptım.", successCriteria="Hasar kaydı açılır.", tags=["train"])

    run = platform.run_conversation(config(), persona, run_idx=0)

    assert [turn.role for turn in run.transcript] == ["assistant", "user", "assistant", "user"]
    assert run.ended_reason == "caller-ended"
    first, *_ = routes.bodies("POST", "/chat/message")
    assert first["agentId"] == "agent-1" and first["versionId"] == "ver-1"
    assert routes.bodies("POST", "/chat/end") == [{"callId": "call-1"}]
    assert run.raw["freya_close"]["assertionResults"][0]["success"] is True
    assert run.tool_calls[0].name == "create_claim" and run.tool_calls[0].args == {"injury": False}
    assert run.extraction_events[0].field == "injury"
    assert run.cost_usd == 0.02


def test_unit_test_runs_and_polls():
    outcomes = iter(["queued", "running", "fail"])
    routes = Recorder(
        {
            ("GET", "/agents/defaults"): ok({"config": {"llmConfig": {}}}),
            ("POST", "/agents"): ok({"agent": {"id": "agent-1"}}, 201),
            ("GET", "/versions/agent/agent-1"): ok({"versions": [{"id": "ver-1", "versionNumber": 1}]}),
            ("POST", "/unit-tests"): ok({"id": "ut-1"}, 201),
            ("POST", "/unit-tests/run-all"): ok({"enqueued": [{"unitTestId": "ut-1", "runIds": ["run-1"], "jobIds": ["j"]}], "skipped": []}, 202),
            ("GET", "/unit-tests/runs/run-1"): lambda body: ok({"id": "run-1", "outcome": next(outcomes), "verdictReason": "called get_policy first"}),
        }
    )
    platform = make_platform(routes)
    test = UnitTest(
        name="verify-before-policy",
        prefix_turns=[Turn(role="assistant", text="Merhaba"), Turn(role="user", text="Poliçemi söyler misiniz?")],
        expectation="Asks for TCKN last 4 and birth date before any policy info.",
        tool_assertions=[{"tool": "get_policy", "negate": True}],
    )

    verdict = platform.run_unit_test(config(), test)

    assert verdict.passed is False and "get_policy" in verdict.reason
    created = routes.bodies("POST", "/unit-tests")[0]
    assert created["input"]["messages"][1] == {"role": "user", "message": "Poliçemi söyler misiniz?"}
    assert created["assertions"] == [{"type": "tool_call", "tool": "get_policy", "negate": True}]
    assert routes.bodies("POST", "/unit-tests/run-all")[0]["entityVersionId"] == "ver-1"


def test_upload_personas_unchanged():
    routes = Recorder({("POST", "/personas"): ok({"personas": [{"id": "p-1"}]}, 201)})
    platform = make_platform(routes)
    persona = Persona(name="kaza", prompt="Ben Ayşe.", successCriteria="Hasar kaydı açılır.", tags=["blind"])
    assert platform.upload_personas([persona]) == ["p-1"]
    sent = routes.bodies("POST", "/personas")[0]["personas"][0]
    assert sent == {"name": "kaza", "prompt": "Ben Ayşe.", "successCriteria": "Hasar kaydı açılır.", "tags": ["blind"]}


def test_parse_tool_calls_ignores_plain_messages():
    assert parse_tool_calls({"messages": [{"role": "user", "message": "hi"}]}) == []
