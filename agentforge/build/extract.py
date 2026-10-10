"""Read a brief into a policy and map its tools onto roles. No hardcoded tool names."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from agentforge.schemas import ToolDef

ROLES = ("verify", "account", "promise", "dispute", "callback", "do_not_call", "transfer")

# First matching role wins. Cues are specific so "account holder" is verification, not the account tool.
_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("do_not_call", ("do not call", "do-not-call", "stop contact", "aramayın")),
    ("promise", ("promise to pay", "payment pledge", "ödeme sözü")),
    ("dispute", ("dispute", "disagreement", "itiraz")),
    ("callback", ("callback", "return call", "geri ara")),
    ("transfer", ("transfer the call", "human agent", "handoff")),
    ("verify", ("verify the caller", "confirm the caller", "account holder", "kimlik")),
    ("account", ("account balance", "amount due", "fetch the balance", "bakiye")),
)


@dataclass
class Policy:
    language: str
    plan_allowed: bool
    minimum_payment: int | None
    maximum_months: int | None
    disclosure: str
    rules: list[str]
    hard_cases: list[str]
    gaps: list[str] = field(default_factory=list)
    roles: dict[str, ToolDef | None] = field(default_factory=dict)

    def tool_name(self, role: str) -> str | None:
        tool = self.roles.get(role)
        return None if tool is None else tool.name


def role_for(tool: ToolDef) -> str | None:
    text = tool.description.lower()
    for role, cues in _CUES:
        if any(cue in text for cue in cues):
            return role
    return None


def map_roles(tools: list[ToolDef]) -> dict[str, ToolDef | None]:
    found: dict[str, ToolDef | None] = {role: None for role in ROLES}
    for tool in tools:
        role = role_for(tool)
        if role is not None and found[role] is None:
            found[role] = tool
    return found


def extract(task_md: str, tools: list[ToolDef]) -> Policy:
    language = _line(task_md, "language") or "en"
    plan_raw = (_line(task_md, "plan_allowed") or "no").lower()
    disclosure = _section(task_md, "Disclosure")
    rules = _bullets(_section(task_md, "Rules"))
    hard_raw = _section(task_md, "Hard cases")
    gaps: list[str] = []
    if hard_raw is None:
        gaps.append("hard_cases")
        hard_cases: list[str] = []
    else:
        hard_cases = _bullets(hard_raw)
    roles = map_roles(tools)
    if roles["callback"] is None:
        gaps.append("callback")
    if not disclosure:
        gaps.append("disclosure")
        disclosure = "This is an automated assistant."
    return Policy(
        language=language,
        plan_allowed=plan_raw in {"yes", "true"},
        minimum_payment=_int_line(task_md, "minimum_payment"),
        maximum_months=_int_line(task_md, "maximum_months"),
        disclosure=disclosure.strip(),
        rules=rules,
        hard_cases=hard_cases,
        gaps=gaps,
        roles=roles,
    )


def _line(text: str, name: str) -> str | None:
    match = re.search(rf"(?m)^{re.escape(name)}:\s*(.+?)\s*$", text)
    return None if match is None else match.group(1).strip()


def _int_line(text: str, name: str) -> int | None:
    raw = _line(text, name)
    if raw is None or raw.lower() in {"", "none"}:
        return None
    return int(raw)


def _section(text: str, heading: str) -> str | None:
    match = re.search(rf"(?ms)^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text)
    if match is None:
        return None
    return match.group(1).strip()


def _bullets(section: str | None) -> list[str]:
    if not section:
        return []
    return [line[2:].strip() for line in section.splitlines() if line.startswith("- ")]
