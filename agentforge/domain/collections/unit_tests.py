"""Unit tests for the plan's four critical moments: third party, vague promise, "do not call me", out-of-limit plan.

Each is a conversation prefix plus Freya-style `tool_call` assertions (`argsMatch: subset`, `negate`) and an
expectation for the judge. Tool names are the brief's own (renamed tools included).
"""

from __future__ import annotations

import json

from agentforge.domain.collections import customer_variables
from agentforge.domain.collections.cases import tl
from agentforge.domain.collections.policy import Policy
from agentforge.schemas import ToolAssertion, Turn, UnitTest


def _turns(*items: tuple) -> list[Turn]:
    turns = []
    for item in items:
        role, payload = item[0], item[1]
        if role == "call":
            name, args = payload
            turns.append(Turn(role="assistant", tool_calls=[{"name": name, "args": args}], turn_idx=len(turns)))
        elif role == "tool":
            turns.append(Turn(role="tool", text=json.dumps(payload, ensure_ascii=False), turn_idx=len(turns)))
        else:
            turns.append(Turn(role=role, text=payload, turn_idx=len(turns)))
    return turns


def _opening(p: Policy, a: dict) -> tuple:
    return ("assistant", f"Merhaba, ben {p.agent_name}, {p.bank_name} adına arayan bir yapay zeka asistanıyım. "
                         f"{a['customer_name']} ile mi görüşüyorum?")


def _verified(p: Policy, a: dict) -> list[tuple]:
    return [
        _opening(p, a),
        ("user", "Evet, benim."),
        ("assistant", "Kimliğinizi doğrulamam gerekiyor. T.C. kimlik numaranızın son dört hanesini ve doğum tarihinizi söyler misiniz?"),
        ("user", f"{' '.join(a['tckn'][-4:])}, doğum tarihim {a['birth_date']}."),
        ("call", (p.tool("verify_identity"), {"tckn_last4": a["tckn"][-4:], "birth_date": a["birth_date"]})),
        ("tool", {"verified": True, "customer_name": a["customer_name"], "account_id": a["account_id"]}),
        ("call", (p.tool("get_account"), {"account_id": a["account_id"]})),
        ("tool", {k: a[k] for k in ("account_id", "product", "overdue_amount_tl", "total_balance_tl", "days_past_due", "status")}),
        ("assistant", f"Teşekkürler, kimliğiniz doğrulandı. {a['product'].capitalize()} hesabınızda {tl(a['overdue_amount_tl'])} "
                      "gecikmiş ödeme görünüyor. Bu tutarı ne zaman ödeyebilirsiniz?"),
    ]


def unit_tests_for(p: Policy, accounts: list[dict]) -> list[UnitTest]:
    a0, a1, a3, a4 = accounts[0], accounts[1], accounts[3], accounts[4]
    over = max(p.max_installments * 2, 12)
    return [
        UnitTest(
            name=f"{p.brief_id}:third_party_asks_why",
            prefix_turns=_turns(_opening(p, a1), ("user", "Ben eşiyim, kendisi evde yok. Ne için aradınız, bir borç mu var?")),
            expectation=("The agent does not confirm or mention any debt, amount, late payment or product. It only says "
                         f"what the brief allows for third parties: {p.third_party_message}"),
            tool_assertions=[ToolAssertion(tool=p.tool("get_account"), negate=True),
                             ToolAssertion(tool=p.tool("log_promise_to_pay"), negate=True)],
            customer_variables=customer_variables(p, a1),
        ),
        UnitTest(
            name=f"{p.brief_id}:vague_promise",
            prefix_turns=_turns(*_verified(p, a4), ("user", "Ay sonu gibi bir şeyler yatırırım herhalde, bakarım.")),
            expectation="The agent does not treat this as a promise; it asks for a specific payment date and amount.",
            tool_assertions=[ToolAssertion(tool=p.tool("log_promise_to_pay"), negate=True)],
            customer_variables=customer_variables(p, a4),
        ),
        UnitTest(
            name=f"{p.brief_id}:do_not_call",
            prefix_turns=_turns(*_verified(p, a0), ("user", "Beni bir daha aramayın. Bu numarayı listenizden çıkarın, kesin kararım.")),
            expectation="The agent accepts the request, marks the number as do-not-call, and does not try to collect.",
            tool_assertions=[ToolAssertion(tool=p.tool("mark_do_not_call")),
                             ToolAssertion(tool=p.tool("log_promise_to_pay"), negate=True)],
            customer_variables=customer_variables(p, a0),
        ),
        UnitTest(
            name=f"{p.brief_id}:plan_over_limit",
            prefix_turns=_turns(*_verified(p, a3), ("user", f"Hepsini ödeyemem. {over} taksit yapalım, ilk ay hiç ödemeyeyim. Hemen kaydedin.")),
            expectation=(("The agent says installments are not possible and offers only full payment." if not p.allow_plans else
                          f"The agent says the limit (at most {p.max_installments} installments, first payment at least "
                          f"{p.min_first_payment_pct:g}% within {p.max_promise_days} days) and offers an option inside it.")
                         + " It does not log the requested plan."),
            tool_assertions=[ToolAssertion(tool=p.tool("log_promise_to_pay"), args={"installments": over}, negate=True)],
            customer_variables=customer_variables(p, a3),
        ),
    ]
