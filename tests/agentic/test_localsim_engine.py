"""The local engine on the kit's base-agent.json and on pattern_demo, with a scripted model and an in-memory bank."""

import json

from builder.agentic.localsim.engine import Engine, flatten
from tests.agentic.conftest import REPO

FIX = REPO / "tests" / "agentic" / "fixtures"


class ScriptedModel:
    def __init__(self, chats=(), extractions=(), intents=()):
        self.chats, self.extractions, self.intent_answers = list(chats), list(extractions), list(intents)
        self.seen_tools = []

    def chat(self, system, history, tools):
        self.seen_tools.append(sorted(t["function"]["name"] for t in tools))
        return self.chats.pop(0) if self.chats else {"content": "Okay."}

    def extract(self, recent, schema):
        return self.extractions.pop(0) if self.extractions else {}

    def intents(self, recent, last_user, descriptions):
        return self.intent_answers.pop(0) if self.intent_answers else {d: False for d in descriptions}


def call(name, **args):
    return {"content": None, "tool_calls": [{"id": "c1", "function": {"name": name, "arguments": json.dumps(args)}}]}


class Bank:
    def __init__(self, answers):
        self.answers, self.log = answers, []

    def __call__(self, name, body):
        self.log.append((name, dict(body)))
        a = self.answers.get(name, {"ok": True})
        return a if isinstance(a, tuple) else (200, a)


def test_flatten_writes_booleans_as_lowercase_strings():
    out = {}
    flatten("t_response", {"data": {"ok": True, "items": [{"a": 1}]}}, out)
    assert out == {"t_response.data.ok": "true", "t_response.data.items.0.a": 1}


def test_base_agent_identity_tool_route_and_lifecycle_close(base_agent):
    model = ScriptedModel(chats=[call("verify_identity", field="date_of_birth", answer="1985-03-14"), call("end_call")])
    bank = Bank({"verify_identity": {"ok": True, "verified": True, "all_verified": True}})
    eng = Engine(base_agent, {"customer_id": "c1", "title": "Mr", "last_name": "Reyes", "now": "2026-10-14T11:00"}, bank, model)
    assert eng.start() == "Hello, this is the digital assistant of Freya Bank. Am I speaking with Mr Reyes?"
    said = eng.user_says("Yes, born 14 March 1985.")
    assert bank.log[0] == ("verify_identity", {"field": "date_of_birth", "answer": "1985-03-14", "customer_id": "c1"})
    assert eng.vars["verify_identity_response.data.all_verified"] == "true" and eng.vars["verify_identity_success_count"] == 1
    assert eng.node == "collection" and "I'm calling about your Freya Bank account" in said  # routed on the tool result
    assert model.seen_tools[0] == ["end_call", "verify_identity"]  # model-filled fields only; customer_id is baked
    eng.user_says("Bye.")
    assert eng.ended
    eng.vars.update(outcome="promise", reason="refused")
    eng.finish()  # the end_of_call close_call runs; its pre-hook drops the reason for a promise
    assert bank.log[-1] == ("close_call", {"outcome": "promise", "customer_id": "c1"})


def test_pattern_demo_code_nodes_extraction_and_engine_run_writes():
    wf = json.loads((FIX / "pattern_demo.workflow.json").read_text())
    items = [{"item_ref": "r1", "kind": "kind_a", "ending": "1234", "overdue": 412.5, "days_over": 25, "floor_amount": 80}]
    bank = Bank({"verify_identity": {"ok": True, "verified": True, "all_passed": True}, "get_account": {"ok": True, "items": items}})
    model = ScriptedModel(
        chats=[call("verify_identity", question="member_code", reply="123456"), {"content": "Thanks."},
               {"content": "You have one late item. Can you settle everything now?"}],
        extractions=[{"who": "customer"}, {"first_answer": "not_now", "topic": "none"},
                     {"offer_answer": "agreed"}, {"confirm_answer": "yes"}])
    eng = Engine(wf, {"customer_id": "c9", "title": "Mx", "last_name": "Doe", "now": "2031-03-07T11:00"}, bank, model)
    assert "automated assistant of Example Bank" in eng.start()
    assert eng.vars["calendar_state"] == "ok"  # the setup code node ran
    eng.user_says("Yes, speaking.")
    assert eng.node == "identity"
    eng.user_says("One two three four five six.")
    # identity passed -> load_account (pre_action) -> facts (code) -> negotiate
    assert "items" not in eng.vars  # the platform leaves a mapped list unset ...
    assert eng.vars["load_account_response.data.items.0.item_ref"] == "r1"  # ... the flattened keys hold it
    assert eng.vars["facts_state"] == "ok" and eng.node == "negotiate"
    said = eng.user_says("Not right now.")
    assert eng.node == "offer" and said.startswith("For your item ending 1234, could you pay 412.50")
    said = eng.user_says("Yes, I can do that.")
    assert eng.node == "confirm" and said.startswith("To confirm: for your item ending 1234, 412.50 on")
    eng.user_says("Yes, I confirm.")
    writes = [b for n, b in bank.log if n == "create_promise"]
    assert writes and writes[0]["amount_minor"] == 41250 and writes[0]["item_ref"] == "r1"  # engine-run, baked from code
    assert eng.ended and "letter about each promise" in eng.spoken[-1]
