"""Turn a TaskSpec into a schema-valid AgentConfig. Invalid configs are not stored."""

from __future__ import annotations

import os
from typing import Any

from loop.llm import LLMClient, parse_json_object
from loop.schema import SchemaError, validate_agent


def runtime_settings() -> dict[str, str]:
    return {
        "provider": "vapi",
        "model_provider": os.environ.get("VAPI_MODEL_PROVIDER", "openai"),
        "model": os.environ.get("VAPI_MODEL", "gpt-4o-mini"),
        "voice_provider": os.environ.get("VAPI_VOICE_PROVIDER", "vapi"),
        "voice_id": os.environ.get("VAPI_VOICE_ID", "Elliot"),
    }


def load_builder_prompt(path) -> tuple[str, str]:
    text = path.read_text()
    lines = text.splitlines()
    version = "builder-unversioned"
    if lines and lines[0].startswith("prompt_version:"):
        version = lines[0].split(":", 1)[1].strip()
        text = "\n".join(lines[1:]).strip()
    return version, text


def template_draft(task: dict[str, Any]) -> dict[str, Any]:
    """Offline stand-in used by --mock. The experiment builder is the LLM path."""
    tool_lines = []
    for tool in task["tools"]:
        errors = ", ".join(tool["errors"]) or "none"
        tool_lines.append(
            f"- {tool['name']}: {tool['description']} Side effect: {tool['side_effects']}. Errors: {errors}."
        )
    constraints = "\n".join(f"- {item}" for item in task["constraints"])
    success = "\n".join(f"- {item}" for item in task["success_criteria"])
    system_prompt = (
        f"You are a voice agent. Task: {task['description']}\n\n"
        f"Constraints:\n{constraints}\n\n"
        f"Success:\n{success}\n\n"
        f"Tools:\n" + "\n".join(tool_lines) + "\n\n"
        "Ask for any required field you do not know. Repeat names, dates, times, quantities, and ids "
        "before a write. Call a write tool only after an explicit yes. Never invent tool results. "
        "If the user corrects a value, replace the old one. If a tool errors, say what failed and what you need next."
    )
    return {
        "system_prompt": system_prompt,
        "first_message": "Hi, I can help with that. What details should I use?",
        "tools": [{"name": tool["name"], "description": tool["description"]} for tool in task["tools"]],
    }


def user_message(task: dict[str, Any]) -> str:
    import json

    return (
        "Compile this TaskSpec into the JSON object described in your instructions.\n\n"
        + json.dumps(task, indent=2)
    )


def assemble(task: dict[str, Any], draft: dict[str, Any], prompt_version: str) -> dict[str, Any]:
    if not isinstance(draft, dict):
        raise SchemaError(["builder draft must be an object"])
    errors: list[str] = []
    for key in ("system_prompt", "first_message", "tools"):
        if key not in draft:
            errors.append(f"builder draft missing {key}")
    tools = draft.get("tools")
    by_name: dict[str, Any] = {}
    if not isinstance(tools, list):
        errors.append("builder draft tools must be a list")
    else:
        for tool in tools:
            if isinstance(tool, dict) and isinstance(tool.get("name"), str):
                by_name[tool["name"]] = tool
            else:
                errors.append("each builder tool needs a name")
    expected = [tool["name"] for tool in task["tools"]]
    if sorted(by_name) != sorted(expected):
        errors.append(f"builder tools must be exactly {expected}")
    if errors:
        raise SchemaError(errors)

    merged_tools = []
    for source in task["tools"]:
        proposed = by_name[source["name"]]
        description = proposed.get("description")
        if not isinstance(description, str) or not description.strip():
            description = source["description"]
        merged_tools.append({**source, "description": description.strip(), "parameters": source["parameters"]})

    return {
        "id": f"{task['id']}-v1",
        "task_id": task["id"],
        "parent_id": None,
        "version": "v1",
        "prompt_version": prompt_version,
        "system_prompt": str(draft["system_prompt"]).strip(),
        "first_message": str(draft["first_message"]).strip(),
        "tools": merged_tools,
        "runtime": runtime_settings(),
    }


def build_agent(
    task: dict[str, Any],
    *,
    prompt_text: str,
    prompt_version: str,
    llm: LLMClient | None = None,
    draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if draft is None:
        if llm is None:
            raise RuntimeError("build_agent needs an LLM client or a draft")
        raw = llm.complete(system=prompt_text, user=user_message(task))
        try:
            draft = parse_json_object(raw)
            config = assemble(task, draft, prompt_version)
            return validate_agent(config, task)
        except (SchemaError, ValueError, KeyError) as first_error:
            repair = llm.complete(
                system=prompt_text,
                user=(
                    "Your previous JSON failed validation. Return only the corrected JSON object.\n\n"
                    f"Errors: {first_error}\n\nPrevious output:\n{raw}"
                ),
            )
            draft = parse_json_object(repair)
    config = assemble(task, draft, prompt_version)
    return validate_agent(config, task)
