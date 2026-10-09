"""Vapi adapter: assistants, our own simulator loop over the Chat API, and unit tests via Evals."""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

import httpx

from agentforge import llm
from agentforge.config import RUNS_DIR, settings, split_model
from agentforge.platform.base import Platform
from agentforge.schemas import (
    AgentConfig,
    Persona,
    RunResult,
    ToolCallRecord,
    Turn,
    UnitTest,
    Verdict,
)
from agentforge.store import append_jsonl

MAX_TURNS = 20
UNIT_TEST_DEADLINE_S = 120
LOG_PATH = RUNS_DIR / "vapi_log.jsonl"
END_TOKEN = "[END]"
TRANSFER_TOOLS = {"transfer_to_human", "transferCall"}

SIMULATOR_PROMPT = (
    "You are a phone caller. Stay in character.\n"
    "Follow this persona: {persona}\n"
    "Speak Turkish, short spoken sentences. When your goal is done or the agent transfers you, "
    "say a goodbye and output [END]."
)


class VapiError(RuntimeError):
    pass


class VapiPlatform(Platform):
    def __init__(self, client: httpx.Client | None = None, log_path=LOG_PATH, sleep=time.sleep):
        cfg = settings()
        self.base_url = cfg.vapi_base_url
        self.tools_base_url = cfg.tools_base_url
        self.simulator_model = cfg.simulator_model
        self.judge_model = cfg.judge_model
        self.api_key = cfg.vapi_api_key
        self.client = client or httpx.Client(timeout=90)
        self.log_path = log_path
        self.sleep = sleep
        self.assistant_ids: dict[str, str] = {}

    # --- Platform -----------------------------------------------------------------------------

    def upsert_agent(self, cfg: AgentConfig) -> str:
        body = self.to_vapi_json(cfg)
        existing = self.assistant_ids.get(cfg.version_label)
        if existing:
            payload = self._request("PATCH", f"/assistant/{existing}", body)
        else:
            payload = self._request("POST", "/assistant", body)
        self.assistant_ids[cfg.version_label] = payload["id"]
        return payload["id"]

    def run_conversation(self, cfg: AgentConfig, persona: Persona, run_idx: int) -> RunResult:
        session_id = f"{cfg.version_label}-{_slug(persona.name)}-{run_idx}-{uuid.uuid4().hex[:8]}"
        assistant = self.to_vapi_json(cfg, session_id=session_id)
        simulator_system = SIMULATOR_PROMPT.format(persona=persona.prompt)
        transcript = [Turn(role="assistant", text=cfg.first_message, turn_idx=0)]
        tool_calls: list[ToolCallRecord] = []
        chat_ids: list[str] = []
        cost = 0.0
        ended_reason = "max-turns"
        started = time.monotonic()
        previous_chat_id: str | None = None

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
            # A transient assistant goes on every turn; previousChatId carries the context.
            body: dict[str, Any] = {"assistant": assistant, "input": caller_text or "..."}
            if previous_chat_id:
                body["previousChatId"] = previous_chat_id
            try:
                chat = self._request("POST", "/chat", body)
            except VapiError as error:
                ended_reason = f"error: {error}"[:300]
                break
            previous_chat_id = chat.get("id")
            if previous_chat_id:
                chat_ids.append(previous_chat_id)
            if isinstance(chat.get("cost"), (int, float)):
                cost += float(chat["cost"])
            new_turns, new_calls = parse_chat_output(chat, start_idx=len(transcript))
            transcript.extend(new_turns)
            tool_calls.extend(new_calls)
            if any(call.name in TRANSFER_TOOLS for call in new_calls):
                ended_reason = "transfer"
                break

        tool_calls = merge_tool_calls(tool_calls, self._tool_server_calls(session_id))
        return RunResult(
            persona_name=persona.name,
            agent_version=cfg.version_label,
            run_idx=run_idx,
            mode="chat",
            transcript=transcript,
            tool_calls=tool_calls,
            ended_reason=ended_reason,
            duration_s=round(time.monotonic() - started, 2),
            cost_usd=cost or None,
            raw={"session_id": session_id, "chat_ids": chat_ids},
        )

    def run_unit_test(self, cfg: AgentConfig, test: UnitTest) -> Verdict:
        """Positive tool assertions run as an exact judge; expectation and negations as an AI judge."""
        assistant = self.to_vapi_json(cfg, session_id=f"unit-{_slug(test.name)}-{uuid.uuid4().hex[:8]}")
        prefix = mock_messages(test.prefix_turns)
        plans: list[tuple[str, dict[str, Any]]] = []
        exact = [a for a in test.tool_assertions if not a.negate]
        if exact:
            calls = [{"name": a.tool, **({"arguments": a.args} if a.args else {})} for a in exact]
            plans.append(("exact", {"type": "exact", "toolCalls": calls}))
        plans.append(("ai", self._ai_judge_plan(test)))

        reasons: list[str] = []
        for kind, plan in plans:
            passed, reason = self._run_eval(test.name, kind, prefix, plan, assistant)
            if not passed:
                return Verdict(check_name=test.name, passed=False, reason=f"{kind}: {reason}")
            reasons.append(f"{kind}: {reason}" if reason else kind)
        return Verdict(check_name=test.name, passed=True, reason="; ".join(reasons))

    # --- Mapping ------------------------------------------------------------------------------

    def to_vapi_json(self, cfg: AgentConfig, session_id: str | None = None) -> dict[str, Any]:
        """AgentConfig -> Vapi assistant body (usable for POST /assistant or as a transient assistant)."""
        provider, model = split_model(cfg.model)
        tools = []
        for tool in cfg.tools:
            body: dict[str, Any] = {
                "type": "function",
                "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters},
            }
            if self.tools_base_url:
                url = f"{self.tools_base_url}/tools/{tool.name}"
                if session_id:
                    url += f"?session_id={session_id}"
                body["server"] = {"url": url}
            tools.append(body)
        assistant: dict[str, Any] = {
            "name": f"agentforge-{cfg.version_label}"[:40],
            "firstMessage": cfg.first_message,
            "firstMessageMode": "assistant-speaks-first",
            "model": {
                "provider": provider,
                "model": model,
                "temperature": 0.3,
                "messages": [{"role": "system", "content": cfg.system_prompt}],
                "tools": tools,
            },
            "metadata": {"version_label": cfg.version_label, "parent_version": cfg.parent_version},
        }
        if session_id:
            assistant["metadata"]["session_id"] = session_id
        return assistant

    # --- Evals --------------------------------------------------------------------------------

    def _ai_judge_plan(self, test: UnitTest) -> dict[str, Any]:
        provider, model = split_model(self.judge_model)
        rules = [f"Expected behaviour: {test.expectation}"]
        for assertion in test.tool_assertions:
            args = f" with arguments {json.dumps(assertion.args, ensure_ascii=False)}" if assertion.args else ""
            verb = "must NOT call" if assertion.negate else "must call"
            rules.append(f"The assistant {verb} the tool {assertion.tool}{args}.")
        content = (
            "Context: {{messages}}\n\nEvaluate ONLY the last assistant message (and any tool calls it makes).\n"
            + "\n".join(rules)
            + "\nPass only if every rule holds. Respond only with pass or fail."
        )
        return {"type": "ai", "model": {"provider": provider, "model": model, "messages": [{"role": "system", "content": content}]}}

    def _run_eval(
        self, name: str, kind: str, prefix: list[dict[str, Any]], plan: dict[str, Any], assistant: dict[str, Any]
    ) -> tuple[bool, str]:
        created = self._request(
            "POST",
            "/eval",
            {
                "name": f"{name}-{kind}"[:80],
                "type": "chat.mockConversation",
                "messages": [*prefix, {"role": "assistant", "judgePlan": plan}],
            },
        )
        # Under load Vapi sometimes answers 201 with {"error": ...} (a database timeout) and no run id.
        for attempt in range(3):
            run = self._request(
                "POST", "/eval/run", {"type": "eval", "evalId": created["id"], "target": {"type": "assistant", "assistant": assistant}}
            )
            run_id = run.get("id") or run.get("evalRunId")
            if run_id:
                break
            self.sleep(2 * (attempt + 1))
        else:
            return False, f"ERROR: eval run was not created: {str(run.get('error'))[:200]}"
        deadline = time.monotonic() + UNIT_TEST_DEADLINE_S
        while True:
            state = self._request("GET", f"/eval/run/{run_id}")
            if state.get("status") == "ended":
                break
            if time.monotonic() > deadline:
                return False, f"ERROR: eval run {run_id} did not end within {UNIT_TEST_DEADLINE_S}s"
            self.sleep(2)
        if state.get("endedReason") != "mockConversation.done":
            return False, f"ERROR: endedReason={state.get('endedReason')}"
        return eval_outcome(state)

    # --- HTTP ---------------------------------------------------------------------------------

    def _tool_server_calls(self, session_id: str) -> list[dict[str, Any]]:
        if not self.tools_base_url:
            return []
        try:
            response = self.client.get(f"{self.tools_base_url}/calls/{session_id}", timeout=15)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return []
        return payload if isinstance(payload, list) else []

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call Vapi with retries on 429/5xx; log every attempt to runs/vapi_log.jsonl."""
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "X-Client": "agentforge"}
        last = ""
        for attempt in range(5):
            started = time.monotonic()
            try:
                response = self.client.request(method, f"{self.base_url}{path}", json=body, headers=headers)
            except httpx.TransportError as error:
                status, payload, last = None, None, str(error)
            else:
                status = response.status_code
                try:
                    payload = response.json()
                except ValueError:
                    payload = response.text[:2000]
                last = f"{status}: {str(payload)[:500]}"
            self._log(method, path, body, status, payload, time.monotonic() - started)
            if status is not None and status < 300:
                return payload if isinstance(payload, dict) else {"data": payload}
            if status is not None and status != 429 and status < 500:
                raise VapiError(f"{method} {path} -> {last}")
            self.sleep(min(2**attempt, 30))
        raise VapiError(f"{method} {path} failed after retries: {last}")

    def _log(self, method: str, path: str, body: Any, status: int | None, payload: Any, elapsed: float) -> None:
        append_jsonl(
            self.log_path,
            {"ts": time.time(), "method": method, "path": path, "request": body, "status": status,
             "response": payload, "elapsed_s": round(elapsed, 3)},
        )


# --- Parsing helpers (module level so tests can hit them directly) -------------------------------


def parse_chat_output(chat: dict[str, Any], start_idx: int) -> tuple[list[Turn], list[ToolCallRecord]]:
    """Turn a /chat response's output messages into transcript turns and tool calls.

    Output items look like OpenAI messages; tool calls may appear as `tool_calls` or `toolCalls`,
    and tool results as role=tool with `tool_call_id`.
    """
    turns: list[Turn] = []
    calls: list[ToolCallRecord] = []
    pending: dict[str, ToolCallRecord] = {}
    output = chat.get("output")
    if isinstance(output, str):
        output = [{"role": "assistant", "content": output}]
    for item in output or []:
        if not isinstance(item, dict):
            continue
        idx = start_idx + len(turns)
        role = item.get("role")
        raw_calls = item.get("tool_calls") or item.get("toolCalls") or []
        if role == "assistant" and raw_calls:
            records = []
            for raw in raw_calls:
                function = raw.get("function") if isinstance(raw.get("function"), dict) else raw
                record = ToolCallRecord(name=str(function.get("name", "")), args=_parse_args(function.get("arguments")), turn_idx=idx)
                records.append(record)
                if raw.get("id"):
                    pending[raw["id"]] = record
            calls.extend(records)
            turns.append(Turn(role="assistant", text=_text(item.get("content")), tool_calls=[r.model_dump() for r in records], turn_idx=idx))
        elif role == "tool":
            result = _text(item.get("content"))
            record = pending.get(item.get("tool_call_id") or item.get("toolCallId") or "")
            if record is not None:
                record.result = _maybe_json(result)
            turns.append(Turn(role="tool", text=result, turn_idx=idx))
        elif role == "assistant":
            text = _text(item.get("content"))
            if text:
                turns.append(Turn(role="assistant", text=text, turn_idx=idx))
    return turns, calls


def merge_tool_calls(from_chat: list[ToolCallRecord], from_server: list[dict[str, Any]]) -> list[ToolCallRecord]:
    """Prefer the chat's own record; fill results from the tool server log, or use it when chat has none."""
    if not from_server:
        return from_chat
    if not from_chat:
        return [ToolCallRecord(name=c.get("name", ""), args=c.get("args") or {}, result=c.get("result")) for c in from_server]
    queue = list(from_server)
    for record in from_chat:
        match = next((c for c in queue if c.get("name") == record.name), None)
        if match is not None:
            queue.remove(match)
            if record.result is None:
                record.result = match.get("result")
            if not record.args:
                record.args = match.get("args") or {}
    return from_chat


def mock_messages(turns: list[Turn]) -> list[dict[str, Any]]:
    """Prefix turns -> chat.mockConversation messages."""
    messages: list[dict[str, Any]] = []
    for turn in turns:
        if turn.role == "assistant" and turn.tool_calls:
            message: dict[str, Any] = {"role": "assistant", "content": turn.text or ""}
            # POST /eval rejects OpenAI-style tool_calls; it accepts toolCalls as {name, arguments}.
            message["toolCalls"] = [{"name": c.get("name", ""), "arguments": c.get("args") or {}} for c in turn.tool_calls]
            messages.append(message)
        else:
            messages.append({"role": turn.role, "content": turn.text})
    return messages


def eval_outcome(state: dict[str, Any]) -> tuple[bool, str]:
    results = state.get("results") or []
    if not results or not isinstance(results[0], dict):
        return False, "ERROR: eval run has no results"
    first = results[0]
    reasons = [
        (m.get("judge") or {}).get("failureReason")
        for m in first.get("messages") or []
        if isinstance(m, dict) and (m.get("judge") or {}).get("failureReason")
    ]
    return first.get("status") == "pass", "; ".join(r for r in reasons if r)


def _caller_view(transcript: list[Turn]) -> str:
    """The simulator sees the conversation with roles flipped: the agent is 'Agent', itself is 'Sen'."""
    lines = []
    for turn in transcript:
        if turn.role == "assistant" and turn.text:
            lines.append(f"Agent: {turn.text}")
        elif turn.role == "user":
            lines.append(f"Sen: {turn.text}")
    return "Conversation so far:\n" + "\n".join(lines) + "\n\nReply with your next line only."


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return " ".join(str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in content).strip()
    return ""


def _parse_args(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        parsed = _maybe_json(arguments)
        return parsed if isinstance(parsed, dict) else {"raw": arguments}
    return {}


def _maybe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:24] or "x"
