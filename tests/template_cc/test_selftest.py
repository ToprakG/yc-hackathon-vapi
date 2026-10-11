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
