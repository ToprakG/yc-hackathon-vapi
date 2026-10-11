"""Feature flags of the compiler fixes. 'all' (default), 'none', 'f1,f3', 'all,-f2'; short ids f1..f10 work."""

from __future__ import annotations

import os

ALL = ["f1_id_complete", "f2_question_not_refusal", "f3_human_first", "f4_discount",
       "f5_vague_date_policy", "f6_counters", "f8_fixed_lines", "f9_number_input", "f10_extract_vote", "f7_router",
       "f11_promise_typed", "f12_slot_summary", "f13_verifier", "f14_rules_ifthen", "f15_hardship_terms", "f16_intents"]
# opt-in: never part of "all"; a flag with no verified policy parameter changes nothing for that brief
OPT_IN = ["f22_forbidden_disclosure"]
_SHORT = {n.split("_", 1)[0]: n for n in ALL + OPT_IN}


def _one(tok: str) -> str:
    tok = tok.strip()
    if tok in ALL or tok in OPT_IN:
        return tok
    if tok in _SHORT:
        return _SHORT[tok]
    raise ValueError(f"unknown feature {tok!r}; known: {', '.join(ALL + OPT_IN)}")


def parse(spec: str | None = None) -> frozenset:
    """None means the env BUILDER_FEATURES, else 'all'."""
    if spec is None:
        spec = os.environ.get("BUILDER_FEATURES") or "all"
    on: set = set()
    for tok in (t for t in spec.replace(";", ",").split(",") if t.strip()):
        tok = tok.strip()
        if tok == "all":
            on = set(ALL)
        elif tok == "none":
            on = set()
        elif tok.startswith("-"):
            on.discard(_one(tok[1:]))
        else:
            on.add(_one(tok))
    return frozenset(on)


def names(features) -> list[str]:
    return sorted(features)
