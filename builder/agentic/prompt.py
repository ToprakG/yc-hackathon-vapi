"""The task prompt and the short role appended to the system prompt. The knowledge lives in the skill."""

from __future__ import annotations

ROLE = ("You build Freya workflow phone agents from a bank's brief. You work only inside the current directory and "
        "write only under out/. You have file tools and the fb tools; there is no shell and no web access.")


def task_prompt(n_briefs: int, minutes: float, skill: str = "build-collections-agent") -> str:
    files = ", ".join(f"input/brief-{i}.*" for i in range(1, n_briefs + 1))
    return f"""Use the {skill} skill to build the phone agent. If the skill does not load, read .claude/skills/{skill}/SKILL.md and follow it.

Inputs: the brief material is {files}, in override order (a later file overrides an earlier one). The tool API is input/tools.openapi.json.

Tools: use ONLY the operations of input/tools.openapi.json (names, URLs, fields, enums as given there). Never add a tool, endpoint or field that API does not define, and do not assume the usual banking tools exist: if the brief describes an operation the API lacks, record that in rules.json and do not invent it.

Time budget: {minutes:g} minutes of wall clock. Call mcp__fb__time_left at every phase boundary and follow its advice.

Write these files:
- out/policy.json (the extraction, per the skill's policy schema)
- out/rules.json (every rule with its quote and where it is implemented)
- out/workflow.json (the Freya workflow)
- out/unit_tests.json (unit tests for your workflow, per the skill's reference/unit-tests.md)

Finish only when mcp__fb__lint_workflow reports 0 errors and mcp__fb__check_coverage reports 0 errors, or when time runs out. If time runs short, make sure out/workflow.json lints with 0 errors before anything else."""
