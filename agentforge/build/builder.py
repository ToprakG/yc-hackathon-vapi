"""LLM BUILDER: TASK + TOOLS -> V1.

CLI: python -m agentforge.build.builder kasko
"""

from __future__ import annotations

import json
import sys

from agentforge import llm
from agentforge.config import RUNS_DIR, settings
from agentforge.domain import load_domain
from agentforge.schemas import AgentConfig, ToolDef
from agentforge.store import save_json

BUILDER_SYSTEM = """You design production voice agents for Turkish insurance and banking call centers.
You receive a call-center SOP (the task) and the tools the agent can call. You write the agent.

The agent is a TURKISH VOICE agent on the phone:
- Every sentence it says is short and spoken. No lists, no markdown, no bullet points, no emojis in speech.
- It asks one thing at a time.
- It reads numbers digit by digit (policy numbers, claim numbers, last 4 of TCKN), never as large numbers.

Write the system prompt (in Turkish) with these sections, in this order:
1. Rol ve üslup: who the agent is, voice style rules above.
2. Aşamalar: numbered stages
   Açılış / AI bildirimi -> Kimlik doğrulama -> Talebi anlama -> İşlem -> Kapanış.
   For each stage: what the agent must do and say, what it must collect, and EXACTLY which tools may be used in that stage.
   No tool may be used in a stage that does not list it.
3. Kesin kurallar: EVERY hard rule from the SOP, including rules buried inside paragraphs. Phrase each one as observable
   behaviour ("Kimlik doğrulanmadan get_policy çağırma ve poliçe bilgisi söyleme", not "be careful with privacy").
   Include escalation rules, PII rules, coverage-promise rules, number-reading rules, and what to do when a tool returns an error.
4. Görünür uyum: compliance must be VISIBLE in speech because a judge reads only the transcript and tool calls.
   The agent says out loud that it is an AI assistant, confirms verification out loud, summarizes collected details and asks
   for confirmation before any write tool, and summarizes what was done at the end of the call.
5. Zor durumlar: caller gives info out of order, corrects themselves, calls on behalf of someone else, asks about excluded
   coverage, asks for a human, mentions injury late. Say what to do for each.

first_message: the opening line the agent speaks. It must include a greeting, the AI disclosure, and one open question.

tool_descriptions: for every tool, a Turkish description that states what it does, its preconditions explicitly
("Sadece ... sonra çağır"), and argument formats. Use the exact tool names given.

Do not invent policy facts, coverages, or rules that are not in the SOP."""

BUILDER_SCHEMA = {
    "type": "object",
    "properties": {
        "system_prompt": {"type": "string"},
        "first_message": {"type": "string"},
        "tool_descriptions": {"type": "object", "additionalProperties": {"type": "string"}},
    },
    "required": ["system_prompt", "first_message", "tool_descriptions"],
}


def builder_user_message(task_md: str, tools: list[ToolDef]) -> str:
    tool_lines = json.dumps([tool.model_dump(mode="json") for tool in tools], ensure_ascii=False, indent=2)
    return f"# TASK (SOP)\n\n{task_md}\n\n# TOOLS\n\n{tool_lines}"


def build_agent(task_md: str, tools: list[ToolDef], model: str | None = None) -> AgentConfig:
    # Models occasionally return JSON without the required keys; one retry fixes it.
    for attempt in range(2):
        payload = llm.call_llm(
            BUILDER_SYSTEM,
            builder_user_message(task_md, tools),
            model=model or settings().builder_model,
            json_schema=BUILDER_SCHEMA,
            temperature=0.2,
            max_tokens=8000,
        )
        if isinstance(payload, dict) and payload.get("system_prompt") and payload.get("first_message"):
            break
    else:
        raise ValueError("builder output is missing system_prompt or first_message")
    descriptions = payload.get("tool_descriptions") or {}
    merged = [
        tool.model_copy(update={"description": descriptions[tool.name]})
        if isinstance(descriptions.get(tool.name), str) and descriptions[tool.name].strip()
        else tool
        for tool in tools
    ]
    return AgentConfig(
        version_label="v1",
        system_prompt=payload["system_prompt"].strip(),
        first_message=payload["first_message"].strip(),
        tools=merged,
        model=settings().agent_model,
        parent_version=None,
        notes="LLM builder output",
    )


def main(argv: list[str]) -> None:
    domain = argv[0] if argv else "kasko"
    task_md, tools = load_domain(domain)
    cfg = build_agent(task_md, tools)
    path = save_json(RUNS_DIR / "v1" / "agent.json", cfg)
    print(f"saved {path}")
    print(f"system prompt: {len(cfg.system_prompt)} chars, first message: {cfg.first_message!r}")


if __name__ == "__main__":
    main(sys.argv[1:])
