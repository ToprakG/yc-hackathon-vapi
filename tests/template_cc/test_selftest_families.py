"""The self-test generator puts the failure families proven in real runs first, each only when the policy defines its rule."""
import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))
FX = Path(__file__).parent / "fixtures"


def policy():
    return json.loads((FX / "invented.policy.json").read_text())


def rules(p, cap=None):
    import selftest_cases as S
    sk = S.skeletons(p, S.Ctx(p, 7))
    return [c["rule"] for c in (sk[:cap] if cap else sk)], sk


def full_policy():
    p = policy()
    p.setdefault("ask_limits", {}).update({"id_decline": 1, "vague_date": 1})
    p["vague_date_offer"] = "deadline"
    p.setdefault("sentences", {})["ai"] = "I am an automated assistant."
    p["forbidden_before_verify"] = ["debt"]
    for b in p["bands"]:
        b.setdefault("deadline_business_days", 8)
    return p


def test_the_families_come_first_and_the_total_stays_in_range():
    import selftest_cases as S
    r, sk = rules(full_policy())
    assert r[:5] == S.FAMILY_FIRST
    assert 8 <= len(r[:S.DEFAULT_MAX]) <= 10


def test_each_family_needs_its_policy_field():
    p = full_policy()
    del p["vague_date_offer"]
    assert "vague_deadline" not in rules(p)[0]
    p = full_policy()
    p["ask_limits"].pop("id_decline")
    assert "identity_nonanswer" not in rules(p)[0]
    p = full_policy()
    p["sentences"].pop("ai"); p.get("lines", {}).pop("ai", None)
    assert "robot_identity" not in rules(p)[0]
    p = full_policy()
    p["bands"] = []
    assert not {"deadline_date", "vague_deadline"} & set(rules(p)[0])


def test_the_deadline_scenarios_expect_a_date_inside_the_deadline():
    import datetime as dt
    p = full_policy()
    _, sk = rules(p)
    for c in sk:
        if c["rule"] in ("vague_deadline", "deadline_date"):
            now = dt.date.fromisoformat(c["variables"]["now"][:10])
            d = dt.date.fromisoformat(c["expected"]["promises"][0]["date"])
            assert now < d and d.weekday() < 5 and d.isoformat() not in set(p.get("holidays") or [])
