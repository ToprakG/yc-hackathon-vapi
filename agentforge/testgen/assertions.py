"""Global assertions (Freya format) from the SOP's hard rules."""

from __future__ import annotations

from agentforge import llm
from agentforge.config import settings
from agentforge.schemas import Assertion, ContextConfig

ASSERTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "assertions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "prompt": {"type": "string"}},
                "required": ["name", "prompt"],
            },
        }
    },
    "required": ["assertions"],
}


def generate_assertions(task_md: str) -> list[Assertion]:
    system = (
        "You turn a call-center SOP into global assertions that a judge checks on EVERY call transcript plus tool calls. "
        "One assertion per hard rule (including rules buried in paragraphs). Each prompt states what must be true, "
        "how to check it from the transcript and tool calls, and that it passes when the rule does not apply to this call. "
        "Names are short snake_case. Typically 5-8 assertions."
    )
    payload = llm.call_llm(system, f"SOP:\n{task_md}", model=settings().builder_model, json_schema=ASSERTIONS_SCHEMA)
    return [
        Assertion(
            name=item["name"],
            prompt=item["prompt"],
            contextConfig=ContextConfig(includeToolCalls=True, includeExtractionEvents=True),
        )
        for item in payload.get("assertions", [])
    ]
