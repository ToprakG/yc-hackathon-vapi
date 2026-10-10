"""Paired A/B against the current best, with the plan's re-run and regression rules (TEST_PLAN "Tanımlar" + section 5).

python -m agentforge.experiments.paired --best 'runs/col-{brief}-v1/agent.json' \\
    --candidate 'runs/col-{brief}-v1+p1/agent.json' --practice practice [--fake a,b,c] [--platform local] [--runs 3]

A change is a builder change, so every brief gets its own agent: `{brief}` in the paths is replaced per brief. Fake
briefs whose agent files are missing are skipped (and acceptance then fails if fewer than 3 were tested).

Per brief: A and B run fresh on the same dev-set cases (from A's baseline if one exists, else every case).
- verdict: Wilcoxon on per-case pass rates, p < 0.1 -> win/loss; critical veto (always-pass -> always-fail on a
  critical case, or a critical group worse at p < 0.1) -> loss.
- a practice-brief win is re-run with fresh runs and must keep its direction (no p needed) to count.
- every claimed win re-runs B on A's always-pass critical cases; any of them below 2/3 is a regression.
Acceptance (section 5): practice not a loss (and confirmed), no loss on at least 3 fake briefs, regression clean.
Builder errors on fake briefs (section 5 item 4) show up as missing agent files here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentforge.domain.collections import list_briefs
from agentforge.domain.collections.cases import CRITICAL_GROUPS
from agentforge.experiments.col_common import dump, groups, load_agent, results_dir, run_cases
from agentforge.schemas import AgentConfig
from agentforge.stats import critical_veto, paired, verdict


def baseline_sets(brief: str, label: str) -> tuple[list[str] | None, list[str]]:
    path = results_dir(brief, label) / "baseline.json"
    if not path.exists():
        return None, []
    data = json.loads(path.read_text())
    return data["dev_set"], data["critical_regression_set"]


def compare_brief(best: AgentConfig, candidate: AgentConfig, brief: str, platform: str, runs: int, tag: str,
                  only_groups: tuple[str, ...] | None = None) -> dict:
    dev, regression = baseline_sets(brief, best.version_label)
    group_of = groups(brief)
    cases = dev if dev is not None else sorted(group_of)
    if only_groups:
        cases = [c for c in cases if group_of.get(c) in only_groups]
    _, a = run_cases(best, brief, platform, runs, f"{tag}_A", cases)
    _, b = run_cases(candidate, brief, platform, runs, f"{tag}_B_vs_{best.version_label}", cases)
    result = paired(a, b)
    veto = critical_veto(a, b, group_of, CRITICAL_GROUPS)
    return {"brief": brief, "cases": sorted(a), "verdict": verdict(result, veto), "paired": result.to_dict(), "veto": veto,
            "A": {k: list(v) for k, v in a.items()}, "B": {k: list(v) for k, v in b.items()}, "regression_cases": regression}


def gate(best: dict[str, AgentConfig], candidate: dict[str, AgentConfig], practice: str, platform: str = "local",
         runs: int = 3, only_groups: tuple[str, ...] | None = None) -> dict:
    """best/candidate: agent per brief; the practice brief must be present, other keys are the fake briefs.
    Briefs where the candidate equals the best (e.g. every add-on skipped as contradicting that brief) are not run."""
    same = [b for b in candidate if b in best and identical(best[b], candidate[b])]
    fakes = [b for b in candidate if b != practice and b in best and b not in same]
    if practice in same:
        return {"best": best[practice].version_label, "candidate": candidate[practice].version_label, "identical": same,
                "practice": {"brief": practice, "verdict": "equal", "paired": paired({}, {}).to_dict(), "veto": [], "identical": True},
                "fakes": [], "win": False, "accepted": False,
                "decision": "nothing to test: the candidate equals the best on the practice brief"}
    result = compare_brief(best[practice], candidate[practice], practice, platform, runs, "ab", only_groups)
    if result["verdict"] == "win":
        rerun = compare_brief(best[practice], candidate[practice], practice, platform, runs, "ab_rerun", only_groups)
        result["rerun"] = {"verdict": rerun["verdict"], "paired": rerun["paired"], "veto": rerun["veto"]}
        result["confirmed"] = rerun["paired"]["mean_diff"] > 0 and not rerun["veto"]
        _, reg = run_cases(candidate[practice], practice, platform, runs, "regression", result["regression_cases"])
        result["regression"] = {c: list(v) for c, v in reg.items()}
        result["regression_failures"] = sorted(c for c, (p, n) in reg.items() if p * 3 < 2 * n)
    fake_results = [compare_brief(best[b], candidate[b], b, platform, runs, "ab", only_groups) for b in fakes]

    no_loss = [r["brief"] for r in fake_results if r["verdict"] != "loss"]
    regression_clean = not result.get("regression_failures")
    # Section 5 item 2: no drop on any fake brief, and at least 3 of them tested.
    accepted = (result["verdict"] != "loss" and result.get("confirmed", True) and regression_clean
                and len(fakes) >= 3 and len(no_loss) == len(fakes))
    win = accepted and result["verdict"] == "win" and result.get("confirmed", False)
    return {
        "best": best[practice].version_label, "candidate": candidate[practice].version_label, "identical": same, "practice": result,
        "fakes": fake_results, "win": win, "accepted": accepted,
        "decision": _decision(win, accepted, rejected=(result["verdict"] == "loss" or not result.get("confirmed", True)
                                                       or not regression_clean or len(no_loss) < len(fakes)), n_fakes=len(fakes)),
    }


def _decision(win: bool, accepted: bool, rejected: bool, n_fakes: int) -> str:
    if win:
        return "lock candidate (win)"
    if accepted:
        return "keep candidate (not worse; simplest-wins rule decides)"
    if not rejected and n_fakes < 3:
        return "not accepted: fewer than 3 fake briefs tested"
    return "reject candidate"


def identical(a: AgentConfig, b: AgentConfig) -> bool:
    return (a.system_prompt, a.first_message, a.workflow, [t.model_dump() for t in a.tools]) == \
           (b.system_prompt, b.first_message, b.workflow, [t.model_dump() for t in b.tools])


def agents_for(template: str, briefs: list[str]) -> dict[str, AgentConfig]:
    if "{brief}" not in template:
        return {briefs[0]: load_agent(template)}
    return {b: load_agent(template.format(brief=b)) for b in briefs if Path(template.format(brief=b)).exists()}


def report(summary: dict, out: Path) -> None:
    practice = summary["practice"]
    p = practice["paired"]
    print(f"practice {practice['brief']}: {practice['verdict']} (wins {p['wins']}, losses {p['losses']}, p={p['p']:.3f}, "
          f"mean {p['mean_diff']:+.2f}){' veto: ' + '; '.join(practice['veto']) if practice['veto'] else ''}")
    if summary.get("identical"):
        print(f"skipped (candidate = best): {', '.join(summary['identical'])}")
    for r in summary["fakes"]:
        print(f"fake {r['brief']}: {r['verdict']} (p={r['paired']['p']:.3f}, mean {r['paired']['mean_diff']:+.2f})")
    print(f"-> {summary['decision']}  ({out})")


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--best", required=True, help="agent path; {brief} is replaced per brief")
    parser.add_argument("--candidate", required=True, help="agent path; {brief} is replaced per brief")
    parser.add_argument("--practice", required=True)
    parser.add_argument("--fake", default="", help="comma-separated fake briefs; default all others")
    parser.add_argument("--platform", default="local")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args(argv)

    fakes = [b for b in args.fake.split(",") if b] or [b for b in list_briefs() if b != args.practice]
    briefs = [args.practice, *fakes]
    best, candidate = agents_for(args.best, briefs), agents_for(args.candidate, briefs)
    if args.practice not in best or args.practice not in candidate:
        raise SystemExit(f"no agent for the practice brief {args.practice}")
    summary = gate(best, candidate, args.practice, args.platform, args.runs)
    out = results_dir(args.practice, summary["candidate"]) / f"paired_vs_{summary['best']}.json"
    dump(out, summary)
    report(summary, out)
    return summary


if __name__ == "__main__":
    main()
