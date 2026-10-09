"""LLM TEST GENERATOR: one or two unit tests per agent bug, cut from the real failing transcript."""

from __future__ import annotations

from agentforge import llm
from agentforge.analyze.analyzer import render_run
from agentforge.config import RUNS_DIR, settings
from agentforge.schemas import Bug, FailureReport, ScoredRun, ToolAssertion, Turn, UnitTest
from agentforge.store import save_json

TEST_SCHEMA = {
    "type": "object",
    "properties": {
        "expectation": {"type": "string"},
        "tool_assertions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string"},
                    "args": {"type": ["object", "null"]},
                    "negate": {"type": "boolean"},
                },
                "required": ["tool", "args", "negate"],
            },
        },
    },
    "required": ["expectation", "tool_assertions"],
}

SYSTEM = """You write a unit test for a Turkish voice agent. The conversation is replayed up to the failure point and the
agent must produce its NEXT turn. Write:
- expectation: what a correct next turn does, observable and specific (the judge reads only that next turn and its tool calls).
- tool_assertions: exact tool-call checks on that next turn. negate=true means the tool must NOT be called. Use args only
  for values that must match exactly; otherwise null. Empty list if the bug is about speech only."""


def failure_turn(scored: ScoredRun, evidence_turn: int | None) -> int | None:
    if evidence_turn is not None:
        return evidence_turn
    return next((v.evidence_turn for v in scored.verdicts if not v.passed and v.evidence_turn is not None), None)


def cut_prefix(transcript: list[Turn], turn: int | None) -> list[Turn]:
    """Turns before the failure, ending on the caller's turn so the agent speaks next."""
    prefix = [t for t in transcript if turn is None or t.turn_idx < turn]
    if turn is None and prefix and prefix[-1].role == "assistant":
        prefix = prefix[:-1]
    while prefix and prefix[-1].role != "user":
        prefix.pop()
    return prefix


def tests_for_bug(bug: Bug, failed: list[ScoredRun]) -> list[UnitTest]:
    runs = {(s.run.persona_name, s.run.run_idx): s for s in failed}
    tests: list[UnitTest] = []
    for evidence in bug.evidence:
        scored = runs.get((evidence.persona, evidence.run_idx))
        if scored is None:
            continue
        prefix = cut_prefix(scored.run.transcript, failure_turn(scored, evidence.turn))
        if not prefix:
            continue
        payload = llm.call_llm(
            SYSTEM,
            f"BUG: {bug.description}\nRULE: {bug.generalized_rule}\n\nFAILING RUN:\n{render_run(scored)}\n\n"
            f"The replay stops after turn {prefix[-1].turn_idx}.",
            model=settings().builder_model,
            json_schema=TEST_SCHEMA,
        )
        tests.append(
            UnitTest(
                name=f"{bug.bug_id}-{evidence.persona}-r{evidence.run_idx}",
                prefix_turns=prefix,
                expectation=payload["expectation"],
                tool_assertions=[ToolAssertion.model_validate(a) for a in payload.get("tool_assertions", [])],
            )
        )
        if len(tests) == 2:
            break
    return tests


def generate_unit_tests(
    report: FailureReport, failed: list[ScoredRun], existing: list[UnitTest] | None = None
) -> list[UnitTest]:
    tests = list(existing or [])
    names = {test.name for test in tests}
    for bug in report.agent_bugs():
        for test in tests_for_bug(bug, failed):
            if test.name not in names:
                tests.append(test)
                names.add(test.name)
    return tests


def save_unit_tests(version: str, tests: list[UnitTest]):
    return save_json(RUNS_DIR / version / "unit_tests.json", tests)
