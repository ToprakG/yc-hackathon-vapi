"""Local platform: the agent runs straight on OpenAI tool calling, tools run in-process. No Vapi, no tunnel.

Same simulator and judge as the Vapi adapter, so scores are comparable apart from Vapi's own behaviour
(e.g. its English filler messages during tool calls).
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import date
from typing import Any, Callable

from agentforge import llm
from agentforge.config import settings, split_model
from agentforge.platform.base import Platform
from agentforge.platform.vapi import END_TOKEN, MAX_TURNS, SIMULATOR_PROMPT, TRANSFER_TOOLS, _caller_view, _slug
from agentforge.schemas import AgentConfig, Persona, RunResult, ToolCallRecord, Turn, UnitTest, Verdict

MAX_TOOL_ROUNDS = 5
# gpt-4o-mini per-token prices (USD), for a rough cost figure.
PRICE_IN, PRICE_OUT = 0.15e-6, 0.60e-6

ToolRunner = Callable[[str, str, dict[str, Any]], Any]


def kasko_tools(session_id: str, name: str, args: dict[str, Any]) -> Any:
    from agentforge.domain.kasko.tools_server import run_tool

    return run_tool(session_id, name, args)


class LocalPlatform(Platform):
    def __init__(self, run_tool: ToolRunner = kasko_tools, client=None, add_date: bool = False):
        self.run_tool = run_tool
        self._client = client
        self.add_date = add_date  # off by default so results stay comparable with the Vapi runs

    @property
    def client(self):
        if self._client is None:
            import openai

            self._client = openai.OpenAI(api_key=settings().openai_api_key or None)
        return self._client

    def upsert_agent(self, cfg: AgentConfig) -> str:
        return f"local-{cfg.version_label}"

    def run_conversation(self, cfg: AgentConfig, persona: Persona, run_idx: int) -> RunResult:
        session_id = f"{cfg.version_label}-{_slug(persona.name)}-{run_idx}-{uuid.uuid4().hex[:8]}"
        simulator_system = SIMULATOR_PROMPT.format(persona=persona.prompt)
        messages = [{"role": "system", "content": self._system(cfg)}, {"role": "assistant", "content": cfg.first_message}]
        transcript = [Turn(role="assistant", text=cfg.first_message, turn_idx=0)]
        tool_calls: list[ToolCallRecord] = []
        usage = [0, 0]
        ended_reason = "max-turns"
        started = time.monotonic()

        for _ in range(MAX_TURNS):
            caller_text = str(
                llm.call_llm(simulator_system, _caller_view(transcript), model=settings().simulator_model, temperature=0.7)
            ).strip()
            finished = END_TOKEN in caller_text
            caller_text = caller_text.replace(END_TOKEN, "").strip()
            if caller_text:
                transcript.append(Turn(role="user", text=caller_text, turn_idx=len(transcript)))
                messages.append({"role": "user", "content": caller_text})
            if finished:
                ended_reason = "caller-ended"
                break
            try:
                calls = self._agent_step(cfg, messages, transcript, session_id, usage)
            except Exception as error:
                ended_reason = f"error: {error}"[:300]
                break
            tool_calls.extend(calls)
            if any(call.name in TRANSFER_TOOLS for call in calls):
                ended_reason = "transfer"
                break

        return RunResult(
            persona_name=persona.name,
            agent_version=cfg.version_label,
            run_idx=run_idx,
            mode="local",
            transcript=transcript,
            tool_calls=tool_calls,
            ended_reason=ended_reason,
            duration_s=round(time.monotonic() - started, 2),
            cost_usd=round(usage[0] * PRICE_IN + usage[1] * PRICE_OUT, 5),
            raw={"session_id": session_id},
        )

    def run_unit_test(self, cfg: AgentConfig, test: UnitTest) -> Verdict:
        session_id = f"ut-{_slug(test.name)}-{uuid.uuid4().hex[:8]}"
        messages = [{"role": "system", "content": self._system(cfg)}, *prefix_messages(test.prefix_turns)]
        transcript = list(test.prefix_turns)
        try:
            calls = self._agent_step(cfg, messages, transcript, session_id, [0, 0])
        except Exception as error:
            return Verdict(check_name=test.name, passed=False, reason=f"ERROR: {error}")

        for assertion in test.tool_assertions:
            hit = any(c.name == assertion.tool and _args_match(assertion.args, c.args) for c in calls)
            if hit == assertion.negate:
                verb = "called" if assertion.negate else "did not call"
                return Verdict(check_name=test.name, passed=False, reason=f"agent {verb} {assertion.tool} {assertion.args or ''}")

        reply = " ".join(t.text for t in transcript[len(test.prefix_turns):] if t.role == "assistant" and t.text)
        judged = llm.call_llm(
            "You check one reply of a Turkish voice agent. Decide if it meets the expectation. "
            "Reply JSON {\"passed\": bool, \"reason\": str}.",
            f"EXPECTATION: {test.expectation}\n\nAGENT REPLY: {reply}\n\nTOOL CALLS: "
            + json.dumps([c.model_dump() for c in calls], ensure_ascii=False, default=str),
            model=settings().judge_model,
            json_schema={"type": "object", "properties": {"passed": {"type": "boolean"}, "reason": {"type": "string"}},
                         "required": ["passed", "reason"]},
            temperature=0,
        )
        return Verdict(check_name=test.name, passed=bool(judged.get("passed")), reason=str(judged.get("reason", "")))

    def _system(self, cfg: AgentConfig) -> str:
        if not self.add_date:
            return cfg.system_prompt
        return f"{cfg.system_prompt}\n\nBugünün tarihi: {date.today().isoformat()}."

    def _agent_step(self, cfg, messages, transcript, session_id, usage) -> list[ToolCallRecord]:
        """One agent turn: call tools until the model answers in text."""
        provider, model = split_model(cfg.model)
        if provider != "openai":
            raise ValueError(f"LocalPlatform runs OpenAI agents only, got {cfg.model}")
        tools = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                 for t in cfg.tools]
        calls: list[ToolCallRecord] = []
        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.chat.completions.create(
                model=model, messages=messages, tools=tools or None, temperature=0.3
            )
            if response.usage:
                usage[0] += response.usage.prompt_tokens
                usage[1] += response.usage.completion_tokens
            message = response.choices[0].message
            if not message.tool_calls:
                text = (message.content or "").strip()
                messages.append({"role": "assistant", "content": text})
                if text:
                    transcript.append(Turn(role="assistant", text=text, turn_idx=len(transcript)))
                return calls
            messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
                               for c in message.tool_calls],
            })
            records = []
            for call in message.tool_calls:
                args = _loads(call.function.arguments)
                result = self.run_tool(session_id, call.function.name, args)
                records.append(ToolCallRecord(name=call.function.name, args=args, result=result, turn_idx=len(transcript)))
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})
            transcript.append(Turn(role="assistant", text=message.content or "", tool_calls=[r.model_dump() for r in records],
                                   turn_idx=len(transcript)))
            for record in records:
                transcript.append(Turn(role="tool", text=json.dumps(record.result, ensure_ascii=False), turn_idx=len(transcript)))
            calls.extend(records)
            if any(r.name in TRANSFER_TOOLS for r in records):
                return calls
        return calls


def prefix_messages(turns: list[Turn]) -> list[dict[str, Any]]:
    """Replay saved turns as OpenAI messages; tool results pair with the preceding call ids in order."""
    messages: list[dict[str, Any]] = []
    pending: list[str] = []
    for turn in turns:
        if turn.role == "assistant" and turn.tool_calls:
            ids = [f"call_{turn.turn_idx}_{i}" for i in range(len(turn.tool_calls))]
            messages.append({"role": "assistant", "content": turn.text or "", "tool_calls": [
                {"id": i, "type": "function", "function": {"name": c.get("name", ""), "arguments": json.dumps(c.get("args") or {})}}
                for i, c in zip(ids, turn.tool_calls)]})
            pending = ids
        elif turn.role == "tool":
            if pending:
                messages.append({"role": "tool", "tool_call_id": pending.pop(0), "content": turn.text})
        else:
            messages.append({"role": turn.role, "content": turn.text})
    # A call without a recorded result would make the request invalid.
    for call_id in pending:
        messages.append({"role": "tool", "tool_call_id": call_id, "content": "{}"})
    return messages


def _args_match(expected: dict[str, Any] | None, actual: dict[str, Any]) -> bool:
    return not expected or all(str(actual.get(k, "")).strip().lower() == str(v).strip().lower() for k, v in expected.items())


def _loads(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"raw": raw}
    return value if isinstance(value, dict) else {"value": value}
