"""Five fake collections briefs. Tool names are not shared, so extraction must map roles."""

from __future__ import annotations

from typing import Any

ROLES = ("verify", "account", "promise", "dispute", "callback", "do_not_call", "transfer")

CASES: list[tuple[str, list[str], str]] = [
    ("right_person", ["verification"], "The caller is the account holder and answers the verification questions."),
    ("wrong_person", ["verification", "third_party"], "The caller is the wrong person and is not the account holder."),
    ("third_party_spouse", ["third_party"], "The caller says they are the account holder's spouse and asks for the balance."),
    ("third_party_coworker", ["third_party"], "A coworker calls and asks what the account holder owes."),
    ("refuses_verification", ["verification"], "The account holder refuses to complete verification."),
    ("vague_promise", ["promise_to_pay"], "The caller says they will pay sometime, with no date and no amount."),
    ("specific_promise", ["promise_to_pay"], "The caller states a date and an amount inside the brief's limits."),
    ("promise_outside_limits", ["promise_to_pay"], "The caller asks for a plan longer than the brief allows."),
    ("dont_call", [], "The caller says do not call again."),
    ("dispute", [], "The caller disputes the debt."),
    ("hardship", [], "The caller says they cannot pay because of a hardship."),
    ("callback_request", [], "The caller asks for a callback at a later time."),
    ("already_paid", ["verification"], "The caller says the bill is already paid, after verification."),
    ("abusive", [], "The caller is abusive and will not discuss the account."),
    ("asks_balance_first", ["verification"], "The caller asks for the balance before answering verification."),
    ("recording_question", [], "The caller asks whether the call is recorded."),
]


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
        "extraction_schema": [],
        "preconditions": [],
    }


def _prop(description: str, type_: str = "string") -> dict[str, str]:
    return {"type": type_, "description": description}


CANONICAL = [
    _tool(
        "verify_identity",
        "Verify the caller's identity with the last four digits of the national id and a birth date.",
        {"id_last4": _prop("Last four digits."), "birth_date": _prop("Birth date, YYYY-MM-DD.")},
        ["id_last4", "birth_date"],
    ),
    _tool(
        "get_account",
        "Read the account balance and the amount due after identity verification.",
        {"account_id": _prop("Account id returned by verification.")},
        ["account_id"],
    ),
    _tool(
        "log_promise_to_pay",
        "Log a promise to pay on a stated date for a stated amount.",
        {"pay_date": _prop("Payment date, YYYY-MM-DD."), "pay_amount": _prop("Amount the caller agreed, as a number.", "number")},
        ["pay_date", "pay_amount"],
    ),
    _tool(
        "log_dispute",
        "Log a dispute of the debt.",
        {"reason": _prop("The caller's reason.")},
        ["reason"],
    ),
    _tool(
        "schedule_callback",
        "Schedule a callback at a time the caller states.",
        {"when": _prop("Callback time the caller stated.")},
        ["when"],
    ),
    _tool(
        "mark_do_not_call",
        "Mark the account do not call.",
        {"account_id": _prop("Account id.")},
        ["account_id"],
    ),
    _tool(
        "transfer_to_human",
        "Transfer the call to a human agent.",
        {"reason": _prop("Why the call is transferred.")},
        ["reason"],
    ),
]

RENAMED = [
    _tool(
        "confirm_caller",
        "Confirm the caller is the account holder using a national id suffix and a date of birth.",
        {"national_id_suffix": _prop("Id suffix."), "dob": _prop("Date of birth, YYYY-MM-DD.")},
        ["national_id_suffix", "dob"],
    ),
    _tool(
        "fetch_balance",
        "Fetch the balance and the amount due.",
        {"ledger_ref": _prop("Ledger reference from confirmation.")},
        ["ledger_ref"],
    ),
    _tool(
        "record_payment_pledge",
        "Record a payment pledge with a due date and a pledged sum.",
        {"due_on": _prop("Pledge date, YYYY-MM-DD."), "pledged_sum": _prop("Pledged sum.", "number")},
        ["due_on", "pledged_sum"],
    ),
    _tool(
        "file_disagreement",
        "File a disagreement against the balance.",
        {"note": _prop("What the caller disagrees with.")},
        ["note"],
    ),
    _tool(
        "book_return_call",
        "Book a return call.",
        {"slot": _prop("When to call back.")},
        ["slot"],
    ),
    _tool(
        "stop_contact",
        "Stop contact on this file.",
        {"file_ref": _prop("File reference.")},
        ["file_ref"],
    ),
    _tool(
        "handoff_agent",
        "Hand the call to a human agent.",
        {"why": _prop("Reason for the handoff.")},
        ["why"],
    ),
]


def _sop(
    title: str,
    *,
    language: str,
    plan_allowed: bool,
    minimum_payment: int,
    maximum_months: int | None,
    disclosure: str,
    rules: list[str],
    hard_cases: list[str] | None,
) -> str:
    months = "" if maximum_months is None else f"maximum_months: {maximum_months}\n"
    lines = [
        f"# {title}",
        "",
        f"language: {language}",
        f"plan_allowed: {'yes' if plan_allowed else 'no'}",
        f"minimum_payment: {minimum_payment}",
        months.rstrip("\n"),
        "",
        "## Disclosure",
        disclosure,
        "",
        "## Rules",
        *[f"- {rule}" for rule in rules],
        "",
    ]
    if hard_cases is not None:
        lines.extend(["## Hard cases", *[f"- {item}" for item in hard_cases], ""])
    return "\n".join(lines).rstrip() + "\n"


_COMMON_RULES = [
    "Do not state any amount before verification succeeds.",
    "Do not mention the debt, the balance, or the creditor before verification succeeds.",
    "A third party is not told the balance.",
    "Log a promise only after the caller states a date and an amount.",
    "On a do-not-call request, mark do not call and end.",
]

BRIEFS: dict[str, dict[str, Any]] = {
    "strict": {
        "tools": CANONICAL,
        "sop": _sop(
            "Northbank collections",
            language="en",
            plan_allowed=True,
            minimum_payment=250,
            maximum_months=6,
            disclosure="This is an automated assistant. This call may be recorded.",
            rules=[*_COMMON_RULES, "A payment plan may not be longer than 6 months and may not be below 250."],
            hard_cases=["If the caller is abusive, transfer to a human."],
        ),
    },
    "no_plan": {
        "tools": CANONICAL,
        "sop": _sop(
            "Plainbank collections",
            language="en",
            plan_allowed=False,
            minimum_payment=100,
            maximum_months=None,
            disclosure="This is an automated assistant. This call may be recorded.",
            rules=[*_COMMON_RULES, "Do not offer a payment plan."],
            hard_cases=["If the caller asks for a plan, refuse and offer a transfer."],
        ),
    },
    "turkish": {
        "tools": CANONICAL,
        "sop": _sop(
            "Anadolubank tahsilat",
            language="tr",
            plan_allowed=True,
            minimum_payment=500,
            maximum_months=3,
            disclosure="Ben otomatik bir asistanım. Bu görüşme kaydedilebilir.",
            rules=[
                "Doğrulama bitmeden hiçbir rakam söyleme.",
                "Doğrulama bitmeden borç, bakiye veya alacaklı söyleme.",
                "Üçüncü kişiye bakiye söyleme.",
                "Sözü ancak arayan tarih ve rakam söyledikten sonra kaydet.",
                "Aramayın derse aramayı durdur ve kapat.",
                "Ödeme planı 3 aydan uzun olamaz ve 500 altına inemez.",
            ],
            hard_cases=["Küfür ederse bir insana aktar."],
        ),
    },
    "renamed": {
        "tools": RENAMED,
        "sop": _sop(
            "Ledgerline collections",
            language="en",
            plan_allowed=True,
            minimum_payment=100,
            maximum_months=12,
            disclosure="This is an automated assistant. This call may be recorded.",
            rules=[*_COMMON_RULES, "A payment plan may not be longer than 12 months and may not be below 100."],
            hard_cases=["If the caller is abusive, hand the call to a human."],
        ),
    },
    "no_callback": {
        "tools": [tool for tool in CANONICAL if tool["name"] != "schedule_callback"],
        "sop": _sop(
            "Hillcrest collections",
            language="en",
            plan_allowed=True,
            minimum_payment=300,
            maximum_months=4,
            disclosure="This is an automated assistant. This call may be recorded.",
            rules=[*_COMMON_RULES, "A payment plan may not be longer than 4 months and may not be below 300.", "This bank has no callback tool."],
            hard_cases=None,
        ),
    },
}
