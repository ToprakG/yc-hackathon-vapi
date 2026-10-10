"""call_llm for T-CC: a stdlib port of agentforge.llm (same contract, same provider:model convention).

`.venv310` has no anthropic/openai/httpx/dotenv packages, so this talks HTTPS with urllib. Every call is recorded in
the trace (model, purpose, tokens, seconds) and is bounded by the build's wall clock (`deadline`, a time.time()).
"""

from __future__ import annotations

import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from builder.template_cc.io import REPO

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"


class LLMError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class OutOfTime(RuntimeError):
    pass


def load_env(path: Path | None = None) -> None:
    """KEY=VALUE / export KEY=VALUE lines from the repo .env. A value already in the process wins."""
    path = Path(path) if path else REPO / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if v and not os.environ.get(k):
            os.environ[k] = v


def split_model(model: str) -> tuple[str, str]:
    """(provider, name) for "openai:gpt-x", "anthropic:claude-x", or a bare name (claude* -> anthropic)."""
    if ":" in model:
        provider, name = model.split(":", 1)
        return provider.strip().lower(), name.strip()
    return ("anthropic", model) if model.lower().startswith("claude") else ("openai", model)


def _post(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise LLMError(f"POST {url} -> {e.code}: {e.read().decode(errors='replace')[:800]}", status=e.code) from None
    except urllib.error.URLError as e:
        raise LLMError(f"POST {url}: {e.reason}") from None


# Tests replace this to avoid any network call.
TRANSPORT = _post


def _anthropic(system, user, model, max_tokens, effort, timeout) -> tuple[str, dict]:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise LLMError("ANTHROPIC_API_KEY is empty", status=401)
    body = TRANSPORT(ANTHROPIC_URL, {"x-api-key": key, "anthropic-version": "2023-06-01"}, {
        "model": model, "system": system, "messages": [{"role": "user", "content": user}],
        "max_tokens": max(max_tokens, 16000), "output_config": {"effort": effort}}, timeout)
    text = "".join(b.get("text", "") for b in body.get("content") or [] if b.get("type") == "text")
    u = body.get("usage") or {}
    return text, {"in": u.get("input_tokens"), "out": u.get("output_tokens")}


def _openai(system, user, model, temperature, max_tokens, json_mode, timeout) -> tuple[str, dict]:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise LLMError("OPENAI_API_KEY is empty", status=401)
    payload: dict[str, Any] = {"model": model, "temperature": temperature, "max_tokens": max_tokens,
                               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    body = TRANSPORT(OPENAI_URL, {"Authorization": "Bearer " + key}, payload, timeout)
    text = ((body.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    u = body.get("usage") or {}
    return text, {"in": u.get("prompt_tokens"), "out": u.get("completion_tokens")}


def _retryable(error: Exception) -> bool:
    status = getattr(error, "status", None)
    return status is None or status == 429 or status >= 500


def call_llm(system: str, user: str, model: str, json_schema: dict | None = None, temperature: float = 0.2,
             max_tokens: int = 4096, effort: str = "medium", *, trace=None, purpose: str = "llm call",
             deadline: float | None = None, attempts: int = 4):
    """Return text, or a parsed dict when json_schema is given. Retries 429/5xx and unparsable JSON."""
    load_env()
    provider, name = split_model(model)
    if json_schema is not None:
        system = (f"{system}\n\nReply with ONE JSON object only, no prose. The JSON Schema below describes that "
                  f"object; return an instance with real values, NOT the schema itself:\n{json.dumps(json_schema)}")
    last: Exception | None = None
    for attempt in range(attempts):
        left = None if deadline is None else deadline - time.time()
        if left is not None and left < 5:
            raise OutOfTime(f"no time left for {purpose}")
        timeout = 600 if left is None else max(5.0, min(600.0, left))
        t0 = time.time()
        try:
            if provider == "anthropic":
                text, usage = _anthropic(system, user, name, max_tokens, effort, timeout)
            elif provider == "openai":
                text, usage = _openai(system, user, name, temperature, max_tokens, json_schema is not None, timeout)
            else:
                raise ValueError(f"unknown LLM provider: {provider}")
            if trace:
                trace.model_call(model, purpose + (f" (retry {attempt})" if attempt else ""), usage.get("in"),
                                 usage.get("out"), None, time.time() - t0)
            if json_schema is None:
                return text
            return unwrap_schema_echo(parse_json(text), json_schema)
        except ValueError as e:  # unparsable JSON: ask again
            last = e
            if trace:
                trace.warn(f"{purpose}: {e}")
        except LLMError as e:
            last = e
            if trace:
                trace.model_call(model, purpose, seconds=time.time() - t0, error=str(e))
            if not _retryable(e):
                raise
        if attempt < attempts - 1:
            time.sleep(min(2 ** attempt, 20) + random.random())
    raise last if last else RuntimeError("call_llm failed")


def unwrap_schema_echo(payload: dict, schema: dict) -> dict:
    """Some models answer with the schema shape, values under properties.<key>.value. Recover the instance."""
    required = schema.get("required") or []
    if all(k in payload for k in required) or not isinstance(payload.get("properties"), dict):
        return payload
    return {k: v.get("value", v.get("default")) if isinstance(v, dict) and ("value" in v or "default" in v) else v
            for k, v in payload["properties"].items()}


def parse_json(text: str) -> dict:
    """A JSON object from model output, tolerating fences and stray prose."""
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    cands = [s]
    a, b = s.find("{"), s.rfind("}")
    if a != -1 and b > a:
        cands.append(s[a: b + 1])
    for c in cands:
        try:
            obj = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError(f"model output was not a JSON object: {text[:200]!r}")
