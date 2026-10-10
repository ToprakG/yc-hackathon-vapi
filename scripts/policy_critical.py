"""Score only the policy fields that change agent behaviour, as MATCH / MISS.

    python3 scripts/policy_critical.py <policy.json> <config.json> [--json]
    python3 scripts/policy_critical.py --diff <policy.json> <policy.json>

Reads the testbed config for scoring only (the builder never does). Key spelling is not a miss: map keys compare after
lowercasing and dropping non-alphanumerics; sets and unordered lists ignore order; numbers compare by value.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from builder.eval.score_policy import _norm  # noqa: E402


def _k(key) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _set(items) -> list:
    return sorted(json.dumps(_norm(x), sort_keys=True) for x in (items or []))


def _keyed(d) -> dict:
    return {_k(k): _norm(v) for k, v in (d or {}).items()}


def _band(b) -> dict:
    b = b or {}
    return {"min": _norm(b.get("min_days")), "max": _norm(b.get("max_days")),
            "deadline": _norm(b.get("deadline_business_days")), "attempts": _norm(b.get("attempts"))}


def _sub(d, *path):
    for p in path:
        d = d.get(p) if isinstance(d, dict) else None
    return d


def fields(p: dict) -> dict:
    """Critical field name -> comparable value."""
    out = {"multi_product": _norm(p.get("multi_product")), "max_products": _norm(p.get("max_products")),
           "identity.questions": _set(_sub(p, "identity", "questions")),
           "identity.max_wrong": _norm(_sub(p, "identity", "max_wrong")),
           "bands.count": len(p.get("bands") or []), "holidays": _set(p.get("holidays")),
           "callback.start": _norm(_sub(p, "callback", "start")), "callback.end": _norm(_sub(p, "callback", "end")),
           "callback.same_day": _norm(_sub(p, "callback", "same_day")),
           "outcome_map": _set(v for v in (p.get("outcome_map") or {}).values() if v),
           "queue_map": _keyed(p.get("queue_map")), "note_map": _keyed(p.get("note_map")),
           "close_rule.kind": _norm(_sub(p, "close_rule", "kind")),
           "close_rule.order": _norm(_sub(p, "close_rule", "order")),
           "tools.create_promise.amount_unit": _norm(_sub(p, "tools", "create_promise", "amount_unit")),
           "tools.schedule_callback.mode": _norm(_sub(p, "tools", "schedule_callback", "mode")),
           "tools.close_call.mode": _norm(_sub(p, "tools", "close_call", "mode"))}
    for i, b in enumerate(p.get("bands") or []):
        out[f"bands.{i}"] = _band(b)
    return out


def compare(policy: dict, config: dict) -> list[dict]:
    got, want = fields(policy), fields(config)
    for name in want:  # a band the policy lacks
        got.setdefault(name, None)
    rows = []
    for name, w in want.items():
        g = got.get(name)
        if name == "outcome_map" and not w:
            continue
        rows.append({"field": name, "status": "MATCH" if g == w else "MISS", "got": g, "want": w})
    for name in got:  # extra bands
        if name not in want:
            rows.append({"field": name, "status": "MISS", "got": got[name], "want": None})
    return rows


def diff(a: dict, b: dict) -> list[str]:
    """Critical fields on which two policies differ (build-to-build variance)."""
    fa, fb = fields(a), fields(b)
    return [k for k in sorted(set(fa) | set(fb)) if fa.get(k) != fb.get(k)]


def main(argv=None) -> int:
    if argv is None and len(sys.argv) > 1 and sys.argv[1] == "--diff":  # policy_critical.py --diff a.json b.json
        a, b = (json.loads(Path(x).read_text()) for x in sys.argv[2:4])
        print(", ".join(diff(a, b)) or "-")
        return 0
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("policy")
    ap.add_argument("config")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rows = compare(json.loads(Path(a.policy).read_text()), json.loads(Path(a.config).read_text()))
    miss = [r for r in rows if r["status"] == "MISS"]
    if a.json:
        print(json.dumps({"misses": len(miss), "total": len(rows), "rows": rows}, ensure_ascii=False))
        return 0
    for r in rows:
        extra = "" if r["status"] == "MATCH" else f"  got={json.dumps(r['got'], ensure_ascii=False)}  want={json.dumps(r['want'], ensure_ascii=False)}"
        print(f"{r['status']:<5} {r['field']}{extra}")
    print(f"\n{len(miss)} critical miss(es) of {len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
