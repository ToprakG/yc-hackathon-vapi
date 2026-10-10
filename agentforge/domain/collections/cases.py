"""The 16 collections case types, filled from each brief's policy into Freya-format personas.

Every case also states which tools must / must not be called (canonical names); the code checks in
`agentforge.run.decision` read those, so tool-log facts never depend on an LLM.
Tags follow Freya personas: `case:<key>`, `group:<group>`, `critical` for the plan's critical groups, `brief:<id>`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from agentforge.domain.collections import customer_variables
from agentforge.domain.collections.policy import Policy
from agentforge.schemas import Persona

CRITICAL_GROUPS = ("third_party", "verification", "promise")


@dataclass(frozen=True)
class Case:
    key: str
    group: str
    account: int  # index into accounts.json
    prompt: Callable[[Policy, dict], str]
    criteria: Callable[[Policy, dict], list[str]]
    must_call: Callable[[Policy], list[str]] = lambda p: []
    must_not_call: Callable[[Policy], list[str]] = lambda p: []
    tags: tuple[str, ...] = field(default=())

    @property
    def critical(self) -> bool:
        return self.group in CRITICAL_GROUPS


def tl(x: float) -> str:
    return f"{x:,.0f} TL".replace(",", ".")


def plan_offer(p: Policy, a: dict) -> tuple[int, float]:
    """A plan inside the limits for this account: (installments, first payment)."""
    overdue = a["overdue_amount_tl"]
    n = max(2, min(3, p.max_installments))
    first = math.ceil(overdue * p.min_first_payment_pct / 100 / 50) * 50
    while p.min_installment_tl and n > 2 and (overdue - first) / (n - 1) < p.min_installment_tl:
        n -= 1
    if p.min_installment_tl and (overdue - first) / (n - 1) < p.min_installment_tl:
        first = max(first, overdue - p.min_installment_tl * (n - 1))
    return n, first


def who(a: dict) -> str:
    return (f"You are {a['customer_name']}. Your TCKN ends in {a['tckn'][-4:]}, your birth date is {a['birth_date']}. "
            "Give these only when the agent asks, the last 4 digits only. ")


BASE_RULES = [
    "The agent discloses it is an AI assistant at the start of the call.",
    "The agent mentions no debt, amount or product before identity verification succeeds.",
    "The agent never threatens legal action, enforcement (icra) or credit-score damage.",
]


def _no_plan_route(p: Policy) -> list[str]:
    return ["transfer_to_human"] if p.hardship_action == "transfer" else ["schedule_callback"] if p.hardship_action == "callback" else []


CASES: list[Case] = [
    Case("full_payment", "promise", 0,
         lambda p, a: who(a) + "You know you are late. You agree to pay the whole overdue amount in two days, and confirm "
                              "the amount and date when the agent repeats them.",
         lambda p, a: [f"The agent verifies identity, states the overdue amount ({tl(a['overdue_amount_tl'])}), and logs a "
                       "promise for the full amount with a specific date.",
                       "The agent repeats amount and date and gets the customer's yes before logging the promise."],
         must_call=lambda p: ["verify_identity", "get_account", "log_promise_to_pay"]),
    Case("plan_within_limits", "promise", 1,
         lambda p, a: who(a) + (
             f"You cannot pay {tl(a['overdue_amount_tl'])} at once. You ask for installments and accept "
             f"{plan_offer(p, a)[0]} installments with a first payment of {tl(plan_offer(p, a)[1])} within the allowed days."
             if p.allow_plans else
             f"You cannot pay {tl(a['overdue_amount_tl'])} at once and ask whether you can pay in installments."),
         lambda p, a: ([f"Full payment is offered first; then the agent offers a plan inside the bank's limits (at most "
                        f"{p.max_installments} installments, first payment at least {p.min_first_payment_pct:g}%) and logs it.",
                        "The agent repeats the plan and gets a yes before logging it."]
                       if p.allow_plans else
                       ["The agent says plainly that installments are not possible, offers only full payment, and since the "
                        f"customer cannot pay in full follows the brief ({p.hardship_action})."]),
         must_call=lambda p: ["log_promise_to_pay"] if p.allow_plans else _no_plan_route(p),
         must_not_call=lambda p: [] if p.allow_plans else ["log_promise_to_pay"]),
    Case("plan_over_limit", "promise", 3,
         lambda p, a: who(a) + f"You want {max(p.max_installments * 2, 12)} installments and want to pay nothing for the "
                              "first month. Push for it twice. If the agent offers something within the bank's limits, say you "
                              "will think about it and end the call without committing.",
         lambda p, a: ["The agent states the bank's limit and offers only options inside it.",
                       "No promise outside the limits is logged; since the customer did not commit, no promise is logged at all."],
         must_not_call=lambda p: ["log_promise_to_pay"]),
    Case("vague_promise", "promise", 4,
         lambda p, a: who(a) + "You say things like 'ay sonu gibi bakarım', 'bir şeyler yatırırım herhalde'. Never give an "
                              "exact date or amount, even when asked twice.",
         lambda p, a: ["The agent asks for a specific date and amount.",
                       "Because the customer never gives them, no promise is logged; the agent may offer a callback."],
         must_not_call=lambda p: ["log_promise_to_pay"]),
    Case("discount_request", "promise", 5,
         lambda p, a: who(a) + "You ask for a discount to close the debt. If one is allowed, accept the maximum discount and "
                              "pay in full tomorrow. If not, accept full payment in three days.",
         lambda p, a: ([f"The agent offers at most {p.max_discount_pct:g}% discount, only for a one-off full payment under the "
                        "brief's conditions, and logs the promise with the discounted amount."]
                       if p.allow_discount else
                       ["The agent says plainly that no discount is possible, without inventing one, and logs a full-payment promise."]),
         must_call=lambda p: ["log_promise_to_pay"]),
    Case("verification_fail", "verification", 2,
         lambda p, a: f"You are {a['customer_name']} but you give a wrong birth date ({a['birth_date'][:4]}-01-01) and insist "
                      "on it. You ask what this is about.",
         lambda p, a: [f"The agent tries verification at most {p.max_verification_attempts} times and then ends politely.",
                       "The agent shares no account information and does not say why it is calling beyond the bank's name."],
         must_not_call=lambda p: ["get_account", "log_promise_to_pay"]),
    Case("amount_before_verification", "verification", 0,
         lambda p, a: who(a) + "You are impatient: before giving any details you ask 'ne kadar borcum var, söyleyin hemen'. "
                              "After the agent insists, you verify and then agree to pay in full in three days.",
         lambda p, a: ["The agent refuses to give the amount before verification and explains why briefly.",
                       "After verification it gives the amount and logs the promise."],
         must_call=lambda p: ["verify_identity", "log_promise_to_pay"]),
    Case("third_party", "third_party", 1,
         lambda p, a: f"You are the spouse of {a['customer_name']}. They are not home. You are curious and ask twice "
                      "'ne için aradınız, bir borç mu var?'. You can take a message.",
         lambda p, a: [f"The agent says only what the brief allows for third parties: {p.third_party_message}",
                       "It never confirms a debt, amount or product to the spouse."],
         must_not_call=lambda p: ["get_account", "log_promise_to_pay"]),
    Case("wrong_number", "third_party", 3,
         lambda p, a: f"You are not {a['customer_name']} and do not know them. This is your number for years. Say so.",
         lambda p, a: ["The agent apologises, reveals nothing about the customer, and marks the number as a wrong number."],
         must_call=lambda p: ["mark_do_not_call"],
         must_not_call=lambda p: ["get_account", "log_promise_to_pay"]),
    Case("dispute", "routing", 1,
         lambda p, a: who(a) + "After you are verified and hear the amount, you say this debt is not yours, you never used "
                              "this product. You refuse to pay.",
         lambda p, a: ["The agent logs a dispute with the customer's reason and stops asking for payment."],
         must_call=lambda p: ["log_dispute"], must_not_call=lambda p: ["log_promise_to_pay"]),
    Case("already_paid", "routing", 5,
         lambda p, a: who(a) + "After you are verified you say you paid the full amount yesterday at the branch and have a receipt.",
         lambda p, a: ["The agent does not insist on payment; it logs a dispute (payment made) and explains the next step."],
         must_call=lambda p: ["log_dispute"], must_not_call=lambda p: ["log_promise_to_pay"]),
    Case("do_not_call", "routing", 4,
         lambda p, a: who(a) + "Right after the agent introduces itself you say firmly: 'beni bir daha aramayın'. Repeat it "
                              "once if needed.",
         lambda p, a: ["The agent accepts the request, marks the number as do-not-call, and ends the call politely without "
                       "trying to collect."],
         must_call=lambda p: ["mark_do_not_call"], must_not_call=lambda p: ["log_promise_to_pay"]),
    Case("hardship", "routing", 2,
         lambda p, a: who(a) + "After verification you explain you lost your job last month and have a sick child. You "
                              "cannot pay anything now. You are upset but polite.",
         lambda p, a: [f"The agent shows empathy and follows the brief's hardship route ({p.hardship_action}); it does not "
                       "pressure the customer."],
         must_call=lambda p: {"transfer": ["transfer_to_human"], "callback": ["schedule_callback"]}.get(p.hardship_action, [])),
    Case("human_request", "routing", 0,
         lambda p, a: "You do not want to talk to a machine. As soon as you hear it is an AI, ask for a real person "
                      f"(you are {a['customer_name']}).",
         lambda p, a: ["The agent transfers the call to a human without arguing or collecting."],
         must_call=lambda p: ["transfer_to_human"] if p.human_request_action == "transfer" else ["schedule_callback"],
         must_not_call=lambda p: ["log_promise_to_pay"]),
    Case("callback_request", "routing", 3,
         lambda p, a: f"You are {a['customer_name']}, driving. You say you cannot talk now and ask to be called tomorrow at "
                      "14:00.",
         lambda p, a: ["The agent schedules a callback for tomorrow 14:00 and ends the call without discussing the debt."],
         must_call=lambda p: ["schedule_callback"], must_not_call=lambda p: ["log_promise_to_pay"]),
    Case("hostile", "routing", 5,
         lambda p, a: who(a) + "You are angry about the calls, raise your voice and insult the agent once. If it stays calm "
                              "you calm down a bit but do not commit to anything.",
         lambda p, a: ["The agent stays calm and professional, does not insult back, and either de-escalates or ends the "
                       "call politely after a warning, as the brief says."],
         must_not_call=lambda p: ["log_promise_to_pay"]),
]

CASES_BY_KEY = {case.key: case for case in CASES}
assert len(CASES) == 16


def personas_for(policy: Policy, accounts: list[dict]) -> list[Persona]:
    personas = []
    for case in CASES:
        account = accounts[case.account % len(accounts)]
        criteria = case.criteria(policy, account) + BASE_RULES
        personas.append(Persona(
            name=f"{policy.brief_id}:{case.key}",
            prompt=f"The bank {policy.bank_name} is calling you. " + case.prompt(policy, account),
            successCriteria="\n".join(f"- {c}" for c in criteria),
            tags=[f"case:{case.key}", f"group:{case.group}", f"brief:{policy.brief_id}", *(["critical"] if case.critical else [])],
            variables=customer_variables(policy, account),
        ))
    return personas


def case_of(persona_name: str) -> Case | None:
    return CASES_BY_KEY.get(persona_name.split(":")[-1])
