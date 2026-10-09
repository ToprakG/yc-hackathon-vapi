"""One call_llm for every LLM box. Supports anthropic and openai."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from agentforge.config import settings, split_model


def call_llm(
    system: str,
    user: str,
    model: str | None = None,
    json_schema: dict[str, Any] | None = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> str | dict[str, Any]:
    """Return text, or a parsed dict when json_schema is given."""
    provider, name = split_model(model or settings().builder_model)
    if json_schema is not None:
        system = (
            f"{system}\n\nReply with ONE JSON object only, no prose, matching this JSON schema:\n"
            f"{json.dumps(json_schema)}"
        )
    for attempt in range(4):
        try:
            if provider == "anthropic":
                text = _anthropic(system, user, name, temperature, max_tokens)
            elif provider == "openai":
                text = _openai(system, user, name, temperature, max_tokens, json_mode=json_schema is not None)
            else:
                raise ValueError(f"unknown LLM provider: {provider}")
            return parse_json(text) if json_schema is not None else text
        except ValueError:
            if attempt == 3:
                raise
        except Exception as error:  # rate limits and transient 5xx
            if attempt == 3 or not _retryable(error):
                raise
        time.sleep(2**attempt)
    raise RuntimeError("unreachable")


def _retryable(error: Exception) -> bool:
    status = getattr(error, "status_code", None) or getattr(getattr(error, "response", None), "status_code", None)
    return status is None or status == 429 or status >= 500


def _anthropic(system: str, user: str, model: str, temperature: float, max_tokens: int) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=settings().anthropic_api_key or None)
    response = client.messages.create(
        model=model,
        system=system,
        messages=[{"role": "user", "content": user}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return "".join(block.text for block in response.content if block.type == "text")


def _openai(system: str, user: str, model: str, temperature: float, max_tokens: int, json_mode: bool) -> str:
    import openai

    client = openai.OpenAI(api_key=settings().openai_api_key or None)
    kwargs: dict[str, Any] = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )
    return response.choices[0].message.content or ""


def parse_json(text: str) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating fences and stray prose."""
    stripped = text.strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
    stripped = re.sub(r"\s*```$", "", stripped)
    candidates = [stripped]
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        candidates.append(stripped[start : end + 1])
    missing = stripped.count("}") - stripped.count("{")
    if missing > 0:
        candidates.append("{" * missing + stripped)
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise ValueError(f"model output was not a JSON object: {text[:200]!r}")
