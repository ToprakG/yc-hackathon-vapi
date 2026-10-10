"""Mock collections backend for one brief. Deterministic over accounts.json, enforces the brief's policy.

In-process: `CollectionsBackend(brief).run_tool(session_id, name, args)` (LocalPlatform uses this).
Over HTTP (Vapi / Freya webhooks):
    COLLECTIONS_BRIEF=marmara_standard uvicorn agentforge.domain.collections.tools_server:app --port 8002
    POST /tools/{name}            -> brief from COLLECTIONS_BRIEF
    POST /{brief}/tools/{name}    -> explicit brief
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import date, timedelta
from typing import Any

from fastapi import FastAPI, Request

from agentforge.domain.collections import brief_dir, load_accounts, load_policy, today
from agentforge.domain.collections.policy import Policy
from agentforge.domain.kasko.tools_server import _session_id, _vapi_calls, normalize_date


def parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(normalize_date(value)[:10])
    except ValueError:
        return None


def promise_violations(policy: Policy, account: dict[str, Any], args: dict[str, Any], on: date) -> list[str]:
    """Why a promise breaks the brief's limits ([] = allowed). Shared by the mock backend and the code checks."""
    problems = []
    overdue = float(account["overdue_amount_tl"])
    try:
        amount = float(args.get("amount_tl") or 0)
        installments = int(args.get("installments") or 1)
        discount = float(args.get("discount_pct") or 0)
    except (TypeError, ValueError):
        return ["amount_tl, installments and discount_pct must be numbers"]
    when = parse_date(args.get("date"))
    if when is None:
        problems.append("date must be YYYY-MM-DD")
    elif when < on or when > on + timedelta(days=policy.max_promise_days):
        problems.append(f"date must be within {policy.max_promise_days} days from {on.isoformat()}")
    if amount <= 0:
        problems.append("amount_tl must be positive")
    if discount:
        if not policy.allow_discount:
            problems.append("no discounts allowed")
        elif discount > policy.max_discount_pct:
            problems.append(f"discount at most {policy.max_discount_pct:g}%")
        elif installments != 1:
            problems.append("discount only for a one-off full payment")
        elif policy.discount_max_days is not None and when is not None and when > on + timedelta(days=policy.discount_max_days):
            problems.append(f"discount only if paid within {policy.discount_max_days} days")
    if installments < 1:
        problems.append("installments must be at least 1")
    elif installments == 1:
        due = overdue * (1 - discount / 100)
        if amount + 0.01 < due:
            problems.append(f"a one-off payment must cover the overdue amount ({due:.2f} TL)")
    else:
        if not policy.allow_plans:
            problems.append("payment plans are not allowed")
        if installments > policy.max_installments:
            problems.append(f"at most {policy.max_installments} installments")
        if amount + 0.01 < overdue * policy.min_first_payment_pct / 100:
            problems.append(f"first payment at least {policy.min_first_payment_pct:g}% of the overdue amount")
        rest = max(0.0, overdue - amount) / (installments - 1)
        if policy.min_installment_tl and rest + 0.01 < policy.min_installment_tl and amount < overdue:
            problems.append(f"each installment at least {policy.min_installment_tl:g} TL")
    return problems


class CollectionsBackend:
    def __init__(self, brief: str):
        self.brief = brief
        self.policy = load_policy(brief_dir(brief))
        self.accounts = load_accounts(brief)
        self.sessions: dict[str, dict[str, Any]] = {}
        self.calls: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self._counter = 0

    def account(self, account_id: Any) -> dict[str, Any] | None:
        wanted = re.sub(r"\s+", "", str(account_id or "")).upper()
        return next((a for a in self.accounts if a["account_id"] == wanted), None)

    def run_tool(self, session_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
        canonical = self.policy.canonical(name)
        handler = getattr(self, f"_{canonical}") if canonical in _HANDLERS else None
        with self._lock:
            state = self.sessions.setdefault(session_id, {})
            result = handler(state, args) if handler else {"error": f"Bilinmeyen araç: {name}"}
            self.calls.setdefault(session_id, []).append(
                {"session_id": session_id, "name": name, "args": args, "result": result, "timestamp": time.time()})
        return result

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}-{self._counter:05d}"

    def _verified(self, state: dict[str, Any], args: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if not state.get("verified"):
            return None, {"error": "Kimlik doğrulanmadı. Önce kimlik doğrulama yapılmalı."}
        account = self.account(args.get("account_id") or state["verified"])
        if account is None or account["account_id"] != state["verified"]:
            return None, {"error": "Bu hesap doğrulanan kişiye ait değil."}
        return account, None

    def _verify_identity(self, state, args):
        if state.get("failed_attempts", 0) >= self.policy.max_verification_attempts:
            return {"verified": False, "error": "Doğrulama deneme hakkı doldu.", "attempts_left": 0}
        last4 = re.sub(r"\D", "", str(args.get("tckn_last4", "")))[-4:]
        birth = normalize_date(args.get("birth_date"))
        for account in self.accounts:
            if len(last4) == 4 and account["tckn"].endswith(last4) and account["birth_date"] == birth:
                state["verified"] = account["account_id"]
                return {"verified": True, "customer_name": account["customer_name"], "account_id": account["account_id"]}
        state["failed_attempts"] = state.get("failed_attempts", 0) + 1
        left = self.policy.max_verification_attempts - state["failed_attempts"]
        return {"verified": False, "error": "Kimlik bilgileri eşleşmedi.", "attempts_left": max(0, left)}

    def _get_account(self, state, args):
        account, error = self._verified(state, args)
        if error:
            return error
        return {k: account[k] for k in ("account_id", "product", "overdue_amount_tl", "total_balance_tl", "days_past_due", "status")}

    def _log_promise_to_pay(self, state, args):
        account, error = self._verified(state, args)
        if error:
            return error
        problems = promise_violations(self.policy, account, args, today())
        if problems:
            return {"logged": False, "error": "Söz bankanın limitlerine uymuyor.", "violations": problems}
        promise_id = self._next_id("PTP")
        state.setdefault("promises", []).append(promise_id)
        return {"logged": True, "promise_id": promise_id, "account_id": account["account_id"],
                "amount_tl": float(args["amount_tl"]), "date": normalize_date(args["date"]),
                "installments": int(args.get("installments") or 1)}

    def _log_dispute(self, state, args):
        account, error = self._verified(state, args)
        if error:
            return error
        if not str(args.get("reason") or "").strip():
            return {"logged": False, "error": "reason boş olamaz."}
        state["disputed"] = True
        return {"logged": True, "dispute_id": self._next_id("ITR"), "account_id": account["account_id"],
                "next_step": "İtiraz ekibi 5 iş günü içinde dönecek; bu sürede tahsilat araması yapılmaz."}

    def _schedule_callback(self, state, args):
        when = str(args.get("datetime") or "").strip()
        if not re.match(r"\d{4}-\d{2}-\d{2}", when):
            return {"scheduled": False, "error": "datetime YYYY-MM-DD HH:MM olmalı."}
        return {"scheduled": True, "callback_id": self._next_id("GA"), "datetime": when}

    def _mark_do_not_call(self, state, args):
        state["do_not_call"] = True
        return {"marked": True, "reason": args.get("reason", "")}

    def _transfer_to_human(self, state, args):
        state["transferred"] = True
        return {"transferred": True, "reason": args.get("reason", ""), "queue_wait_s": 30}


_HANDLERS = {"verify_identity", "get_account", "log_promise_to_pay", "log_dispute", "schedule_callback",
             "mark_do_not_call", "transfer_to_human"}

_BACKENDS: dict[str, CollectionsBackend] = {}


def backend(brief: str) -> CollectionsBackend:
    if brief not in _BACKENDS:
        _BACKENDS[brief] = CollectionsBackend(brief)
    return _BACKENDS[brief]


app = FastAPI(title="collections mock tools")


async def _handle(brief: str, name: str, request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body if isinstance(body, dict) else {}
    session_id = _session_id(request, body)
    tools = backend(brief)
    message = body.get("message")
    if isinstance(message, dict) and (message.get("toolCallList") or message.get("toolWithToolCallList")):
        results = [{"toolCallId": call_id, "result": json.dumps(tools.run_tool(session_id, call_name or name, args), ensure_ascii=False)}
                   for call_id, call_name, args in _vapi_calls(message)]
        return {"results": results}
    return tools.run_tool(session_id, name, {k: v for k, v in body.items() if k not in {"metadata", "session_id"}})


@app.post("/tools/{name}")
async def default_brief_tool(name: str, request: Request) -> dict[str, Any]:
    return await _handle(os.environ.get("COLLECTIONS_BRIEF", "marmara_standard"), name, request)


@app.post("/{brief}/tools/{name}")
async def brief_tool(brief: str, name: str, request: Request) -> dict[str, Any]:
    return await _handle(brief, name, request)


@app.get("/{brief}/calls/{session_id}")
def calls(brief: str, session_id: str) -> list[dict[str, Any]]:
    return backend(brief).calls.get(session_id, [])


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "today": today().isoformat()}

