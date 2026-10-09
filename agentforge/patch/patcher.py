"""LLM PATCHER: V(n) + FailureReport -> V(n+1)."""

from __future__ import annotations

import json
import re

from agentforge import llm
from agentforge.config import settings
from agentforge.schemas import AgentConfig, FailureReport, Patch

MAX_GROWTH = 0.15

SURGICAL_SCHEMA = {
    "type": "object",
    "properties": {
        "patches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "bug_id": {"type": "string"},
                    "layer": {"enum": ["prompt", "tool_schema", "first_message"]},
                    "operator": {"type": "string"},
                    "before": {"type": "string"},
                    "after": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["bug_id", "layer", "operator", "before", "after", "rationale"],
            },
        }
    },
    "required": ["patches"],
}

FREE_SCHEMA = {
    "type": "object",
    "properties": {
        "system_prompt": {"type": "string"},
        "first_message": {"type": "string"},
        "rationale": {"type": "string"},
    },
    "required": ["system_prompt", "first_message", "rationale"],
}

SURGICAL_SYSTEM = """You patch a Turkish voice agent. For EACH bug make exactly ONE minimal edit:
- layer "prompt": operator "add_rule" (before = an exact line or sentence in the system prompt to replace with itself
  plus the new rule, or "" to append at the end) or "replace_rule" (before = exact existing text, after = replacement).
  Put the rule in the stage it belongs to.
- layer "tool_schema": operator "tighten_tool:<tool_name>"; before = exact text in that tool's description ("" to append),
  after = the new text. State preconditions and formats explicitly.
- layer "first_message": operator "edit_first_message"; before = exact text in the first message, after = replacement.
"before" MUST be copied character for character from the current text, or be "". Keep spoken Turkish, short sentences,
no markdown. Keep growth small: total system prompt growth must stay under {budget} characters."""

FREE_SYSTEM = """You improve a Turkish voice agent. Rewrite the system prompt and first message so the agent follows every
generalized rule in the failure report while keeping all existing correct behaviour. Spoken Turkish, short sentences,
numbered stages, a "Kesin kurallar" section, no markdown lists in speech."""


def next_label(label: str) -> str:
    match = re.fullmatch(r"(.*?v)(\d+)", label)
    return f"{match.group(1)}{int(match.group(2)) + 1}" if match else f"{label}-p"


def describe(cfg: AgentConfig, report: FailureReport) -> str:
    tools = [{"name": t.name, "description": t.description, "parameters": t.parameters} for t in cfg.tools]
    bugs = [bug.model_dump(mode="json", exclude={"evidence", "culprit"}) for bug in report.agent_bugs()]
    return (
        f"SYSTEM PROMPT:\n{cfg.system_prompt}\n\nFIRST MESSAGE:\n{cfg.first_message}\n\n"
        f"TOOLS:\n{json.dumps(tools, ensure_ascii=False, indent=1)}\n\nBUGS:\n{json.dumps(bugs, ensure_ascii=False, indent=1)}"
    )


def apply_patch(cfg: AgentConfig, patch: Patch) -> AgentConfig | None:
    """Apply one patch; None if its `before` text is not found."""

    def edit(text: str) -> str | None:
        if not patch.before:
            return f"{text.rstrip()}\n{patch.after}" if text else patch.after
        if patch.before not in text:
            return None
        return text.replace(patch.before, patch.after, 1)

    if patch.layer == "prompt":
        new = edit(cfg.system_prompt)
        return None if new is None else cfg.model_copy(update={"system_prompt": new})
    if patch.layer == "first_message":
        new = edit(cfg.first_message)
        return None if new is None else cfg.model_copy(update={"first_message": new})
    target = patch.operator.split(":", 1)[1].strip() if ":" in patch.operator else None
    tools = list(cfg.tools)
    for index, tool in enumerate(tools):
        if target and tool.name != target:
            continue
        if not target and (not patch.before or patch.before not in tool.description):
            continue
        new = edit(tool.description)
        if new is not None:
            tools[index] = tool.model_copy(update={"description": new})
            return cfg.model_copy(update={"tools": tools})
    return None


def apply_patches(cfg: AgentConfig, patches: list[Patch]) -> tuple[AgentConfig, list[Patch]]:
    applied = []
    for patch in patches:
        updated = apply_patch(cfg, patch)
        if updated is not None:
            cfg = updated
            applied.append(patch)
    return cfg, applied


def within_budget(old: AgentConfig, new: AgentConfig) -> bool:
    return len(new.system_prompt) <= len(old.system_prompt) * (1 + MAX_GROWTH)


def surgical(cfg: AgentConfig, report: FailureReport) -> tuple[AgentConfig, list[Patch]]:
    budget = int(len(cfg.system_prompt) * MAX_GROWTH)
    system = SURGICAL_SYSTEM.replace("{budget}", str(budget))
    user = describe(cfg, report)
    for attempt in range(2):
        payload = llm.call_llm(system, user, model=settings().builder_model, json_schema=SURGICAL_SCHEMA)
        patches = [Patch.model_validate(item) for item in payload.get("patches", [])]
        patched, applied = apply_patches(cfg, patches)
        if within_budget(cfg, patched):
            return patched, applied
        user = f"{describe(cfg, report)}\n\nYour last patches grew the prompt too much. Write shorter rules."
    while applied:
        applied = applied[:-1]
        patched, applied = apply_patches(cfg, applied)
        if within_budget(cfg, patched):
            return patched, applied
    return cfg, []


def free(cfg: AgentConfig, report: FailureReport) -> tuple[AgentConfig, list[Patch]]:
    payload = llm.call_llm(FREE_SYSTEM, describe(cfg, report), model=settings().builder_model, json_schema=FREE_SCHEMA)
    patched = cfg.model_copy(update={"system_prompt": payload["system_prompt"], "first_message": payload["first_message"]})
    summary = Patch(
        bug_id=",".join(bug.bug_id for bug in report.agent_bugs()) or "none",
        layer="prompt",
        operator="rewrite",
        before="",
        after="",
        rationale=payload.get("rationale", ""),
    )
    return patched, [summary]


def patch_agent(
    cfg: AgentConfig, report: FailureReport, mode: str = "surgical", new_label: str | None = None
) -> tuple[AgentConfig, list[Patch]]:
    if mode not in {"surgical", "free"}:
        raise ValueError(f"unknown patch mode: {mode}")
    if report.agent_bugs():
        patched, patches = surgical(cfg, report) if mode == "surgical" else free(cfg, report)
    else:
        patched, patches = cfg, []
    notes = "; ".join(f"{p.bug_id}: {p.operator}" for p in patches)
    return (
        patched.model_copy(
            update={
                "version_label": new_label or next_label(cfg.version_label),
                "parent_version": cfg.version_label,
                "notes": f"{mode} patch of {cfg.version_label}. {notes}".strip(),
            }
        ),
        patches,
    )
