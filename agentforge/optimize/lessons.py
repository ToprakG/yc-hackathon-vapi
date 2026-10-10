"""Lessons library (TEST_PLAN section 4, "her durumda yapılır"): recurring practice failures -> general builder rules.

mine: group failed checks in practice runs; for each failure type that recurs (>= min_count runs), an LLM writes
      one general rule from a few failing transcripts. Proposals go to results/collections/lessons.json.
test: append the proposed rules to every brief's agent and run the section-5 gate; accepted rules are locked into the
      template (the collections builder appends locked rules to every build).
"""

from __future__ import annotations

import json
from pathlib import Path

from agentforge import llm
from agentforge.config import RESULTS_DIR, settings
from agentforge.optimize.gepa import REFLECT_SYSTEM, clean_rules
from agentforge.run.scorer import render_transcript
from agentforge.schemas import ScoredRun

LESSONS_PATH = RESULTS_DIR / "collections" / "lessons.json"

LESSON_SCHEMA = {"type": "object", "properties": {"rule": {"type": "string"}, "why": {"type": "string"}},
                 "required": ["rule", "why"]}


def recurring(scored: list[ScoredRun], min_count: int = 3) -> dict[str, list[ScoredRun]]:
    """Failed check -> runs that failed it, for checks failed in at least `min_count` runs (judge errors excluded)."""
    by_check: dict[str, list[ScoredRun]] = {}
    for s in scored:
        for v in s.verdicts:
            if not v.passed and not v.reason.startswith("ERROR"):
                by_check.setdefault(v.check_name, []).append(s)
    return {k: v for k, v in sorted(by_check.items(), key=lambda kv: -len(kv[1])) if len(v) >= min_count}


def write_lesson(check: str, runs: list[ScoredRun], existing: list[str]) -> dict:
    examples = "\n\n---\n\n".join(f"CASE {s.run.persona_name}\n{render_transcript(s.run)[:2500]}" for s in runs[:3])
    user = (f"The agent keeps failing the check '{check}'. Write ONE general rule that prevents it, following the rule "
            f"format above. Rules already in the template:\n{json.dumps(existing, ensure_ascii=False)}\n\n"
            f"Return JSON {{\"rule\": str, \"why\": str}}.\n\nFAILING CALLS:\n\n{examples}")
    result = llm.call_llm(REFLECT_SYSTEM, user, model=settings().builder_model, json_schema=LESSON_SCHEMA, temperature=0.2)
    rule = clean_rules([result.get("rule", "")])
    return {"check": check, "rule": rule[0] if rule else "", "why": str(result.get("why", "")),
            "evidence": [f"{s.run.persona_name}#{s.run.run_idx}" for s in runs[:10]], "count": len(runs), "status": "proposed"}


def mine(scored: list[ScoredRun], existing: list[str], min_count: int = 3, path: Path | None = None) -> list[dict]:
    path = path or LESSONS_PATH
    known = json.loads(path.read_text()) if path.exists() else []
    seen = {lesson["check"] for lesson in known if lesson["status"] in ("proposed", "locked")}
    new = [write_lesson(check, runs, existing) for check, runs in recurring(scored, min_count).items() if check not in seen]
    lessons = known + [lesson for lesson in new if lesson["rule"]]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lessons, ensure_ascii=False, indent=1) + "\n")
    return lessons


def set_status(rules: list[str], status: str, path: Path | None = None) -> None:
    path = path or LESSONS_PATH
    lessons = json.loads(path.read_text())
    for lesson in lessons:
        if lesson["rule"] in rules:
            lesson["status"] = status
    path.write_text(json.dumps(lessons, ensure_ascii=False, indent=1) + "\n")
