"""Feature flags of the compiler fixes. 'all' (default), 'none', 'f1,f3', 'all,-f2'; short ids f1..f10 work."""

from __future__ import annotations

import os

ALL = ["f1_id_complete", "f2_question_not_refusal", "f3_human_first", "f4_discount", "f5_vague_date_policy",
       "f6_counters", "f8_fixed_lines", "f9_number_input", "f10_extract_vote", "f7_router", "f11_promise_typed",
       "f12_slot_summary", "f13_verifier", "f14_rules_ifthen", "f15_hardship_terms", "f16_intents",
       "f18_side_resume", "f19_refusal_rule", "f20_once_flags", "f21_spoken_answers", "f24_day_once",
       "f25_dispute_wins", "f26_amount_assembly", "f18_opening_fallback"]
# f18_opening_fallback is a sub-switch of f18_side_resume: ON whenever f18 is on (parse() adds it) unless it is named with a minus
# ("...,-f18_opening_fallback"): then an empty who1 after the first reply stays in `opening` as without f18.
# opt-in: never part of "all"; a flag with no verified policy parameter changes nothing for that brief
OPT_IN = ["f22_forbidden_disclosure"]
_SHORT: dict = {}
for _n in ALL + OPT_IN:
    _SHORT.setdefault(_n.split("_", 1)[0], _n)  # a short id names the first flag that has it (f16 = f16_intents)


def _one(tok: str) -> str:
    tok = tok.strip()
    if tok in ALL:
        return tok
    if tok in _SHORT:
        return _SHORT[tok]
    raise ValueError(f"unknown feature {tok!r}; known: {', '.join(ALL)}")


def parse(spec: str | None = None) -> frozenset:
    """None means the env BUILDER_FEATURES, else 'all'."""
    if spec is None:
        spec = os.environ.get("BUILDER_FEATURES") or "all"
    on: set = set()
    off: set = set()
    for tok in (t for t in spec.replace(";", ",").split(",") if t.strip()):
        tok = tok.strip()
        if tok == "all":
            on = set(ALL)
        elif tok == "none":
            on = set()
        elif tok.startswith("-"):
            on.discard(_one(tok[1:]))
            off.add(_one(tok[1:]))
        else:
            on.add(_one(tok))
    if "f18_side_resume" in on and "f18_opening_fallback" not in off:
        on.add("f18_opening_fallback")   # default ON (matches m1)
    return frozenset(on)


def names(features) -> list[str]:
    return sorted(features)
