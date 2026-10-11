"""The task prompt and the short role appended to the system prompt. The knowledge lives in the skill."""

from __future__ import annotations

ROLE = ("You build Freya workflow phone agents from a bank's brief. You work only inside the current directory and "
        "write only under out/. You have file tools and the fb tools; there is no shell and no web access.")


def task_prompt(n_briefs: int, minutes: float, skill: str = "build-collections-agent") -> str:
    files = ", ".join(f"input/brief-{i}.*" for i in range(1, n_briefs + 1))
    return f"""Use the {skill} skill to build the phone agent. If the skill does not load, read .claude/skills/{skill}/SKILL.md and follow it.

Inputs: the brief material is {files}, in override order (a later file overrides an earlier one). The tool API is input/tools.openapi.json.

Brief material: when a brief file starts with a NOTE and has `=== FILE: name ===` sections, it is a whole case folder (BRIEF.md and README.md first, then emails, attachments, documents, meeting excerpts, test-environment rules and example scenarios, dated files oldest to newest). Read all of it; a later-dated document overrides an earlier one when they disagree, and every override goes into rules.json.

Tools: use ONLY the operations of input/tools.openapi.json (names, URLs, fields, enums as given there). Never add a tool, endpoint or field that API does not define, and do not assume the usual banking tools exist: if the brief describes an operation the API lacks, record that in rules.json and do not invent it.

Stages: build only the stages the documents require. Do not add an identity check, a promise or negotiation stage, or a "verify before disclosing" rule unless the documents ask for it; if they say the caller is already verified upstream, go from the opening to the work the call is for.

Call variables: declare in the workflow (test_variables, policy.call_variables) every variable the documents say the agent receives at the start of the call, under the documents' own names, and never have the agent ask the caller for a value that is given as a call variable. Date decisions use the call's own date-time variable when the documents define one.

Time budget: {minutes:g} minutes of wall clock. Call mcp__fb__time_left at every phase boundary and follow its advice.

Write these files:
- out/policy.json (the extraction, per the skill's policy schema)
- out/rules.json (every rule with its quote and where it is implemented)
- out/workflow.json (the Freya workflow)
- out/unit_tests.json (unit tests for your workflow, per the skill's reference/unit-tests.md)

Finish only when mcp__fb__lint_workflow reports 0 errors and mcp__fb__check_coverage reports 0 errors, or when time runs out. If time runs short, make sure out/workflow.json lints with 0 errors before anything else."""
