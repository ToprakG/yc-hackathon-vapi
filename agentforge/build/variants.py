"""Shippable AgentConfig variants. No pinning, and no workflow graph."""

from __future__ import annotations

from agentforge.build.extract import Policy
from agentforge.build.template import render
from agentforge.schemas import AgentConfig, ToolDef

# The agent model only. The builder model and temperature stay fixed.
MODEL_SWEEP = ("openai:gpt-4o-mini", "openai:gpt-4o")


def template_config(
    policy: Policy,
    tools: list[ToolDef],
    *,
    opener: str = "fixed",
    descriptions: str = "rewritten",
    model: str | None = None,
    version_label: str | None = None,
) -> AgentConfig:
    label = version_label or f"template-{opener}-{descriptions}"
    return render(
        policy,
        tools,
        opener=opener,
        descriptions=descriptions,
        model=model,
        version_label=label,
    )


def apply_opener(config: AgentConfig, policy: Policy, kind: str) -> AgentConfig:
    from agentforge.build.template import opener_text

    return config.model_copy(
        update={
            "first_message": opener_text(policy, kind),
            "version_label": f"{config.version_label}-opener-{kind}",
            "notes": f"{config.notes} opener={kind}".strip(),
        }
    )


def apply_descriptions(config: AgentConfig, policy: Policy, tools: list[ToolDef], mode: str) -> AgentConfig:
    if mode not in {"raw", "rewritten"}:
        raise ValueError(f"unknown descriptions: {mode}")
    from agentforge.build.template import _describe

    merged = [_describe(policy, tool, mode) for tool in tools]
    return config.model_copy(
        update={
            "tools": merged,
            "version_label": f"{config.version_label}-tools-{mode}",
            "notes": f"{config.notes} descriptions={mode}".strip(),
        }
    )


def sweep_models(config: AgentConfig, models: tuple[str, ...] = MODEL_SWEEP) -> list[AgentConfig]:
    swept = []
    for model in models:
        slug = model.replace(":", "-").replace("/", "-")
        swept.append(
            config.model_copy(
                update={
                    "model": model,
                    "version_label": f"{config.version_label}-{slug}",
                    "notes": f"{config.notes} model={model}".strip(),
                }
            )
        )
    return swept


def stage_order_ok(prompt: str, verify: str, account: str) -> bool:
    """The prompt names the verify tool before the account tool."""
    verify_at = prompt.find(verify)
    account_at = prompt.find(account)
    return verify_at != -1 and account_at != -1 and verify_at < account_at


def shippable(policy: Policy, tools: list[ToolDef], *, model: str | None = None) -> dict[str, AgentConfig]:
    """Every variant this round can upload. One-call stays in build_agent and is not called here."""
    out: dict[str, AgentConfig] = {}
    for opener in ("fixed", "generic"):
        for descriptions in ("raw", "rewritten"):
            config = template_config(policy, tools, opener=opener, descriptions=descriptions, model=model)
            out[config.version_label] = config
    base = out["template-fixed-rewritten"]
    for config in sweep_models(base):
        out[config.version_label] = config
    return out
