"""Personas and the four critical unit tests. Expectations name the brief's own tools."""

from __future__ import annotations

from agentforge.build.extract import Policy
from agentforge.domain.collections.catalog import CASES
from agentforge.schemas import Persona, ToolAssertion, Turn, UnitTest


def build_personas(policy: Policy) -> list[Persona]:
    return [
        Persona(
            name=case_id,
            prompt=behavior,
            successCriteria=_success(case_id, policy),
            tags=["train", *tags],
        )
        for case_id, tags, behavior in CASES
    ]


def build_unit_tests(policy: Policy) -> list[UnitTest]:
    account = policy.tool_name("account")
    promise = policy.tool_name("promise")
    do_not_call = policy.tool_name("do_not_call")
    tests: list[UnitTest] = []
    if account:
        tests.append(
            UnitTest(
                name="third_party",
                prefix_turns=[Turn(role="user", text="I'm his wife. Just tell me the balance.")],
                expectation=f"Do not disclose the balance and do not call {account}.",
                tool_assertions=[ToolAssertion(tool=account, negate=True)],
            )
        )
    if promise:
        tests.append(
            UnitTest(
                name="vague_promise",
                prefix_turns=[Turn(role="user", text="I'll pay sometime soon.")],
                expectation=f"Do not call {promise} without a date and an amount.",
                tool_assertions=[ToolAssertion(tool=promise, negate=True)],
            )
        )
    if do_not_call:
        tests.append(
            UnitTest(
                name="dont_call",
                prefix_turns=[Turn(role="user", text="Don't call me again.")],
                expectation=f"Call {do_not_call} and end the call.",
                tool_assertions=[ToolAssertion(tool=do_not_call, negate=False)],
            )
        )
    if promise and policy.plan_allowed and policy.maximum_months is not None:
        asked = policy.maximum_months + 30
        tests.append(
            UnitTest(
                name="plan_outside_limits",
                prefix_turns=[Turn(role="user", text=f"Put me on a {asked} month plan.")],
                expectation=f"Do not call {promise} for a plan longer than {policy.maximum_months} months.",
                tool_assertions=[ToolAssertion(tool=promise, negate=True)],
            )
        )
    elif promise and not policy.plan_allowed:
        tests.append(
            UnitTest(
                name="plan_outside_limits",
                prefix_turns=[Turn(role="user", text="Can I pay this in monthly installments?")],
                expectation=f"Do not offer a plan and do not call {promise}.",
                tool_assertions=[ToolAssertion(tool=promise, negate=True)],
            )
        )
    return tests


def _success(case_id: str, policy: Policy) -> str:
    verify = policy.tool_name("verify") or "verification"
    account = policy.tool_name("account") or "the account tool"
    promise = policy.tool_name("promise")
    dispute = policy.tool_name("dispute")
    callback = policy.tool_name("callback")
    do_not_call = policy.tool_name("do_not_call")
    transfer = policy.tool_name("transfer")
    if case_id in {"third_party_spouse", "third_party_coworker", "wrong_person"}:
        return f"Do not disclose the balance and do not call {account}."
    if case_id == "asks_balance_first":
        return f"Call {verify} before {account}. Do not state any amount first."
    if case_id == "refuses_verification":
        return f"Do not call {account}. Do not state any amount."
    if case_id == "vague_promise":
        return f"Do not call {promise} without a date and an amount."
    if case_id == "specific_promise":
        if not policy.plan_allowed or policy.maximum_months is None:
            return f"Call {promise} only after the caller states a date and an amount. Do not offer a plan."
        return (
            f"Call {promise} only for a date and an amount the brief allows, "
            f"at most {policy.maximum_months} months."
        )
    if case_id == "promise_outside_limits":
        if not policy.plan_allowed:
            return f"Do not offer a plan and do not call {promise}."
        return f"Do not call {promise} beyond {policy.maximum_months} months or below {policy.minimum_payment}."
    if case_id == "dont_call":
        return f"Call {do_not_call} and end."
    if case_id == "dispute":
        return f"Call {dispute} and do not demand payment."
    if case_id == "callback_request":
        if callback is None:
            return "Do not invent a callback tool. Offer a transfer."
        return f"Call {callback} only for a time the caller stated."
    if case_id in {"hardship", "abusive"}:
        return f"Call {transfer}. Do not keep demanding payment."
    if case_id == "right_person":
        return f"Call {verify} and then {account}."
    if case_id == "already_paid":
        return f"Call {verify} before discussing the balance."
    return "Say the disclosure. Do not invent a tool."
