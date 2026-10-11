"""Offline tests of the self-test tooling (no Freya, no model): scenario skeletons, scoring modes, the R2 allow-list, the R4 guard."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))
FX = Path(__file__).parent / "fixtures"


def policy():
    return json.loads((FX / "invented.policy.json").read_text())


def test_skeletons_are_policy_driven_and_valid():
    import selftest_cases as S
    p = policy()
    sk = S.skeletons(p, S.Ctx(p, 7))
    assert sk, "at least one scenario"
    om = p["outcome_map"]
    for c in sk:
        assert c["expected"]["outcome"] is not None
        assert c["products"] and set(c["identity"]) == set(p["identity"]["questions"])
        if c["rule"] == "dispute":
            assert [c["expected"]["outcome"], c["expected"]["reason"]] == om["np_dispute"]
    assert [c["rule"] for c in sk] == sorted([c["rule"] for c in sk], key=lambda r: S.PRIORITY.index(r))


def test_r2_allow_list_is_parametric_only():
    import selftest_repair as R
    for ok in ("f17_anything", "f19_refusal_rule", "f22_forbidden_disclosure", "f24_day_once", "f25_dispute_wins"):
        assert R.r2_ok(ok)
    for core in ("f1_id_complete", "f7_router", "f15_hardship_terms", "f18_side_resume", "f20_once_flags", "f21_spoken_answers", "f13_verifier"):
        assert not R.r2_ok(core)


def test_r4_only_for_marked_unknown_rules():
    import selftest_repair as R
    assert not R.is_unknown({"rule": "dispute"})
    assert not R.is_unknown({"rule": "unknown_rule", "unknown": True})  # no brief quote
    assert R.is_unknown({"rule": "unknown_rule", "unknown": True, "quotes": ["x"]})


def test_check_patch_needs_the_brief_sentence_verbatim():
    import selftest_repair as R
    brief = "Always say the branch code. Never promise a waiver."
    ok = {"zone": "node:x/rules", "op": "append", "before": "", "after": "Never promise a waiver. IF asked for a waiver THEN decline.",
          "brief_quote": "Never promise a waiver."}
    assert isinstance(R.check_patch(ok, brief, [{"id": "c", "variables": {}, "identity": {}, "products": []}]), dict)
    assert isinstance(R.check_patch({**ok, "after": "Decline waivers."}, brief, []), str)
    assert isinstance(R.check_patch({**ok, "brief_quote": "Not in the brief."}, brief, []), str)


def test_judge_ledger_mode_keeps_only_structural_checks():
    import types
    sys.modules.setdefault("freya", types.ModuleType("freya"))
    try:
        import selftest_run as SR
    except Exception:  # vendor tester not importable here
        import pytest
        pytest.skip("vendor tester not available")
    case = {"ledger": "judge", "expected": {}}
    led = {"outcome": "x", "reason": None, "promises": [], "notes": [], "callbacks": [], "transfers": [],
           "calls": [{"tool": "close_call", "result": {}}]}
    assert SR.score_case(case, led)["pass"]


# --- LLM calls go through llm.py: TCC_LLM_PROVIDER=anthropic needs no Claude Code login -------------------------------------------------
def _mock_anthropic(monkeypatch, replies):
    import subprocess
    from builder.template_cc import llm
    calls = []

    def fake(url, headers, payload, timeout):
        calls.append((url, payload))
        return {"content": [{"type": "text", "text": json.dumps(replies.pop(0))}], "usage": {"input_tokens": 1, "output_tokens": 1}}

    def no_cli(*a, **k):
        raise AssertionError("the claude CLI / a subprocess must not be used with TCC_LLM_PROVIDER=anthropic")
    monkeypatch.setattr(llm, "TRANSPORT", fake)
    monkeypatch.setattr(llm, "load_env", lambda *a, **k: None)
    monkeypatch.setattr(subprocess, "run", no_cli)
    monkeypatch.setattr(subprocess, "Popen", no_cli)
    monkeypatch.setenv("TCC_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    return calls


def test_patcher_diagnosis_uses_llm_py_only(monkeypatch):
    import selftest_repair as R
    calls = _mock_anthropic(monkeypatch, [{"diagnosis": "the agent skipped a rule the brief states", "action": "none"}])
    row = {"case": "ST-01", "failed": ["conversation (Freya judge): x"], "ledger": {}, "tools": []}
    case = {"rule": "dispute", "script": "s", "expected": {}, "criteria": []}
    act = R.diagnose(row, case, policy(), "brief text", ["f7_router"], "/nonexistent", set())
    assert act["action"] == "none" and len(calls) == 1
    assert calls[0][0].startswith("https://api.anthropic.com") and calls[0][1]["model"] == "claude-sonnet-5-5"


def test_scenario_writer_uses_llm_py_only(monkeypatch):
    import selftest_cases as S
    calls = _mock_anthropic(monkeypatch, [{"scenarios": [{"id": "ST-01", "script": "x", "criteria": []}]}])
    out = S.write_personas("brief", [{"id": "ST-01", "rule": "dispute", "facts": "f", "expected": {"outcome": "o", "reason": None}}], None)
    assert out["scenarios"][0]["id"] == "ST-01" and calls[0][0].startswith("https://api.anthropic.com")


def test_final_trace_appends_scenarios_and_actions(tmp_path):
    import subprocess
    out, base = tmp_path / "out", tmp_path / "out" / "r0"
    (base / "selftest").mkdir(parents=True)
    tdir = tmp_path / "trace"
    tdir.mkdir()
    (tdir / "trace.txt").write_text("start\n")
    (tdir / "events.jsonl").write_text("")
    (base / "build_report.json").write_text(json.dumps({"slot": "final-x", "trace": str(tdir), "saved": {"workflow_id": "w1", "agent_id": "a1"}}))
    (base / "workflow.json").write_text("{}")
    (out / "selftest").mkdir()
    (out / "selftest" / "cases.json").write_text(json.dumps([{"id": "ST-01", "title": "t", "rule": "dispute"}]))
    (base / "selftest" / "results.json").write_text(json.dumps({"passed": 0, "cases": 1, "seconds": {}, "rows": [
        {"case": "ST-01", "rule": "dispute", "pass": False, "freya_judge": False, "failed": ["outcome (a, b), expected (c, d)", "conversation (Freya judge): bad"]}]}))
    (out / "patch_report.json").write_text(json.dumps({"start": str(base), "rounds": [{"round": 1, "actions": [
        {"case": "ST-01", "action": "policy_field", "pointer": "/x", "how": "ledger diff -> R1"}], "used": ["ST-01"], "kept": False, "result": "reverted", "fixed": [], "broken": ["ST-02"]}]}))
    env = {**__import__("os").environ, "FINAL_SAVE": "none"}
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "final_trace.py"), "--out", str(out), "--base", str(base), "--green", str(base)], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    ev = [json.loads(x) for x in (tdir / "events.jsonl").read_text().splitlines()]
    assert [e["type"] for e in ev if e["type"] in ("selftest_scenario", "patcher_action")] == ["selftest_scenario", "patcher_action"]
    sc = next(e for e in ev if e["type"] == "selftest_scenario")
    assert sc["passed"] is False and "bad" in sc["judge_verdict"] and sc["ledger_diff"].startswith("outcome")
    pa = next(e for e in ev if e["type"] == "patcher_action")
    assert pa["reverted"] is True and pa["field"] == "/x"
    assert "REVERTED" in (tdir / "trace.txt").read_text()
    assert json.loads((out / "build_report.json").read_text())["saved"]["workflow_id"] == "w1"
