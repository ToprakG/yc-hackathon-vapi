"""Collections domain: one folder per bank brief under briefs/<id>/.

Each brief folder is a normal domain pack (`sop.md` + `tools.json`, so `load_domain` works on it) plus test-only files
the builder never reads: `policy.json` (ground truth), `accounts.json` (mock customers), `personas.json` (16 case types),
`unit_tests.json` (4 critical moments). `python -m agentforge.domain.collections prepare` regenerates the derived files.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

from agentforge.domain.collections.policy import Policy, load_policy
from agentforge.schemas import ToolDef

COLLECTIONS_DIR = Path(__file__).parent
BRIEFS_DIR = COLLECTIONS_DIR / "briefs"


def list_briefs() -> list[str]:
    return sorted(p.name for p in BRIEFS_DIR.iterdir() if (p / "sop.md").exists())


def brief_dir(brief: str | Path) -> Path:
    path = Path(brief)
    return path if path.is_dir() else BRIEFS_DIR / str(brief)


def today() -> date:
    """The date the mock backend, the agent's {{today}} variable and the checks all agree on."""
    fixed = os.environ.get("COLLECTIONS_TODAY")
    return date.fromisoformat(fixed) if fixed else date.today()


CANONICAL_TOOL_DEFS: dict[str, dict[str, Any]] = {
    "verify_identity": {
        "description": "Aranan kişinin kimliğini T.C. kimlik numarasının son 4 hanesi ve doğum tarihi ile doğrular. "
                       "Başarılıysa müşterinin adını ve hesap numarasını döner.",
        "properties": {
            "tckn_last4": {"type": "string", "description": "T.C. kimlik numarasının son 4 hanesi, örn. \"8904\"."},
            "birth_date": {"type": "string", "description": "Doğum tarihi, YYYY-MM-DD."},
        },
        "required": ["tckn_last4", "birth_date"],
    },
    "get_account": {
        "description": "Doğrulanmış müşterinin hesabını getirir: ürün, gecikmiş tutar, toplam bakiye, gecikme günü.",
        "properties": {"account_id": {"type": "string", "description": "verify_identity'nin döndüğü hesap numarası."}},
        "required": ["account_id"],
    },
    "log_promise_to_pay": {
        "description": "Müşterinin ödeme sözünü kaydeder. Tek seferlik ödemede installments=1. Taksitte amount_tl ilk "
                       "ödemedir. Banka limitleri dışındaki sözleri reddeder ve sebebini döner.",
        "properties": {
            "account_id": {"type": "string", "description": "Hesap numarası."},
            "amount_tl": {"type": "number", "description": "Ödenecek tutar (taksitte ilk ödeme), TL."},
            "date": {"type": "string", "description": "(İlk) ödeme tarihi, YYYY-MM-DD."},
            "installments": {"type": "integer", "description": "Taksit sayısı; tek seferlik ödeme için 1."},
            "discount_pct": {"type": "number", "description": "Uygulanan indirim yüzdesi; yoksa 0."},
        },
        "required": ["account_id", "amount_tl", "date", "installments"],
    },
    "log_dispute": {
        "description": "Müşterinin borca itirazını kaydeder (borç bana ait değil, ödedim, tutar yanlış vb.).",
        "properties": {
            "account_id": {"type": "string", "description": "Hesap numarası."},
            "reason": {"type": "string", "description": "İtirazın kısa açıklaması."},
        },
        "required": ["account_id", "reason"],
    },
    "schedule_callback": {
        "description": "Geri arama planlar. Doğrulanmamış kişiler için de kullanılabilir; hesap bilgisi gerekmez.",
        "properties": {
            "datetime": {"type": "string", "description": "Geri arama zamanı, YYYY-MM-DD HH:MM."},
            "note": {"type": "string", "description": "Kısa not, örn. \"müşteri müsait değil\"."},
            "account_id": {"type": "string", "description": "Biliniyorsa hesap numarası; yoksa boş."},
        },
        "required": ["datetime", "note"],
    },
    "mark_do_not_call": {
        "description": "Numarayı aranmayacaklar listesine ekler (müşteri aranmak istemiyor veya yanlış numara).",
        "properties": {
            "reason": {"type": "string", "description": "\"customer request\" veya \"wrong number\"."},
            "account_id": {"type": "string", "description": "Biliniyorsa hesap numarası; yoksa boş."},
        },
        "required": ["reason"],
    },
    "transfer_to_human": {
        "description": "Görüşmeyi canlı müşteri temsilcisine aktarır.",
        "properties": {"reason": {"type": "string", "description": "Aktarma sebebi."}},
        "required": ["reason"],
    },
}


def tools_for(policy: Policy) -> list[ToolDef]:
    return [
        ToolDef(name=policy.tool(name), description=spec["description"],
                parameters={"type": "object", "properties": spec["properties"], "required": spec["required"]})
        for name, spec in CANONICAL_TOOL_DEFS.items()
    ]


# Mock customers. Amounts are chosen so the limits bite: a small balance where the minimum installment matters,
# a large one where the first-payment percentage matters.
_PEOPLE = [
    ("Ayşe Yılmaz", "12345678904", "1985-03-14", "05321112233", "kredi kartı", 4250.0, 18500.0, 23),
    ("Mehmet Demir", "23456789018", "1972-11-02", "05334445566", "ihtiyaç kredisi", 12800.0, 64000.0, 41),
    ("Elif Şahin", "34567890126", "1993-07-29", "05367778899", "kredi kartı", 1900.0, 1900.0, 12),
    ("Can Öztürk", "45678901234", "1968-01-09", "05301234567", "taşıt kredisi", 27500.0, 210000.0, 58),
    ("Zeynep Arslan", "56789012342", "2000-12-05", "05449876543", "kredi kartı", 8000.0, 15200.0, 30),
    ("Hasan Koç", "67890123450", "1955-05-17", "05552223344", "ihtiyaç kredisi", 3600.0, 22000.0, 9),
]


def make_accounts(policy: Policy) -> list[dict[str, Any]]:
    prefix = "".join(w[0] for w in policy.brief_id.split("_")).upper()
    accounts = []
    for i, (name, tckn, birth, phone, product, overdue, balance, dpd) in enumerate(_PEOPLE, start=1):
        accounts.append({
            "account_id": f"{prefix}-{100200 + i * 7}",
            "customer_name": name,
            "tckn": tckn,
            "birth_date": birth,
            "phone": phone,
            "product": product,
            "overdue_amount_tl": overdue,
            "total_balance_tl": balance,
            "days_past_due": dpd,
            "status": "overdue",
        })
    return accounts


def load_accounts(brief: str | Path) -> list[dict[str, Any]]:
    import json

    return json.loads((brief_dir(brief) / "accounts.json").read_text())


def customer_variables(policy: Policy, account: dict[str, Any]) -> dict[str, str]:
    """What an outbound campaign row would carry. Debt fields are included so the 'data in prompt vs tool' test
    (T1.6) can use them; whether the agent may say them before verification is the agent's job."""
    return {
        "customer_name": account["customer_name"],
        "customer_phone": account["phone"],
        "account_id": account["account_id"],
        "product": account["product"],
        "overdue_amount_tl": f"{account['overdue_amount_tl']:.2f}",
        "days_past_due": str(account["days_past_due"]),
        "bank_name": policy.bank_name,
        "agent_name": policy.agent_name,
        "today": today().isoformat(),
    }


def _fresh(variables: dict[str, str]) -> dict[str, str]:
    return {**variables, "today": today().isoformat()} if variables else variables


def load_personas(brief: str | Path):
    """personas.json with {{today}} refreshed, so packs prepared yesterday still agree with the mock backend."""
    from agentforge.schemas import Persona
    from agentforge.store import load_models

    return [p.model_copy(update={"variables": _fresh(p.variables)}) for p in load_models(brief_dir(brief) / "personas.json", Persona)]


def load_unit_tests(brief: str | Path):
    from agentforge.schemas import UnitTest
    from agentforge.store import load_models

    return [t.model_copy(update={"customer_variables": _fresh(t.customer_variables)})
            for t in load_models(brief_dir(brief) / "unit_tests.json", UnitTest)]


def collections_tools(brief: str):
    """Tool runner for LocalPlatform: the brief's mock backend, in-process."""
    from agentforge.domain.collections.tools_server import backend

    return backend(brief).run_tool


__all__ = ["collections_tools", "load_personas", "load_unit_tests", "BRIEFS_DIR", "Policy", "brief_dir", "customer_variables", "list_briefs", "load_accounts", "load_policy",
           "make_accounts", "today", "tools_for"]
