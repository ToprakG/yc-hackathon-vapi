"""LLM ANALYZER: failed train runs -> generalized behavioral bugs."""

from __future__ import annotations

import json

from agentforge import llm
from agentforge.config import settings
from agentforge.schemas import Bug, FailureReport, Persona, RunResult, ScoredRun

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "bugs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "bug_id": {"type": "string"},
                    "description": {"type": "string"},
                    "generalized_rule": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "persona": {"type": "string"},
                                "run_idx": {"type": "integer"},
                                "turn": {"type": ["integer", "null"]},
                            },
                            "required": ["persona", "run_idx", "turn"],
                        },
                    },
                    "culprit": {"enum": ["agent", "simulator", "judge"]},
                    "layer": {"enum": ["prompt", "tool_schema", "first_message"]},
                },
                "required": ["bug_id", "description", "generalized_rule", "evidence", "culprit", "layer"],
            },
        }
    },
    "required": ["bugs"],
}

SYSTEM = """You analyze failed test calls of a Turkish voice agent and write a failure report.
1. Group the failures into GENERALIZED behavioral bugs. A bug describes agent behaviour that would also fail other
   callers, never a single persona's detail. Merge failures with the same root cause.
2. generalized_rule: the rule the agent should follow, phrased as observable behaviour, usable verbatim in a prompt.
3. culprit: "agent" if the agent misbehaved; "simulator" if the caller broke character, contradicted its own facts, or
   asked for something impossible; "judge" if the verdict contradicts the transcript or the tool log.
4. layer: "prompt" (system prompt rule), "tool_schema" (tool description or parameter), or "first_message".
5. evidence: persona name, run_idx and the turn_idx where the failure shows.
bug_id: short snake_case. Order bugs by how many runs they explain."""


def render_run(scored: ScoredRun) -> str:
    run: RunResult = scored.run
    lines = [f"### persona={run.persona_name} run_idx={run.run_idx} ended={run.ended_reason}"]
    for turn in run.transcript:
        calls = f" tool_calls={json.dumps(turn.tool_calls, ensure_ascii=False)}" if turn.tool_calls else ""
        lines.append(f"[{turn.turn_idx}] {turn.role}: {turn.text}{calls}")
    if run.tool_calls:
        lines.append("TOOL LOG:")
        lines.extend(
            f"  [{call.turn_idx}] {call.name}({json.dumps(call.args, ensure_ascii=False)}) -> "
            f"{json.dumps(call.result, ensure_ascii=False, default=str)[:300]}"
            for call in run.tool_calls
        )
    lines.append("FAILED CHECKS:")
    lines.extend(
        f"  {verdict.check_name} (turn {verdict.evidence_turn}): {verdict.reason}"
        for verdict in scored.verdicts
        if not verdict.passed
    )
    return "\n".join(lines)


def require_split(runs: list[ScoredRun], personas: list[Persona], split: str) -> None:
    by_name = {persona.name: persona for persona in personas}
    for scored in runs:
        persona = by_name.get(scored.run.persona_name)
        if persona is None or persona.split != split:
            raise ValueError(f"run for persona {scored.run.persona_name!r} is not tagged {split!r}")


def analyze(version: str, failed: list[ScoredRun], personas: list[Persona]) -> FailureReport:
    require_split(failed, personas, "train")
    failed = [scored for scored in failed if not scored.passed]
    if not failed:
        return FailureReport(version=version)
    criteria = {persona.name: persona.successCriteria for persona in personas}
    sections = [
        f"successCriteria: {criteria.get(scored.run.persona_name, '')}\n{render_run(scored)}" for scored in failed
    ]
    payload = llm.call_llm(
        SYSTEM,
        f"Agent version {version}. {len(failed)} failed runs:\n\n" + "\n\n".join(sections),
        model=settings().builder_model,
        json_schema=REPORT_SCHEMA,
    )
    return FailureReport(version=version, bugs=[Bug.model_validate(bug) for bug in payload.get("bugs", [])])
