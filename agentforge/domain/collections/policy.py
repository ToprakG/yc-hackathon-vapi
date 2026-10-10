"""Machine-readable collections policy: the ground truth tests are generated from.

For the practice briefs it is hand-written (`briefs/<id>/policy.json`). For a new brief, `extract_policy` reads it
from the brief text once and caches it. The builder never sees this file; it reads only `sop.md`.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from agentforge import llm
from agentforge.config import settings

# Canonical tool names. A brief may rename them (`Policy.tool_names`); everything else uses these.
CANONICAL_TOOLS = (
    "verify_identity",
    "get_account",
    "log_promise_to_pay",
    "log_dispute",
    "schedule_callback",
    "mark_do_not_call",
    "transfer_to_human",
)


class Policy(BaseModel):
    brief_id: str
    bank_name: str
    agent_name: str = "Asistan"
    language: str = "tr"  # language the agent must speak on the call
    strict: bool = False  # strict briefs demand verbatim scripts and stricter limits

    # Opening and disclosure
    must_disclose_ai: bool = True
    must_disclose_recording: bool = False
    # Phrases the opening must contain in meaning (not necessarily verbatim unless strict).
    required_disclosures: list[str] = Field(default_factory=list)
    # Debt details (amount, that there is a debt) may be mentioned only after verification.
    debt_only_after_verification: bool = True
    # What the agent may say to someone who is not the customer.
    third_party_message: str = "Müşteriye ulaşmak istediğimizi, kendisinin bizi geri araması gerektiğini söyle; borçtan bahsetme."

    # Verification
    verification_fields: list[str] = Field(default_factory=lambda: ["tckn_last4", "birth_date"])
    max_verification_attempts: int = 2

    # Payment options
    allow_full_payment: bool = True
    allow_plans: bool = True
    max_installments: int = 6
    min_first_payment_pct: float = 20.0  # of the overdue amount
    min_installment_tl: float = 0.0
    max_promise_days: int = 7  # first payment date must be within this many days of today
    allow_discount: bool = False
    max_discount_pct: float = 0.0
    discount_max_days: int | None = None  # discount only if the one-off payment is within this many days
    # What the brief says about offering full payment vs a plan first. "unspecified" = the builder decides (T2.2).
    payment_order: str = "unspecified"  # full_first | plan_first | unspecified

    # Routing
    hardship_action: str = "transfer"  # transfer | callback | plan
    dispute_action: str = "log_dispute"  # dispute -> log it and stop collecting
    human_request_action: str = "transfer"
    abusive_action: str = "warn_then_end"

    tool_names: dict[str, str] = Field(default_factory=dict)  # canonical -> name used in this brief
    extra_rules: list[str] = Field(default_factory=list)  # other observable rules, checked by the decision model

    def tool(self, canonical: str) -> str:
        return self.tool_names.get(canonical, canonical)

    def canonical(self, name: str) -> str:
        reverse = {v: k for k, v in self.tool_names.items()}
        return reverse.get(name, name)


def load_policy(brief_dir: str | Path) -> Policy:
    return Policy.model_validate_json((Path(brief_dir) / "policy.json").read_text())


EXTRACT_SYSTEM = """You read a debt-collections call brief from a bank and fill a JSON policy for test generation.
Copy limits exactly as the brief states them. If the brief is silent on a field, keep the default you are given.
If the brief forbids payment plans, set allow_plans=false and max_installments=1. payment_order is "full_first" or
"plan_first" only if the brief says which to offer first, else "unspecified". Put every other observable rule
(something a reviewer could check in a transcript or tool log) into extra_rules, one short sentence each.
tool_names maps each canonical tool to the name the brief uses, only when it differs."""


def extract_policy(brief_md: str, brief_id: str, tool_names: list[str] | None = None) -> Policy:
    defaults = Policy(brief_id=brief_id, bank_name="?").model_dump()
    user = (
        f"CANONICAL TOOLS: {', '.join(CANONICAL_TOOLS)}\n"
        f"TOOLS IN THIS BRIEF: {', '.join(tool_names or [])}\n\n"
        f"DEFAULTS:\n{Policy.model_validate(defaults).model_dump_json(indent=1)}\n\nBRIEF:\n{brief_md}"
    )
    raw = llm.call_llm(EXTRACT_SYSTEM, user, model=settings().builder_model, json_schema=Policy.model_json_schema(), temperature=0)
    return Policy.model_validate({**defaults, **raw, "brief_id": brief_id})
