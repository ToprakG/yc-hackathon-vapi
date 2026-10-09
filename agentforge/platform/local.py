"""Local platform: the agent runs straight on OpenAI or Claude tool calling, tools run in-process. No Vapi, no tunnel.

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
# Per-token prices (USD) for a rough cost figure; unknown models count as 0.
PRICES = {"gpt-4o-mini": (0.15e-6, 0.60e-6), "gpt-4o": (2.5e-6, 10e-6), "claude-haiku-5-5": (0.10e-6, 0.50e-6),
          "claude-sonnet-5-5": (2e-6, 10e-6)}
CALL_OPENED = "[Çağrı bağlandı]"  # Claude needs a user turn before the agent's greeting

ToolRunner = Callable[[str, str, dict[str, Any]], Any]


def kasko_tools(session_id: str, name: str, args: dict[str, Any]) -> Any:
    from agentforge.domain.kasko.tools_server import run_tool

    return run_tool(session_id, name, args)


class LocalPlatform(Platform):
    def __init__(self, run_tool: ToolRunner = kasko_tools, client=None, add_date: bool = False, agent_model: str | None = None):
        self.run_tool = run_tool
        self._client = client
        self.add_date = add_date  # off by default so results stay comparable with the Vapi runs
        # The agent model is a platform choice here (AGENT_MODEL), so saved configs run on whatever key we have.
        self.agent_model = agent_model or settings().agent_model

    def client(self, provider: str):
        if self._client is not None:
            return self._client
        if provider == "anthropic":
            import anthropic

            self._client = anthropic.Anthropic(api_key=settings().anthropic_api_key or None)
        else:
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
            cost_usd=self._cost(usage),
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

    def _cost(self, usage: list[int]) -> float:
        price_in, price_out = PRICES.get(split_model(self.agent_model)[1], (0.0, 0.0))
        return round(usage[0] * price_in + usage[1] * price_out, 5)

    def _system(self, cfg: AgentConfig) -> str:
        if not self.add_date:
            return cfg.system_prompt
        return f"{cfg.system_prompt}\n\nBugünün tarihi: {date.today().isoformat()}."

    def _agent_step(self, cfg, messages, transcript, session_id, usage) -> list[ToolCallRecord]:
        """One agent turn: call tools until the model answers in text."""
        provider, model = split_model(self.agent_model)
        complete = self._complete_anthropic if provider == "anthropic" else self._complete_openai
        calls: list[ToolCallRecord] = []
        for _ in range(MAX_TOOL_ROUNDS):
            text, requested = complete(model, messages, cfg.tools, usage)
            if not requested:
                messages.append({"role": "assistant", "content": text})
                if text:
                    transcript.append(Turn(role="assistant", text=text, turn_idx=len(transcript)))
                return calls
            messages.append({
                "role": "assistant",
                "content": text,
                "tool_calls": [{"id": i, "type": "function", "function": {"name": n, "arguments": json.dumps(a, ensure_ascii=False)}}
                               for i, n, a in requested],
            })
            records = []
            for call_id, name, args in requested:
                result = self.run_tool(session_id, name, args)
                records.append(ToolCallRecord(name=name, args=args, result=result, turn_idx=len(transcript)))
                messages.append({"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, ensure_ascii=False)})
            transcript.append(Turn(role="assistant", text=text, tool_calls=[r.model_dump() for r in records],
                                   turn_idx=len(transcript)))
            for record in records:
                transcript.append(Turn(role="tool", text=json.dumps(record.result, ensure_ascii=False), turn_idx=len(transcript)))
            calls.extend(records)
            if any(r.name in TRANSFER_TOOLS for r in records):
                return calls
        return calls


    def _complete_openai(self, model, messages, tools, usage):
        specs = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                 for t in tools]
        response = self.client("openai").chat.completions.create(model=model, messages=messages, tools=specs or None, temperature=0.3)
        if response.usage:
            usage[0] += response.usage.prompt_tokens
            usage[1] += response.usage.completion_tokens
        message = response.choices[0].message
        requested = [(c.id, c.function.name, _loads(c.function.arguments)) for c in message.tool_calls or []]
        return (message.content or "").strip(), requested

    def _complete_anthropic(self, model, messages, tools, usage):
        specs = [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools]
        response = self.client("anthropic").messages.create(
            model=model,
            system=messages[0]["content"],
            messages=to_anthropic(messages[1:]),
            tools=specs,
            max_tokens=2048,
            # Short spoken turns don't need thinking, and with it off there are no thinking blocks to preserve
            # when the history is re-sent in our own format.
            thinking={"type": "disabled"},
        )
        usage[0] += response.usage.input_tokens
        usage[1] += response.usage.output_tokens
        text = " ".join(b.text for b in response.content if b.type == "text").strip()
        requested = [(b.id, b.name, dict(b.input or {})) for b in response.content if b.type == "tool_use"]
        return text, requested


def to_anthropic(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Our OpenAI-style history -> Claude messages (tool_use / tool_result blocks); must start with a user turn."""
    out: list[dict[str, Any]] = [{"role": "user", "content": CALL_OPENED}]
    for m in messages:
        if m["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            last = out[-1]
            if last["role"] == "user" and isinstance(last["content"], list) and last["content"][0].get("type") == "tool_result":
                last["content"].append(block)  # all results of one turn go back in one user message
            else:
                out.append({"role": "user", "content": [block]})
        elif m["role"] == "assistant":
            blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
            blocks += [{"type": "tool_use", "id": c["id"], "name": c["function"]["name"], "input": _loads(c["function"]["arguments"])}
                       for c in m.get("tool_calls") or []]
            if blocks:
                out.append({"role": "assistant", "content": blocks})
        else:
            out.append({"role": "user", "content": m["content"] or "..."})
    return out


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
