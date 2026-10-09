"""LLM clients used by the builder. The voice runtime is a separate adapter."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Protocol

from loop.vapi_runtime import request_json


class LLMClient(Protocol):
    def complete(self, *, system: str, user: str) -> str: ...


class OpenAIChatClient:
    def __init__(self, api_key: str, model: str, base_url: str = "https://api.openai.com/v1", transport=None):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.transport = transport or request_json

    def complete(self, *, system: str, user: str) -> str:
        status, payload = self.transport(
            "POST",
            f"{self.base_url}/chat/completions",
            {
                "model": self.model,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        if status >= 300:
            raise RuntimeError(f"OpenAI chat failed with status {status}")
        return payload["choices"][0]["message"]["content"]


class VapiChatClient:
    """Builder calls through Vapi chat so one VAPI_API_KEY can run the loop."""

    def __init__(
        self,
        api_key: str,
        model: str,
        model_provider: str = "openai",
        base_url: str = "https://api.vapi.ai",
        transport=None,
    ):
        self.api_key = api_key
        self.model = model
        self.model_provider = model_provider
        self.base_url = base_url.rstrip("/")
        self.transport = transport or request_json

    def complete(self, *, system: str, user: str) -> str:
        status, payload = self.transport(
            "POST",
            f"{self.base_url}/chat",
            {
                "input": user,
                "stream": False,
                "assistant": {
                    "name": "agent-builder",
                    "model": {
                        "provider": self.model_provider,
                        "model": self.model,
                        "temperature": 0.2,
                        "messages": [{"role": "system", "content": system}],
                    },
                },
            },
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        if status >= 300:
            raise RuntimeError(f"Vapi chat failed with status {status}")
        return extract_chat_text(payload)


def extract_chat_text(payload: dict[str, Any]) -> str:
    output = payload.get("output")
    if isinstance(output, str):
        return output.strip()
    parts: list[str] = []
    for item in output or []:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict):
                    parts.append(str(block.get("text") or block.get("content") or ""))
    text = "\n".join(part for part in parts if part).strip()
    if not text:
        raise RuntimeError("Vapi chat returned no assistant text")
    return text


def make_llm_client() -> LLMClient:
    provider = os.environ.get("BUILDER_PROVIDER", "").strip().lower()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    vapi_key = os.environ.get("VAPI_API_KEY", "").strip()
    model = os.environ.get("BUILDER_MODEL", "gpt-4o-mini")
    if provider == "openai" or (not provider and openai_key):
        if not openai_key:
            raise RuntimeError("BUILDER_PROVIDER=openai but OPENAI_API_KEY is missing")
        return OpenAIChatClient(
            api_key=openai_key,
            model=model,
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
    if provider == "vapi" or (not provider and vapi_key):
        if not vapi_key:
            raise RuntimeError("BUILDER_PROVIDER=vapi but VAPI_API_KEY is missing")
        return VapiChatClient(
            api_key=vapi_key,
            model=model,
            model_provider=os.environ.get("VAPI_MODEL_PROVIDER", "openai"),
            base_url=os.environ.get("VAPI_BASE_URL", "https://api.vapi.ai"),
        )
    raise RuntimeError(
        "No builder credentials. Set VAPI_API_KEY or OPENAI_API_KEY in .env. "
        "Use --mock to store a template V1 without calling a model."
    )


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("model output did not contain a JSON object")
    payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("model output JSON must be an object")
    return payload
