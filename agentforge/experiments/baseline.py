"""T0.1 Baseline x 3: per-case run-to-run variance, and the case sets every later comparison uses.

python -m agentforge.experiments.baseline --brief marmara_standard --agent runs/col-v1/agent.json [--platform local]
    [--repeats 3] [--runs 3] [--force]

Writes results/collections/<brief>/<agent label>/baseline.json. Cached: re-running with the same agent, cases, checks,
models and platform prints the stored result instead of spending runs (--force to redo).

Case sets are fixed here, from the baseline only, never from a candidate's results:
- regression: passed every baseline run -> skipped in A/B comparisons, re-run as a regression check on claimed wins.
- dev: everything else, including cases that always failed (that is where fixes show up; in the paired tests
  cases where both configs tie drop out anyway, so keeping them costs runs, not accuracy).
"""

from __future__ import annotations

import argparse
import statistics

from agentforge.experiments.col_common import cache_key, dump, groups, load_agent, results_dir, run_cases
from agentforge.domain.collections.cases import CRITICAL_GROUPS
from agentforge.stats import merge


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brief", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--platform", default="local")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    cfg = load_agent(args.agent)
    out = results_dir(args.brief, cfg.version_label) / "baseline.json"
    key = cache_key(cfg, args.brief, args.platform, args.runs)
    if out.exists() and not args.force:
        import json

        cached = json.loads(out.read_text())
        if cached.get("cache_key") == key and cached.get("repeats") == args.repeats:
            print(f"cached baseline ({out}): pass rate {cached['pass_rate_mean']:.2f} ± {cached['pass_rate_sd']:.2f}")
            return cached

    repeats = []
    for i in range(args.repeats):
        _, counts = run_cases(cfg, args.brief, args.platform, args.runs, f"baseline_{i}")
        repeats.append(counts)
    total = merge(*repeats)
    rates = [sum(p for p, _ in c.values()) / max(1, sum(n for _, n in c.values())) for c in repeats]
    group_of = groups(args.brief)
    per_case = {
        case: {"group": group_of.get(case), "passed": p, "runs": n,
               "per_repeat": [r.get(case, (0, 0))[0] for r in repeats],
               "rate_sd": statistics.pstdev([r[case][0] / r[case][1] for r in repeats if case in r]) if len(repeats) > 1 else 0.0}
        for case, (p, n) in sorted(total.items())
    }
    regression = [c for c, (p, n) in total.items() if p == n]
    result = {
        "brief": args.brief, "agent": cfg.version_label, "platform": args.platform, "cache_key": key,
        "repeats": args.repeats, "runs_per_case": args.runs,
        "pass_rate_mean": statistics.mean(rates), "pass_rate_sd": statistics.stdev(rates) if len(rates) > 1 else 0.0,
        "pass_rates": rates,
        "cases_with_any_variance": sum(1 for v in per_case.values() if 0 < v["passed"] < v["runs"]),
        "per_case": per_case,
        "regression_set": sorted(regression),
        "critical_regression_set": sorted(c for c in regression if group_of.get(c) in CRITICAL_GROUPS),
        "always_fail": sorted(c for c, (p, _) in total.items() if p == 0),
        "dev_set": sorted(c for c in total if c not in regression),
        "counts": {c: list(v) for c, v in total.items()},
    }
    dump(out, result)
    print(f"{args.brief} {cfg.version_label}: pass rate {result['pass_rate_mean']:.2f} ± {result['pass_rate_sd']:.2f} "
          f"over {args.repeats} repeats; dev set {len(result['dev_set'])} cases, regression set {len(regression)} -> {out}")
    return result


if __name__ == "__main__":
    main()
