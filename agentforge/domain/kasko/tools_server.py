"""Mock kasko tools. Deterministic over policies.json with per-session state.

Run: uvicorn agentforge.domain.kasko.tools_server:app --port 8001
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request

POLICIES: list[dict[str, Any]] = json.loads((Path(__file__).parent / "policies.json").read_text())

app = FastAPI(title="kasko mock tools")

SESSIONS: dict[str, dict[str, Any]] = {}
CALLS: dict[str, list[dict[str, Any]]] = {}
_claim_counter = {"next": 1}


def reset_state() -> None:
    SESSIONS.clear()
    CALLS.clear()
    _claim_counter["next"] = 1


def normalize_date(value: Any) -> str:
    text = str(value or "").strip()
    match = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", text)
    if match:
        day, month, year = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return text


def normalize_policy(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def find_policy(policy_number: Any) -> dict[str, Any] | None:
    wanted = normalize_policy(policy_number)
    return next((p for p in POLICIES if p["policy_number"] == wanted), None)


def verify_identity(state: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    last4 = re.sub(r"\D", "", str(args.get("tckn_last4", "")))[-4:]
    birth = normalize_date(args.get("birth_date"))
    for policy in POLICIES:
        if policy["tckn"].endswith(last4) and len(last4) == 4 and policy["birth_date"] == birth:
            state["verified"] = policy["policy_number"]
            return {
                "verified": True,
                "customer_name": policy["customer_name"],
                "policy_number": policy["policy_number"],
            }
    state["failed_attempts"] = state.get("failed_attempts", 0) + 1
    return {"verified": False, "error": "Kimlik bilgileri eşleşmedi.", "failed_attempts": state["failed_attempts"]}


def _require_verified(state: dict[str, Any], policy_number: Any) -> dict[str, Any] | None:
    if not state.get("verified"):
        return {"error": "Kimlik doğrulanmadı. Önce verify_identity çağrılmalı."}
    policy = find_policy(policy_number)
    if policy is None:
        return {"error": f"Poliçe bulunamadı: {policy_number}"}
    if policy["policy_number"] != state["verified"]:
        return {"error": "Bu poliçe doğrulanan kişiye ait değil."}
    return None


def get_policy(state: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    error = _require_verified(state, args.get("policy_number"))
    if error:
        return error
    policy = find_policy(args["policy_number"])
    return {
        "policy_number": policy["policy_number"],
        "status": policy["status"],
        "vehicle": policy["vehicle"],
        "coverages": policy["coverages"],
        "exclusions": policy["exclusions"],
        "ferdi_kaza_limit_tl": policy["ferdi_kaza_limit_tl"],
    }


def create_claim(state: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    error = _require_verified(state, args.get("policy_number"))
    if error:
        return error
    policy = find_policy(args["policy_number"])
    if policy["status"] != "active":
        return {"error": "Poliçe aktif değil, hasar dosyası açılamaz."}
    missing = [field for field in ("date", "location", "description") if not str(args.get(field) or "").strip()]
    if "injury" not in args:
        missing.append("injury")
    if missing:
        return {"error": f"Eksik alanlar: {', '.join(missing)}"}
    claim_id = f"HSR-{_claim_counter['next']:06d}"
    _claim_counter["next"] += 1
    claim = {
        "claim_id": claim_id,
        "policy_number": policy["policy_number"],
        "date": normalize_date(args["date"]),
        "location": args["location"],
        "description": args["description"],
        "injury": bool(args["injury"]),
        "other_plate": args.get("other_plate") or "",
    }
    state.setdefault("claims", []).append(claim)
    return {"created": True, **claim, "next_step": "Eksper 2 iş günü içinde arayacak."}


def transfer_to_human(state: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    state["transferred"] = True
    return {"transferred": True, "reason": args.get("reason", ""), "queue_wait_s": 30}


TOOLS = {
    "verify_identity": verify_identity,
    "get_policy": get_policy,
    "create_claim": create_claim,
    "transfer_to_human": transfer_to_human,
}


def run_tool(session_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    state = SESSIONS.setdefault(session_id, {})
    handler = TOOLS.get(name)
    result = handler(state, args) if handler else {"error": f"Bilinmeyen araç: {name}"}
    CALLS.setdefault(session_id, []).append(
        {"session_id": session_id, "name": name, "args": args, "result": result, "timestamp": time.time()}
    )
    return result


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            return {"raw": raw}
    return {}


def _session_id(request: Request, body: dict[str, Any]) -> str:
    if request.query_params.get("session_id"):
        return request.query_params["session_id"]
    message = body.get("message") if isinstance(body.get("message"), dict) else {}
    for candidate in (
        (message.get("call") or {}).get("id") if isinstance(message.get("call"), dict) else None,
        ((message.get("assistant") or {}).get("metadata") or {}).get("session_id")
        if isinstance(message.get("assistant"), dict)
        else None,
        (message.get("metadata") or {}).get("session_id") if isinstance(message.get("metadata"), dict) else None,
        (body.get("metadata") or {}).get("session_id") if isinstance(body.get("metadata"), dict) else None,
    ):
        if candidate:
            return str(candidate)
    return request.headers.get("x-session-id") or "default"


def _vapi_calls(message: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    calls = []
    for item in message.get("toolCallList") or []:
        function = item.get("function") or {}
        calls.append((item.get("id", ""), function.get("name") or item.get("name", ""), _parse_args(function.get("arguments"))))
    if not calls:
        for item in message.get("toolWithToolCallList") or []:
            call = item.get("toolCall") or {}
            function = call.get("function") or {}
            name = function.get("name") or (item.get("function") or {}).get("name") or item.get("name", "")
            calls.append((call.get("id", ""), name, _parse_args(function.get("arguments"))))
    return calls


@app.post("/tools/{name}")
async def tool_endpoint(name: str, request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    session_id = _session_id(request, body)
    message = body.get("message")
    if isinstance(message, dict) and (message.get("toolCallList") or message.get("toolWithToolCallList")):
        results = []
        for call_id, call_name, args in _vapi_calls(message):
            result = run_tool(session_id, call_name or name, args)
            results.append({"toolCallId": call_id, "result": json.dumps(result, ensure_ascii=False)})
        return {"results": results}
    args = {k: v for k, v in body.items() if k not in {"metadata", "session_id"}}
    return run_tool(session_id, name, args)


@app.get("/calls/{session_id}")
def get_calls(session_id: str) -> list[dict[str, Any]]:
    return CALLS.get(session_id, [])


@app.post("/reset")
def reset() -> dict[str, bool]:
    reset_state()
    return {"ok": True}


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}
