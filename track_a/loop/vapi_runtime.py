"""HTTP helper and the Vapi runtime adapter.

Builder code imports neither this module's adapter nor the Vapi URL.
`loop.llm` uses `request_json` only as a transport.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable


Transport = Callable[[str, str, dict[str, Any] | None, dict[str, str]], tuple[int, dict[str, Any]]]


def request_json(
    method: str,
    url: str,
    body: dict[str, Any] | None,
    headers: dict[str, str],
    timeout: int = 90,
) -> tuple[int, dict[str, Any]]:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode()
            payload = json.loads(raw) if raw else {}
            if not isinstance(payload, dict):
                raise RuntimeError(f"Vapi {method} {url} returned a non-object body")
            return response.status, payload
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:2000]
        raise RuntimeError(f"Vapi {method} {url} -> {error.code}: {detail}") from None


class VapiRuntime:
    """Publishes an AgentConfig with POST /assistant, or PATCH when an id already exists.

    Simulations stay on this adapter for Phase 2 (`POST /eval/simulation/run`). The builder
    never calls Vapi itself.
    """

    def __init__(self, api_key: str, base_url: str = "https://api.vapi.ai", transport: Transport | None = None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.transport = transport or request_json

    @classmethod
    def from_env(cls) -> "VapiRuntime":
        api_key = os.environ.get("VAPI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("VAPI_API_KEY is not set. Add it to .env before publishing.")
        return cls(api_key=api_key, base_url=os.environ.get("VAPI_BASE_URL", "https://api.vapi.ai"))

    def publish(self, config: dict[str, Any], existing_id: str | None = None) -> dict[str, Any]:
        body = assistant_payload(config)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if existing_id:
            status, payload = self.transport("PATCH", f"{self.base_url}/assistant/{existing_id}", body, headers)
        else:
            status, payload = self.transport("POST", f"{self.base_url}/assistant", body, headers)
        if status >= 300:
            raise RuntimeError(f"Vapi publish failed with status {status}")
        assistant_id = payload.get("id")
        if not isinstance(assistant_id, str) or not assistant_id:
            raise RuntimeError("Vapi publish response did not include an assistant id")
        return {
            "provider": "vapi",
            "assistant_id": assistant_id,
            "agent_version": config["id"],
            "request": body,
        }

    def simulate(self, config: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            "Phase 2 runs personas through POST /eval/simulation/run on this adapter. "
            f"Refusing to simulate {scenario.get('id')} against {config.get('id')} early."
        )


def assistant_payload(config: dict[str, Any]) -> dict[str, Any]:
    runtime = config["runtime"]
    payload: dict[str, Any] = {
        "name": config["id"][:40],
        "firstMessage": config["first_message"],
        "firstMessageMode": "assistant-speaks-first",
        "model": {
            "provider": runtime["model_provider"],
            "model": runtime["model"],
            "messages": [{"role": "system", "content": config["system_prompt"]}],
            "tools": [function_tool(tool) for tool in config["tools"]],
        },
        "voice": {
            "provider": runtime["voice_provider"],
            "voiceId": runtime["voice_id"],
        },
        "metadata": {
            "task_id": config["task_id"],
            "agent_version": config["id"],
            "prompt_version": config["prompt_version"],
        },
    }
    return payload


def function_tool(tool: dict[str, Any]) -> dict[str, Any]:
    description = tool["description"]
    if tool["side_effects"] not in description.lower() and tool["side_effects"] != "none":
        description = f"{description} Side effect: {tool['side_effects']}."
    body: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": description,
            "parameters": tool["parameters"],
        },
    }
    server_url = os.environ.get("VAPI_TOOL_SERVER_URL", "").strip()
    if server_url:
        body["server"] = {"url": server_url}
    return body
