"""Freya adapter. Mapping and open questions are in docs/freya_port.md.

Endpoints come from the full spec at https://staging-app.freyavoice.ai/api/openapi.json
(the docs' openapi.json is an older subset without chat, personas, simulations, unit tests or branches).
"""

from __future__ import annotations

import copy
import json
import os
import time
from typing import Any

import httpx

from agentforge import llm
from agentforge.config import settings, split_model
from agentforge.platform.base import Platform
from agentforge.schemas import (
    AgentConfig,
    Assertion,
    ExtractionEvent,
    Persona,
    RunResult,
    ToolCallRecord,
    Turn,
    UnitTest,
    Verdict,
)

DEFAULT_BASE_URL = "https://app.freyavoice.ai/api/v2"
MAX_TURNS = 20
END_TOKEN = "[END]"
UNIT_TEST_DEADLINE_S = 120
ANALYSIS_DEADLINE_S = 60
SIMULATION_DEADLINE_S = 1800
RETRY_STATUSES = {429, 500, 502, 503, 504}
TRANSFER_TOOLS = {"transfer_to_human", "transferCall"}

SIMULATOR_PROMPT = (
    "You are a phone caller. Stay in character.\n"
    "Follow this persona: {persona}\n"
    "Speak Turkish, short spoken sentences. When your goal is done or the agent transfers you, "
    "say a goodbye and output [END]."
)

# Freya's extraction_schema types.
EXTRACTION_TYPES = {
    "str": "string",
    "string": "string",
    "int": "integer",
    "integer": "integer",
    "number": "float",
    "float": "float",
    "bool": "boolean",
    "boolean": "boolean",
    "date": "date",
    "datetime": "datetime",
    "enum": "enum",
}


class FreyaError(RuntimeError):
    pass


class FreyaPlatform(Platform):
    def __init__(
        self,
        client: httpx.Client | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        workspace_id: str | None = None,
        sleep=time.sleep,
    ):
        self.api_key = api_key if api_key is not None else os.environ.get("FREYA_API_KEY", "").strip()
        self.base_url = (base_url or os.environ.get("FREYA_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.workspace_id = workspace_id if workspace_id is not None else os.environ.get("FREYA_WORKSPACE_ID", "").strip()
        self.tools_base_url = settings().tools_base_url
        self.simulator_model = settings().simulator_model
        self.client = client or httpx.Client(timeout=90)
        self.sleep = sleep
        self.agent_id: str | None = None
        self.version_ids: dict[str, str] = {}
        self.branch_ids: dict[str, str] = {}
        self.unit_test_ids: dict[str, str] = {}
        self._defaults: dict[str, Any] | None = None

    # --- Platform -----------------------------------------------------------------------------

    def upsert_agent(self, cfg: AgentConfig) -> str:
        """Return the Freya *version* id for cfg.version_label.

        The first config creates the agent (its first version is the mainline head). Every later
        label becomes a branch forked from its parent's version, so candidates never touch mainline
        until promote() merges them.
        """
        if cfg.version_label in self.version_ids:
            return self.version_ids[cfg.version_label]
        config = self.agent_config(cfg)
        if self.agent_id is None:
            result = self._request(
                "POST", "/agents", {"name": f"agentforge-{cfg.version_label}", "language": "tr", "config": config}
            )
            self.agent_id = result["agent"]["id"]
            self.version_ids[cfg.version_label] = self._head_version_id()
        else:
            body: dict[str, Any] = {
                "entityType": "agent",
                "entityId": self.agent_id,
                "name": cfg.version_label,
                "config": config,
                "description": cfg.notes[:500],
            }
            parent = self.version_ids.get(cfg.parent_version or "")
            if parent:
                body["baseVersionId"] = parent
            result = self._request("POST", "/branches", body)
            self.branch_ids[cfg.version_label] = result["branchId"]
            self.version_ids[cfg.version_label] = result["headVersionId"]
        return self.version_ids[cfg.version_label]

    def run_conversation(self, cfg: AgentConfig, persona: Persona, run_idx: int) -> RunResult:
        version_id = self.upsert_agent(cfg)
        simulator_system = SIMULATOR_PROMPT.format(persona=persona.prompt)
        # TODO(ask-organizers): POST /chat/message needs a non-empty caller message, so Freya's own
        # greeting is never returned to us. We record cfg.first_message as turn 0 and let the caller reply to it.
        transcript = [Turn(role="assistant", text=cfg.first_message, turn_idx=0)]
        call_id: str | None = None
        ended_reason = "max-turns"
        started = time.monotonic()

        for _ in range(MAX_TURNS):
            caller_text = str(
                llm.call_llm(simulator_system, _caller_view(transcript), model=self.simulator_model, temperature=0.7)
            ).strip()
            finished = END_TOKEN in caller_text
            caller_text = caller_text.replace(END_TOKEN, "").strip()
            if caller_text:
                transcript.append(Turn(role="user", text=caller_text, turn_idx=len(transcript)))
            if finished:
                ended_reason = "caller-ended"
                break
            body: dict[str, Any] = {"message": caller_text or "..."}
            if call_id:
                body["callId"] = call_id
            else:
                body.update({"agentId": self.agent_id, "versionId": version_id})
            try:
                reply = self._request("POST", "/chat/message", body)
            except FreyaError as error:
                ended_reason = f"error: {error}"[:300]
                break
            call_id = reply.get("callId") or call_id
            if reply.get("response"):
                transcript.append(Turn(role="assistant", text=reply["response"], turn_idx=len(transcript)))
            if reply.get("endedByAgent"):
                ended_reason = "agent-ended"
                break

        raw: dict[str, Any] = {"call_id": call_id, "version_id": version_id}
        tool_calls: list[ToolCallRecord] = []
        extraction: list[ExtractionEvent] = []
        cost = None
        if call_id:
            raw["chat_end"] = self._request("POST", "/chat/end", {"callId": call_id})
            call = self._wait_for_analysis(call_id)
            raw["freya_call"] = call
            raw["freya_close"] = {
                "assertionResults": call.get("assertionResults"),
                "successCriteriaResult": call.get("successCriteriaResult"),
                "assertionsSummary": call.get("assertionsSummary"),
            }
            tool_calls = parse_tool_calls(call)
            extraction = parse_extraction(call)
            cost = call.get("cost") if isinstance(call.get("cost"), (int, float)) else None
            if any(record.name in TRANSFER_TOOLS for record in tool_calls) and ended_reason == "agent-ended":
                ended_reason = "transfer"
        return RunResult(
            persona_name=persona.name,
            agent_version=cfg.version_label,
            run_idx=run_idx,
            mode="chat",
            transcript=transcript,
            tool_calls=tool_calls,
            extraction_events=extraction,
            ended_reason=ended_reason,
            duration_s=round(time.monotonic() - started, 2),
            cost_usd=cost,
            raw=raw,
        )

    def run_unit_test(self, cfg: AgentConfig, test: UnitTest) -> Verdict:
        version_id = self.upsert_agent(cfg)
        test_id = self.unit_test_ids.get(test.name)
        if test_id is None:
            created = self._request("POST", "/unit-tests", self.unit_test_body(test, version_id))
            test_id = created["id"]
            self.unit_test_ids[test.name] = test_id
        enqueued = self._request(
            "POST",
            "/unit-tests/run-all",
            {
                "workspaceId": self.workspace_id,
                "entityType": "agent",
                "entityId": self.agent_id,
                "entityVersionId": version_id,
                "unitTestIds": [test_id],
            },
        )
        run_ids = [run_id for item in enqueued.get("enqueued", []) for run_id in item.get("runIds", [])]
        if not run_ids:
            return Verdict(check_name=test.name, passed=False, reason=f"ERROR: run not enqueued ({enqueued.get('skipped')})")
        deadline = time.monotonic() + UNIT_TEST_DEADLINE_S
        while True:
            run = self._request("GET", f"/unit-tests/runs/{run_ids[0]}")
            outcome = run.get("outcome")
            if outcome in {"pass", "fail"}:
                return Verdict(check_name=test.name, passed=outcome == "pass", reason=run.get("verdictReason") or "")
            if outcome == "error":
                return Verdict(check_name=test.name, passed=False, reason=f"ERROR: {run.get('verdictReason')}")
            if time.monotonic() > deadline:
                return Verdict(check_name=test.name, passed=False, reason=f"ERROR: timed out in state {outcome}")
            self.sleep(2)

    # --- Promotion (gate decisions) -----------------------------------------------------------

    def promote(self, cfg: AgentConfig, publish: bool = True) -> dict[str, Any]:  # type: ignore[override]
        """COMMIT: merge the candidate's branch onto mainline (POST /branches/{id}/rebase)."""
        branch_id = self.branch_ids[cfg.version_label]
        result = self._request("POST", f"/branches/{branch_id}/rebase", {"publish": publish})
        if result.get("conflicts"):
            raise FreyaError(f"merge conflicts for {cfg.version_label}: {result['conflicts']}")
        if result.get("newVersionId"):
            self.version_ids[cfg.version_label] = result["newVersionId"]
        return result

    def discard(self, cfg: AgentConfig) -> dict[str, Any]:  # type: ignore[override]
        """DISCARD: mark the candidate's branch discarded."""
        return self._request("POST", f"/branches/{self.branch_ids[cfg.version_label]}/discard", {})

    # --- Native simulations -------------------------------------------------------------------

    def upload_personas(self, personas: list[Persona], agent_ids: list[str] | None = None) -> list[str]:
        """POST /personas with our Freya-format personas unchanged. Returns persona ids in order."""
        items = []
        for persona in personas:
            item = persona.model_dump(exclude_none=True)
            if agent_ids or self.agent_id:
                item["agentIds"] = agent_ids or [self.agent_id]
            items.append(item)
        result = self._request("POST", "/personas", {"personas": items})
        return [persona["id"] for persona in result["personas"]]

    def upload_assertions(self, assertions: list[Assertion]) -> list[str]:
        # TODO(ask-organizers): POST /simulations takes assertion UUIDs, but the spec has no endpoint
        # that creates an assertion. Until they tell us how, pass existing ids to run_native_simulation.
        raise NotImplementedError("Freya has no documented endpoint to create assertions")

    def run_native_simulation(
        self,
        cfg: AgentConfig,
        persona_ids: list[str],
        assertion_ids: list[str] | None = None,
        mode: str = "chat",
        runs_per_persona: int = 3,
        name: str | None = None,
        wait: bool = True,
    ) -> dict[str, Any]:
        """Run Freya's own simulator + judge. Returns the simulation and its latest iteration."""
        version_id = self.upsert_agent(cfg)
        body: dict[str, Any] = {
            "name": name or f"agentforge-{cfg.version_label}",
            "agentId": self.agent_id,
            "agentVersionId": version_id,
            "mode": mode,
            "selectedPersonaIds": persona_ids,
            "runsPerPersona": runs_per_persona,
            "start": True,
        }
        if assertion_ids:
            body["assertions"] = assertion_ids
        simulation = self._request("POST", "/simulations", body)["simulation"]
        deadline = time.monotonic() + SIMULATION_DEADLINE_S
        while wait and simulation.get("status") not in {"completed", "paused"}:
            if time.monotonic() > deadline:
                raise FreyaError(f"simulation {simulation['id']} did not complete")
            self.sleep(10)
            simulation = self._request("GET", f"/simulations/{simulation['id']}")["simulation"]
        iterations = self._request("GET", f"/simulations/{simulation['id']}/iterations", params={"limit": 1})
        latest = (iterations.get("iterations") or [None])[0]
        return {"simulation": simulation, "iteration": latest}

    # --- Mapping ------------------------------------------------------------------------------

    def agent_config(self, cfg: AgentConfig) -> dict[str, Any]:
        """AgentConfig -> Freya agent config, layered on GET /agents/defaults for tts/stt/compliance."""
        config = copy.deepcopy(self._default_config())
        provider, model = split_model(cfg.model)
        llm_config = config.setdefault("llmConfig", {})
        llm_config.update(
            {
                "provider": provider,
                "model": model,
                "systemPrompt": cfg.system_prompt,
                "firstMessage": cfg.first_message,
                "firstMessageMode": "assistant-speaks-first",
                "tools": [self.tool_json(tool) for tool in cfg.tools],
            }
        )
        return config

    def tool_json(self, tool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": tool.name,
                # TODO(ask-organizers): `handler` is required but undocumented. We assume a webhook URL.
                "handler": f"{self.tools_base_url}/tools/{tool.name}" if self.tools_base_url else tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        if tool.extraction_schema:
            body["extraction_schema"] = [
                {
                    "name": field.name,
                    "type": EXTRACTION_TYPES.get(field.type.lower(), "string"),
                    "description": field.description,
                    "required": field.required,
                }
                for field in tool.extraction_schema
            ]
        return body

    def unit_test_body(self, test: UnitTest, version_id: str) -> dict[str, Any]:
        messages = [
            # TODO(ask-organizers): role names for tool turns in unit-test input are not documented.
            {"role": turn.role, "message": turn.text}
            for turn in test.prefix_turns
            if turn.text
        ]
        assertions = [
            {
                "type": "tool_call",
                "tool": assertion.tool,
                **({"args": assertion.args, "argsMatch": "subset"} if assertion.args else {}),
                "negate": assertion.negate,
            }
            for assertion in test.tool_assertions
        ]
        return {
            "workspaceId": self.workspace_id,
            "entityType": "agent",
            "entityId": self.agent_id,
            "name": test.name,
            "expectation": test.expectation,
            "assertions": assertions,
            "input": {
                "schemaVersion": 1,
                "callType": "web",
                "messages": messages,
                "authoredAgainstVersionId": version_id,
            },
            "judgeContext": {"includeToolCalls": True, "includeExtractionEvents": True},
        }

    # --- HTTP ---------------------------------------------------------------------------------

    def _default_config(self) -> dict[str, Any]:
        if self._defaults is None:
            self._defaults = self._request("GET", "/agents/defaults", params={"language": "tr"})["config"]
        return self._defaults

    def _head_version_id(self) -> str:
        result = self._request("GET", f"/versions/agent/{self.agent_id}", params={"entityId": self.agent_id})
        versions = result.get("versions") or []
        if not versions:
            raise FreyaError(f"agent {self.agent_id} has no versions")
        return max(versions, key=lambda version: version.get("versionNumber", 0))["id"]

    def _wait_for_analysis(self, call_id: str) -> dict[str, Any]:
        """POST /chat/end runs analysis async; poll GET /call/{id} until assertion results appear."""
        deadline = time.monotonic() + ANALYSIS_DEADLINE_S
        while True:
            call = self._request("GET", f"/call/{call_id}")["call"]
            if call.get("assertionResults") or call.get("successCriteriaResult") or time.monotonic() > deadline:
                return call
            self.sleep(3)

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None, params: dict[str, Any] | None = None
    ) -> Any:
        if not self.api_key:
            raise FreyaError("FREYA_API_KEY is not set")
        query = dict(params or {})
        if self.workspace_id:
            query.setdefault("workspaceId", self.workspace_id)
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        for attempt in range(5):
            response = self.client.request(method, f"{self.base_url}{path}", json=body, params=query, headers=headers)
            if response.status_code in RETRY_STATUSES and attempt < 4:
                self.sleep(2**attempt)
                continue
            return unwrap(response, f"{method} {path}")
        raise FreyaError("unreachable")


def unwrap(response: httpx.Response, label: str) -> Any:
    """Return data.result from Freya's {success, data: {message, result}} envelope."""
    try:
        payload = response.json()
    except ValueError:
        raise FreyaError(f"{label} -> {response.status_code}: {response.text[:500]}") from None
    if response.status_code >= 400 or not isinstance(payload, dict) or payload.get("success") is False:
        message = payload.get("data", {}).get("message") if isinstance(payload, dict) else None
        raise FreyaError(f"{label} -> {response.status_code}: {message or str(payload)[:500]}")
    data = payload.get("data")
    if isinstance(data, dict) and "result" in data:
        return data["result"]
    return payload


def parse_tool_calls(call: dict[str, Any]) -> list[ToolCallRecord]:
    """Pull tool calls out of GET /call/{id}.

    TODO(ask-organizers): the spec types call.messages as {role, message, ...} and leaves `artifact`
    untyped, so tool calls have no documented home. We accept the OpenAI/Vapi-like shapes we expect.
    """
    records: list[ToolCallRecord] = []
    messages = list(call.get("messages") or [])
    artifact = call.get("artifact")
    if isinstance(artifact, dict):
        messages += list(artifact.get("messages") or [])
        messages += [{"toolCalls": artifact["toolCalls"]}] if isinstance(artifact.get("toolCalls"), list) else []
    for idx, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        for item in message.get("toolCalls") or message.get("tool_calls") or []:
            if not isinstance(item, dict):
                continue
            function = item.get("function") if isinstance(item.get("function"), dict) else item
            name = function.get("name")
            if not name:
                continue
            args = function.get("arguments") or function.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {"raw": args}
            records.append(
                ToolCallRecord(name=name, args=args if isinstance(args, dict) else {"value": args}, result=item.get("result"), turn_idx=idx)
            )
    return records


def parse_extraction(call: dict[str, Any]) -> list[ExtractionEvent]:
    """call.insights is a free-form {field: value} map; turn indexes are not available."""
    insights = call.get("insights")
    if not isinstance(insights, dict):
        return []
    return [ExtractionEvent(field=field, value=value) for field, value in insights.items()]


def _caller_view(transcript: list[Turn]) -> str:
    lines = [f"{'AGENT' if turn.role == 'assistant' else 'YOU'}: {turn.text}" for turn in transcript if turn.role != "tool"]
    return "Conversation so far:\n" + "\n".join(lines) + "\n\nReply with your next line as the caller only."
