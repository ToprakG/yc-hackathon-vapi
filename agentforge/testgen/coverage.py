"""Coverage personas: ordinary callers, one per main SOP path."""

from __future__ import annotations

from agentforge import llm
from agentforge.config import settings
from agentforge.schemas import Persona, ToolDef
from agentforge.testgen.adversary import PERSONA_RULES, GeneratedPersona, slugify, tools_brief

COVERAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "personas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "name": {"type": "string"},
                    "prompt": {"type": "string"},
                    "successCriteria": {"type": "string"},
                },
                "required": ["path", "name", "prompt", "successCriteria"],
            },
        }
    },
    "required": ["personas"],
}


def generate_coverage(task_md: str, tools: list[ToolDef], n: int = 6) -> list[Persona]:
    system = (
        "You write simulated callers that cover the main paths of a Turkish call-center SOP. "
        f"List the {n} most common paths a real caller takes and write one persona per path. "
        "Most callers are ordinary and cooperative; at most one may be mildly difficult. "
        "Each path gets a short kebab-case slug.\n" + PERSONA_RULES
    )
    user = f"SOP:\n{task_md}\n\nTOOLS:\n{tools_brief(tools)}"
    payload = llm.call_llm(system, user, model=settings().builder_model, json_schema=COVERAGE_SCHEMA, temperature=0.7)
    personas = []
    for item in payload.get("personas", [])[:n]:
        generated = GeneratedPersona.model_validate(item)
        path = slugify(item.get("path") or generated.name)
        personas.append(
            Persona(
                name=f"cov-{slugify(generated.name)}",
                prompt=generated.prompt,
                successCriteria=generated.successCriteria,
                tags=["coverage", f"path:{path}"],
            )
        )
    return personas
