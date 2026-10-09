"""One call_llm for every LLM box. Supports anthropic and openai."""

from __future__ import annotations

import json
import random
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
            f"{system}\n\nReply with ONE JSON object only, no prose. The JSON Schema below describes that object; "
            f"return an instance with real values, NOT the schema itself:\n{json.dumps(json_schema)}"
        )
    attempts = 6
    for attempt in range(attempts):
        try:
            if provider == "anthropic":
                text = _anthropic(system, user, name, temperature, max_tokens)
            elif provider == "openai":
                text = _openai(system, user, name, temperature, max_tokens, json_mode=json_schema is not None)
            else:
                raise ValueError(f"unknown LLM provider: {provider}")
            return unwrap_schema_echo(parse_json(text), json_schema) if json_schema is not None else text
        except ValueError:
            if attempt == attempts - 1:
                raise
        except Exception as error:  # rate limits and transient 5xx
            if attempt == attempts - 1 or not _retryable(error):
                raise
        time.sleep(min(2**attempt, 20) + random.random())  # jitter so parallel callers don't retry in lockstep
    raise RuntimeError("unreachable")


def _retryable(error: Exception) -> bool:
    status = getattr(error, "status_code", None) or getattr(getattr(error, "response", None), "status_code", None)
    return status is None or status == 429 or status >= 500


def _anthropic(system: str, user: str, model: str, temperature: float, max_tokens: int) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=settings().anthropic_api_key or None)
    # Current Claude models reject sampling params (temperature is gone from the SDK) and always think,
    # so thinking tokens count against max_tokens; give them room and set effort explicitly.
    response = client.messages.create(
        model=model,
        system=system,
        messages=[{"role": "user", "content": user}],
        max_tokens=max(max_tokens, 16000),
        output_config={"effort": "medium"},
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


def unwrap_schema_echo(payload: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Some models answer with the schema shape, values under properties.<key>.value. Recover the instance."""
    required = schema.get("required") or []
    if all(key in payload for key in required) or not isinstance(payload.get("properties"), dict):
        return payload
    properties = payload["properties"]
    return {
        key: value.get("value", value.get("default")) if isinstance(value, dict) and ("value" in value or "default" in value) else value
        for key, value in properties.items()
    }


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
