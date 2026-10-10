"""Rule-by-rule check. Repair inserts the extracted line. It does not ask a model to rewrite the prompt."""

from __future__ import annotations

import re
from collections.abc import Callable

from agentforge.build.extract import Policy
from agentforge.schemas import AgentConfig

Ask = Callable[[str, str], bool]

_YES_NO = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"passes": {"type": "boolean"}},
    "required": ["passes"],
}


def llm_ask(rule: str, prompt: str) -> bool:
    """One yes/no through the shared LLM client. Tests pass a fake ask instead of calling this."""
    from agentforge.llm import call_llm

    parsed = call_llm(
        "You check one policy rule. passes is true only if the prompt states that rule.",
        f"Rule:\n{rule}\n\nPrompt:\n{prompt}",
        json_schema=_YES_NO,
        temperature=0,
        max_tokens=256,
        effort="low",
    )
    return isinstance(parsed, dict) and parsed.get("passes") is True


def self_check(
    policy: Policy,
    agent: AgentConfig,
    *,
    repair: bool = True,
    ask: Ask | None = None,
) -> tuple[AgentConfig, list[str]]:
    checker = llm_ask if ask is None else ask
    prompt = agent.system_prompt
    gaps: list[str] = []
    inserts: list[str] = []

    for tool in _mapped_tools(policy):
        if not re.search(rf"\b{re.escape(tool.name)}\b", prompt):
            gaps.append(f"missing tool {tool.name}")
            inserts.append(f"Call {tool.name}.")

    if policy.roles.get("callback") is None and re.search(r"\bschedule_callback\b", prompt):
        gaps.append("invented callback tool")
        inserts.append("This brief has no callback tool. Do not invent one.")

    if policy.minimum_payment is not None and not _has_number(prompt, policy.minimum_payment):
        gaps.append(f"missing minimum payment {policy.minimum_payment}")
        inserts.append(f"The minimum payment is {policy.minimum_payment}.")
    if policy.maximum_months is not None and not _has_number(prompt, policy.maximum_months):
        gaps.append(f"missing maximum months {policy.maximum_months}")
        inserts.append(f"The maximum number of months is {policy.maximum_months}.")

    for rule in policy.rules:
        if not checker(rule, prompt):
            gaps.append(f"rule failed: {rule}")
            inserts.append(rule)

    if repair and inserts:
        prompt = prompt.rstrip() + "\n" + "\n".join(inserts)
        agent = agent.model_copy(update={"system_prompt": prompt})
    return agent, gaps


def _mapped_tools(policy: Policy):
    seen: set[str] = set()
    for tool in policy.roles.values():
        if tool is None or tool.name in seen:
            continue
        seen.add(tool.name)
        yield tool


def _has_number(prompt: str, value: int) -> bool:
    return re.search(rf"\b{value}\b", prompt) is not None
