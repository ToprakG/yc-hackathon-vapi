"""Freya-style scoring: an LLM judge reads the transcript (plus tool calls / extraction events when enabled)."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

from rich.console import Console

from agentforge import llm
from agentforge.config import settings, split_model
from agentforge.schemas import Assertion, Persona, RunResult, ScoredRun, Verdict

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "passed": {"type": "boolean"},
        "reason": {"type": "string"},
        "evidence_turn": {"type": ["integer", "null"]},
    },
    "required": ["passed", "reason", "evidence_turn"],
}

JUDGE_SYSTEM = (
    "You evaluate a phone conversation between a voice agent (assistant) and a caller (user). "
    "Judge only what is observable in the transcript and the logs you are given. "
    "Be strict: if the requirement is not clearly met, it fails. "
    "But a conditional rule (\"if the caller ...\", \"when an injury ...\") whose condition never occurs in this "
    "conversation is not applicable and PASSES; say so in the reason. "
    "evidence_turn is the turn index that best supports your verdict, or null."
)

_console = Console(stderr=True)
_warned = threading.Event()


def _warn_same_provider() -> None:
    if _warned.is_set():
        return
    _warned.set()
    cfg = settings()
    if split_model(cfg.judge_model)[0] == split_model(cfg.agent_model)[0]:
        _console.print(
            f"[yellow]warning: JUDGE_MODEL ({cfg.judge_model}) and AGENT_MODEL ({cfg.agent_model}) "
            "use the same provider; the judge may be lenient on its own family.[/yellow]"
        )


def render_transcript(run: RunResult) -> str:
    lines = []
    for turn in run.transcript:
        text = turn.text
        if turn.tool_calls:
            text = f"{text} [tool_calls: {json.dumps(turn.tool_calls, ensure_ascii=False)}]".strip()
        lines.append(f"[{turn.turn_idx}] {turn.role}: {text}")
    return "\n".join(lines) or "(empty transcript)"


def render_context(run: RunResult, include_tool_calls: bool, include_extraction: bool) -> str:
    parts = [f"TRANSCRIPT:\n{render_transcript(run)}"]
    if include_tool_calls:
        calls = [call.model_dump(mode="json") for call in run.tool_calls]
        parts.append(f"TOOL CALLS:\n{json.dumps(calls, ensure_ascii=False, indent=1) if calls else '(none)'}")
    if include_extraction:
        events = [event.model_dump(mode="json") for event in run.extraction_events]
        parts.append(f"EXTRACTION EVENTS:\n{json.dumps(events, ensure_ascii=False, indent=1) if events else '(none)'}")
    return "\n\n".join(parts)


def judge(check_name: str, instructions: str, context: str) -> Verdict:
    user = f"{instructions}\n\n{context}"
    try:
        result = llm.call_llm(
            JUDGE_SYSTEM, user, model=settings().judge_model, json_schema=JUDGE_SCHEMA, temperature=0
        )
    except Exception as error:
        return Verdict(check_name=check_name, passed=False, reason=f"ERROR: judge failed: {error}")
    evidence = result.get("evidence_turn")
    return Verdict(
        check_name=check_name,
        passed=result.get("passed") is True,
        reason=str(result.get("reason", "")),
        evidence_turn=evidence if isinstance(evidence, int) and not isinstance(evidence, bool) else None,
    )


def score_run(run: RunResult, persona: Persona, assertions: list[Assertion]) -> ScoredRun:
    if run.ended_reason.startswith("error"):
        verdict = Verdict(check_name="successCriteria", passed=False, reason=f"run failed: {run.ended_reason}")
        return ScoredRun(run=run, verdicts=[verdict], passed=False)
    _warn_same_provider()

    criteria = f"SUCCESS CRITERIA for caller '{persona.name}':\n{persona.successCriteria}"
    if persona.evaluationPrompt:
        criteria = f"{persona.evaluationPrompt}\n\n{criteria}"
    checks = [("successCriteria", criteria, render_context(run, True, True))]
    for assertion in assertions:
        ctx = assertion.contextConfig
        instructions = f"ASSERTION '{assertion.name}' (must hold for the whole conversation):\n{assertion.prompt}"
        checks.append((assertion.name, instructions, render_context(run, ctx.includeToolCalls, ctx.includeExtractionEvents)))
    with ThreadPoolExecutor(max_workers=len(checks)) as pool:
        verdicts = list(pool.map(lambda check: judge(*check), checks))
    return ScoredRun(run=run, verdicts=verdicts, passed=all(v.passed for v in verdicts))
