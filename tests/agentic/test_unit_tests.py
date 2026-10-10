import json
import shutil
from pathlib import Path

import pytest

from builder.agentic.tools import openapi_summary, unit_tests
from tests.agentic.conftest import REPO

FIX = REPO / "tests" / "agentic" / "fixtures"


@pytest.fixture
def demo():
    return json.loads((FIX / "pattern_demo.workflow.json").read_text())


@pytest.fixture
def demo_api():
    return openapi_summary.load(FIX / "pattern_demo.openapi.json")


GOOD = {"name": "refusal goes to the next proposal", "rule": "R31", "start_node": "offer",
        "variables": {"offer_text": "Could you pay 412.50 by Wednesday?", "offer_ref": "r1"},
        "messages": [{"role": "assistant", "text": "Could you pay 412.50 by Wednesday?"}, {"role": "user", "text": "No."}],
        "expect": "The agent does not repeat the proposal.",
        "checks": [{"var": "offer_answer", "equals": "refused"}, {"node": "next_offer"}, {"tool": "create_promise", "absent": True}],
        "mock": {"verify_identity": {"ok": True, "verified": False}}}


def test_validate_accepts_a_good_test_and_names_each_problem(demo, demo_api):
    assert unit_tests.validate([GOOD], demo, demo_api)["errors"] == []
    bad = [dict(GOOD, name="a", start_node="nowhere"),
           dict(GOOD, name="b", messages=[{"role": "user", "text": "hi"}, {"role": "assistant", "text": "x"}]),
           dict(GOOD, name="c", checks=[{"tool": "pay_now"}]),
           dict(GOOD, name="d", checks=[{"tool": "create_promise", "body": {"amount": 1}}]),
           dict(GOOD, name="e", checks=[{"node": "x", "tool": "add_note"}]),
           dict(GOOD, name="f", mock={"bank_magic": {}})]
    msgs = [e["msg"] for e in unit_tests.validate(bad, demo, demo_api)["errors"]]
    for expected in ("start_node 'nowhere'", "the last message must be the customer's", "'pay_now' is not in the tool API",
                     "body fields not in the API: ['amount']", "exactly one of tool / node / var", "mock for 'bank_magic'"):
        assert any(expected in m for m in msgs), (expected, msgs)


def test_to_freya_starts_in_the_named_node_with_the_variables():
    t = unit_tests.to_freya(GOOD, {"title": "Mx"})
    last_assistant = t["messages"][0]
    assert last_assistant["nodeId"] == "offer" and last_assistant["workflowSnapshot"]["currentNode"] == "offer"
    assert last_assistant["workflowSnapshot"]["variableTable"]["offer_ref"]["value"] == "r1"
    assert "nodeId" not in t["messages"][1]
    assert t["assertions"] == [{"type": "extraction", "name": "offer_answer", "match": "equals", "value": "refused"},
                               {"type": "routing", "signal": "node_entered", "target": "next_offer"},
                               {"type": "tool_call", "tool": "create_promise", "negate": True}]
    assert t["mock"]["verify_identity"]["data"] == {"ok": True, "verified": False} and t["tags"][0] == "agentic"


class FakeFreya:
    """The unit-test routes and save_workflow, in memory. `outcomes` decides pass/fail per test name and call."""

    def __init__(self, outcomes):
        self.outcomes, self.tests, self.runs, self.saved, self.n = outcomes, {}, {}, [], 0

    def workspace_id(self):
        return "ws"

    def save_workflow(self, slot, wf, state_file=None):
        self.saved.append((slot, state_file))
        return {"workflow_id": "wf-unit", "agent_id": "ag-unit"}

    def api(self, method, path, body=None, **params):
        if method == "GET" and path == "/api/v2/unit-tests":
            return {"unitTests": list(self.tests.values())}
        if method == "POST" and path == "/api/v2/unit-tests":
            self.n += 1
            tid = f"t{self.n}"
            self.tests[tid] = {"id": tid, "name": body["name"], "tags": body["tags"], "isArchived": False}
            return {"id": tid}
        if method == "PATCH":
            tid = path.rsplit("/", 1)[1]
            self.tests[tid].update({k: v for k, v in body.items() if k in ("isArchived", "name", "tags")})
            return {}
        if path == "/api/v2/unit-tests/run-all":
            enq = []
            for tid in body["unitTestIds"]:
                name = self.tests[tid]["name"]
                outcome = self.outcomes[name].pop(0) if isinstance(self.outcomes[name], list) else self.outcomes[name]
                rid = f"r-{tid}-{len(self.runs)}"
                self.runs[rid] = {"id": rid, "outcome": outcome, "verdictReason": f"{name} {outcome}", "agentResponse": "ok",
                                  "assertionResults": [] if outcome == "pass" else [{"passed": False, "assertion": {"type": "routing"}}]}
                enq.append({"unitTestId": tid, "runIds": [rid]})
            return {"enqueued": enq}
        if path.startswith("/api/v2/unit-tests/runs/"):
            return self.runs[path.rsplit("/", 1)[1]]
        raise AssertionError((method, path))


def test_sync_and_run_creates_runs_and_archives_stale_tests():
    fake = FakeFreya({"refusal goes to the next proposal": "fail", "other": "pass"})
    other = dict(GOOD, name="other", mock=None)
    res = unit_tests.sync_and_run(fake, "wf", [GOOD, other], {})
    assert {r["name"]: r["outcome"] for r in res} == {"refusal goes to the next proposal": "fail", "other": "pass"}
    assert unit_tests.summary(res) == {"passed": 1, "failed": 1, "errors": 0, "total": 2}
    unit_tests.sync(fake, "wf", [unit_tests.to_freya(other, {})])  # GOOD left the suite: archived, not deleted
    assert [t["isArchived"] for t in fake.tests.values()] == [True, False]


def _run_build(tmp_path, outcomes, review_rules=()):
    pytest.importorskip("claude_agent_sdk")
    from claude_agent_sdk import ResultMessage

    from builder.agentic import run as run_mod

    phases = []

    async def query(prompt, options):
        out = Path(options.cwd) / "out"
        if prompt.startswith("Review the phone agent"):
            phases.append("review")
            (out / "review.json").write_text(json.dumps({"rules": list(review_rules)}))
        elif "independent reviewer" in prompt:
            phases.append(("fix", "unit test 'refusal goes to the next proposal'" in prompt))
            wf = json.loads((out / "workflow.json").read_text())
            wf["system_prompt"] += " Fixed."
            (out / "workflow.json").write_text(json.dumps(wf))
        else:
            phases.append("build")
            shutil.copyfile(FIX / "pattern_demo.workflow.json", out / "workflow.json")
            (out / "rules.json").write_text("[]")
            (out / "unit_tests.json").write_text(json.dumps([GOOD]))
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="s1")

    brief = tmp_path / "brief.md"
    brief.write_text("1. Example rule.\n")
    fake = FakeFreya(outcomes)
    o = run_mod.BuildOptions(briefs=[brief], api=FIX / "pattern_demo.openapi.json", slot="agentic-test", out_dir=tmp_path / "out", save="none")
    report = run_mod.run(o, query_fn=query, freya_mod=fake, validate_fn=lambda wf, n: {"skipped": "no key"}, trace_root=tmp_path / "traces")
    return report, phases, fake


def test_unit_failures_reach_the_fix_round_and_a_better_fix_is_kept(tmp_path):
    report, phases, fake = _run_build(tmp_path, {"refusal goes to the next proposal": ["fail", "pass"]})
    assert phases == ["build", "review", ("fix", True)]
    rv = report["review"]
    assert rv["unit_before"]["summary"]["failed"] == 1 and rv["unit_after"]["summary"]["passed"] == 1 and "rolled_back" not in rv
    assert fake.saved[0][0] == "agentic-test-unit" and Path(fake.saved[0][1]).is_absolute()
    assert json.loads((tmp_path / "out" / "workflow.json").read_text())["system_prompt"].endswith("Fixed.")
    assert json.loads((tmp_path / "out" / "findings.json").read_text())[0]["kind"] == "unit_test_failed"


def test_a_fix_that_passes_fewer_unit_tests_is_rolled_back(tmp_path):
    defect = {"id": "V1", "source_quote": "Example rule", "verdict": "wrong", "node_ids": ["offer"], "defect": "d", "fix": "f"}
    report, phases, fake = _run_build(tmp_path, {"refusal goes to the next proposal": ["pass", "fail"]}, [defect])
    assert phases[-1][0] == "fix" and "rolled_back" in report["review"]
    assert not json.loads((tmp_path / "out" / "workflow.json").read_text())["system_prompt"].endswith("Fixed.")


POLICY = {"sentences": {"ai": "Example Bank's automated assistant", "failed_id": "visit a branch"},
          "queue_map": {"human": "desk_x", "restructuring": None, "support": "desk_y"},
          "outcome_map": {"nr_wrong_number": ["outcome_w", "detail_b"], "nr_deceased": None, "np_dispute": ["outcome_u", "detail_h"]},
          "callback": {"start": "09:00", "end": "17:00"}, "holidays": ["2031-03-10"],
          "tools": {"schedule_callback": {"mode": "datetime", "datetime": "slot"}, "transfer_to_agent": {"queue": "desk"}}}


def test_policy_templates_take_every_value_from_the_policy_and_api(demo_api):
    from builder.agentic.tools import policy_suite

    t = {x["template"]: x for x in policy_suite.templates(POLICY, demo_api, "2031-03-07T11:00")}
    assert "deceased" not in t and "restructuring_request" not in t  # the policy has no such route
    cb = t["callback_inside_window"]["checks"][0]
    assert cb == {"tool": "schedule_callback", "body": {"slot": "2031-03-11T10:00"}}  # next business day after a holiday
    assert {"tool": "transfer_to_agent", "body": {"desk": "desk_x"}} in t["human_request_insists"]["checks"]
    assert "Example Bank's automated assistant" in t["robot_question_opening"]["expect"]
    assert t["identity_last_wrong_answer"]["mock"]["verify_identity"]["tries_left"] == 0


def test_required_templates_are_enforced(demo, demo_api):
    from builder.agentic.tools import policy_suite

    required = policy_suite.templates(POLICY, demo_api, "2031-03-07T11:00")
    tests = [dict(GOOD, name="robot", template="robot_question_opening", checks=[])]
    msgs = [e["msg"] for e in unit_tests.validate(tests, demo, demo_api, required)["errors"]]
    assert any("keep the template's checks" in m for m in msgs)  # its get_account-absent check was dropped
    assert any("'callback_inside_window' has no test" in m for m in msgs)


def test_failed_local_cases_become_regression_tests(demo):
    from builder.agentic.localsim.sim import derive_tests

    turns = [{"node": "identity", "vars": {"x": "1"}, "agent": "Your code?", "user": "123"},
             {"node": "offer", "vars": {"offer_text": "Pay 10?"}, "agent": "Pay 10?", "user": "No."},
             {"node": "offer", "vars": {"offer_text": "Pay 10?"}, "agent": "Pay 10?", "user": "I said no."},
             {"node": "facts", "vars": {}, "agent": "x", "user": "y"}]  # not a conversation node: never a start node
    res = [{"id": "T-1", "pass": False, "turns": turns, "failed_checks": ["only one offer"], "ledger_failed": []},
           {"id": "T-2", "pass": True, "turns": turns}]
    tests = derive_tests(res, demo)
    # the last conversation turn is also the loop turn here, so one test; the passing case gives none
    assert [(t["name"], t["start_node"]) for t in tests] == [("sim T-1 turn 3", "offer")]
    assert all("only one offer" in t["expect"] for t in tests) and tests[0]["messages"][-1] == {"role": "user", "text": "I said no."}
    assert unit_tests.validate(tests[:1], demo, openapi_summary.load(FIX / "pattern_demo.openapi.json"))["errors"] == []


def test_local_sim_failures_reach_the_fix_round_and_a_worse_fix_is_rolled_back(tmp_path, monkeypatch):
    from builder.agentic import run as run_mod

    calls = []

    def fake_localsim(ws, opts, trace, workflow_path, label="local sims"):
        calls.append(label)
        before = "before" in label
        res = [{"id": "T-001", "family": "Unclear", "style": "pieces", "pass": not before and False, "nodes": ["opening", "opening"],
                "ledger_failed": [], "failed_checks": ["the agent ends the call after the second unclear answer"],
                "transcript": [("assistant", "Am I speaking with Mx Doe?"), ("user", "What?")]},
               {"id": "T-002", "family": "Happy path", "pass": before, "nodes": [], "transcript": []}]
        passed = sum(r["pass"] for r in res)
        return {"ran": True, "results": res, "summary": {"passed": passed, "total": 2}}

    monkeypatch.setattr(run_mod, "localsim_phase", fake_localsim)
    report, phases, fake = _run_build(tmp_path, {"refusal goes to the next proposal": ["pass", "pass"]})
    assert calls == ["local sims (before fix)", "local sims (after fix)"]
    findings = json.loads((tmp_path / "out" / "findings.json").read_text())
    assert findings[0]["kind"] == "local_sim_failed" and "second unclear answer" in findings[0]["defect"]
    assert phases[-1][0] == "fix" and "local sims 0 vs 1" in report["review"]["rolled_back"]
