"""T0.3: does the local decision-model judge agree with Freya's verdicts? Picks the plan's branch.

python -m agentforge.experiments.agreement --brief marmara_standard --runs runs/col-v1/marmara_standard_freya.jsonl \\
    [--labels freya_labels.json]

--runs: ScoredRun JSONL from conversations run on Freya (FreyaPlatform keeps Freya's own analysis in
  run.raw["freya_close"]). Our decision judge re-scores the same transcripts, so only the judges differ.
--labels: optional {"<persona name>#<run_idx>": true/false} with Freya verdicts read off the UI, for runs whose
  analysis shape we can't parse. Labels win over parsed values.

Branch (TEST_PLAN section 0): agreement >= 85% overall AND in each critical group -> local inner loop, sections 3-4 on;
>= 90% also allows GEPA-lite; otherwise the fallback branch (Freya verdicts decide, local judge = dev triage only).
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from agentforge.domain.collections import brief_dir, load_personas, load_policy
from agentforge.domain.collections.cases import CRITICAL_GROUPS, case_of
from agentforge.experiments.col_common import dump, results_dir
from agentforge.run.decision import scorer_for
from agentforge.schemas import ScoredRun
from agentforge.store import load_jsonl

LOCAL_THRESHOLD = 0.85
GEPA_THRESHOLD = 0.90


def _passed(value: Any) -> bool | None:
    """Read one Freya result in whichever shape it comes: bool, "pass"/"fail", or a dict with passed/result/outcome."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return {"pass": True, "passed": True, "success": True, "true": True,
                "fail": False, "failed": False, "failure": False, "false": False}.get(value.strip().lower())
    if isinstance(value, dict):
        for key in ("passed", "pass", "success", "result", "outcome", "status", "verdict"):
            if key in value:
                return _passed(value[key])
    return None


def freya_verdict(raw: dict) -> bool | None:
    """successCriteria AND every assertion, from FreyaPlatform's raw["freya_close"].
    TODO(ask-organizers): exact shape of successCriteriaResult / assertionResults."""
    close = raw.get("freya_close") or {}
    success = _passed(close.get("successCriteriaResult"))
    if success is None:
        return None
    results = close.get("assertionResults") or []
    parsed = [_passed(r) for r in results] if isinstance(results, list) else []
    if any(p is None for p in parsed):
        return None
    return success and all(parsed)


def agreement(pairs: list[tuple[str, bool, bool]]) -> dict:
    """pairs: (group, local, freya). Agreement overall, per group, and the confusion counts."""
    by_group: dict[str, list[bool]] = defaultdict(list)
    for group, local, freya in pairs:
        by_group[group].append(local == freya)
    rate = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
    return {
        "n": len(pairs),
        "overall": rate([l == f for _, l, f in pairs]),
        "per_group": {g: {"n": len(v), "agreement": rate(v)} for g, v in sorted(by_group.items())},
        "local_lenient": sum(l and not f for _, l, f in pairs),  # we pass, Freya fails: the dangerous direction
        "local_strict": sum(f and not l for _, l, f in pairs),
    }


def branch(stats: dict) -> str:
    overall = stats["overall"] or 0
    critical = [stats["per_group"].get(g, {}).get("agreement") for g in CRITICAL_GROUPS]
    if any(c is None for c in critical):
        return "undecided: a critical group has no Freya-labelled runs yet"
    if overall >= LOCAL_THRESHOLD and all(c >= LOCAL_THRESHOLD for c in critical):
        return "local+gepa" if overall >= GEPA_THRESHOLD and all(c >= GEPA_THRESHOLD for c in critical) else "local"
    return "fallback"


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brief", required=True)
    parser.add_argument("--runs", nargs="+", required=True)
    parser.add_argument("--labels")
    args = parser.parse_args(argv)

    runs = [s for path in args.runs for s in load_jsonl(Path(path), ScoredRun)]
    labels = json.loads(Path(args.labels).read_text()) if args.labels else {}
    personas = {p.name: p for p in load_personas(args.brief)}
    score = scorer_for(load_policy(brief_dir(args.brief)))

    todo = []
    for s in runs:
        freya = labels.get(f"{s.run.persona_name}#{s.run.run_idx}", freya_verdict(s.run.raw))
        if freya is not None and s.run.persona_name in personas:
            todo.append((s, bool(freya)))
    with ThreadPoolExecutor(max_workers=6) as pool:
        local = list(pool.map(lambda item: score(item[0].run, personas[item[0].run.persona_name]), todo))
    pairs = [((case_of(s.run.persona_name).group if case_of(s.run.persona_name) else "other"), l.passed, f)
             for (s, f), l in zip(todo, local)]
    stats = agreement(pairs)
    stats["unlabelled_runs"] = len(runs) - len(todo)
    stats["branch"] = branch(stats)
    stats["disagreements"] = [{"persona": s.run.persona_name, "run_idx": s.run.run_idx, "local": l.passed, "freya": f,
                               "local_failed": [v.check_name for v in l.verdicts if not v.passed]}
                              for (s, f), l in zip(todo, local) if l.passed != f]
    out = results_dir(args.brief, "judge") / "agreement.json"
    dump(out, stats)
    print(f"agreement {stats['overall'] if stats['overall'] is not None else float('nan'):.0%} on {stats['n']} runs "
          f"({stats['unlabelled_runs']} without a Freya verdict); "
          + ", ".join(f"{g} {v['agreement']:.0%} (n={v['n']})" for g, v in stats["per_group"].items())
          + f"\nbranch: {stats['branch']} -> {out}")
    return stats


if __name__ == "__main__":
    main()
