"""Render an extracted policy into one AgentConfig. This is the shippable template."""

from __future__ import annotations

from agentforge.config import settings
from agentforge.build.extract import Policy
from agentforge.schemas import AgentConfig, ToolDef

# A greeting we would ship. It does not name the debt, the balance, or the creditor.
GENERIC_OPENER = {
    "en": "Hello. How can I help you?",
    "tr": "Merhaba. Size nasıl yardımcı olabilirim?",
}

_DEBT_WORDS = ("debt", "amount", "creditor", "balance", "borç", "bakiye", "tutar", "alacak")


def opener_text(policy: Policy, kind: str) -> str:
    if kind == "fixed":
        text = policy.disclosure
    elif kind == "generic":
        text = GENERIC_OPENER.get(policy.language, GENERIC_OPENER["en"])
    else:
        raise ValueError(f"unknown opener: {kind}")
    leaked = [word for word in _DEBT_WORDS if word in text.lower()]
    if leaked:
        raise ValueError(f"opener mentions {leaked}, which is not a variant we ship")
    return text


def render(
    policy: Policy,
    tools: list[ToolDef],
    *,
    opener: str = "fixed",
    descriptions: str = "rewritten",
    model: str | None = None,
    version_label: str = "template",
) -> AgentConfig:
    if descriptions not in {"raw", "rewritten"}:
        raise ValueError(f"unknown descriptions: {descriptions}")
    merged = [_describe(policy, tool, descriptions) for tool in tools]
    return AgentConfig(
        version_label=version_label,
        system_prompt=system_prompt(policy, tools),
        first_message=opener_text(policy, opener),
        tools=merged,
        model=model or settings().agent_model,
        notes=f"template opener={opener} descriptions={descriptions}",
    )


def system_prompt(policy: Policy, tools: list[ToolDef]) -> str:
    names = {tool.name for tool in tools}
    verify = policy.tool_name("verify") or "the verification tool"
    account = policy.tool_name("account") or "the account tool"
    sections = [
        _role(policy),
        _stages(policy, verify, account),
        _rules(policy),
        _compliance(policy, verify, account),
        _hard_cases(policy),
    ]
    prompt = "\n\n".join(sections)
    invented = _snake_names(prompt) - names
    if invented:
        raise ValueError(f"template invented tool names: {sorted(invented)}")
    return prompt


def _describe(policy: Policy, tool: ToolDef, mode: str) -> ToolDef:
    if mode == "raw":
        return tool
    role = next((name for name, mapped in policy.roles.items() if mapped is not None and mapped.name == tool.name), "tool")
    description = f"Role {role.replace('_', '-')}. {tool.description}"
    return tool.model_copy(update={"description": description})


def _role(policy: Policy) -> str:
    return (
        "## Role\n"
        "You are a collections voice agent. Speak in short sentences. "
        "Ask one thing at a time. Do not invent a tool, an amount, or a plan the brief does not allow."
    )


def _stages(policy: Policy, verify: str, account: str) -> str:
    lines = [
        "## Stages",
        "1. Opening. Say the disclosure. Do not mention the debt, the balance, or the creditor.",
        f"2. Verification. Call {verify} before any other tool.",
        f"3. Account. Call {account} only after verification succeeds. Do not state any amount before that.",
    ]
    promise = policy.tool_name("promise")
    limit = _limit_sentence(policy)
    if promise and policy.plan_allowed:
        lines.append(f"4. Promise. Call {promise} only after the caller states a date and an amount. {limit}")
    elif promise:
        lines.append(f"4. Promise. Do not offer a payment plan and do not call {promise}.")
    else:
        lines.append("4. Promise. Do not offer a payment plan. This brief has no promise tool.")
    if policy.tool_name("do_not_call"):
        lines.append(f"5. Do not call. On that request, call {policy.tool_name('do_not_call')} and end.")
    if policy.tool_name("dispute"):
        lines.append(f"6. Dispute. Call {policy.tool_name('dispute')} when the caller disputes the debt.")
    if policy.tool_name("callback"):
        lines.append(f"7. Callback. Call {policy.tool_name('callback')} only when the caller asks for one.")
    else:
        lines.append("7. Callback. This brief has no callback tool. Do not invent one. Offer a transfer instead.")
    if policy.tool_name("transfer"):
        lines.append(f"8. Transfer. Call {policy.tool_name('transfer')} for a human, a hardship, or abuse.")
    return "\n".join(lines)


def _rules(policy: Policy) -> str:
    lines = ["## Hard rules", *policy.rules]
    if policy.minimum_payment is not None:
        lines.append(f"The minimum payment is {policy.minimum_payment}.")
    if policy.maximum_months is not None:
        lines.append(f"The maximum number of months is {policy.maximum_months}.")
    if not policy.plan_allowed:
        lines.append("A payment plan is not allowed.")
    return "\n".join(lines)


def _compliance(policy: Policy, verify: str, account: str) -> str:
    return (
        "## Visible compliance\n"
        f"Say the disclosure out loud: {policy.disclosure} "
        f"Say that verification succeeded before you call {account}. "
        f"Call {verify} first."
    )


def _hard_cases(policy: Policy) -> str:
    if "hard_cases" in policy.gaps or not policy.hard_cases:
        body = "The brief left hard cases unspecified. Do not invent a tool. Offer a transfer to a human."
    else:
        body = "\n".join(policy.hard_cases)
    return f"## Hard cases\n{body}"


def _limit_sentence(policy: Policy) -> str:
    parts = []
    if policy.maximum_months is not None:
        parts.append(f"not longer than {policy.maximum_months} months")
    if policy.minimum_payment is not None:
        parts.append(f"not below {policy.minimum_payment}")
    return ("A plan is " + " and ".join(parts) + ".") if parts else ""


def _snake_names(text: str) -> set[str]:
    import re

    return set(re.findall(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", text))
