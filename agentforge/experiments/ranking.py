"""T0.4: do unit-test scores pick the same winner as Freya? (pairwise, not a 5-variant Spearman)

python -m agentforge.experiments.ranking unit --brief marmara_standard --agent runs/col-v1/agent.json [--repeats 3]
    -> unit-test score of one agent (the 4 critical-moment tests x repeats), for the pairs file
python -m agentforge.experiments.ranking check pairs.json
    pairs.json: [{"name": "v1 vs v2", "unit": {"A": 0.50, "B": 0.75},
                  "freya": {"A": {"<case>": [passed, runs], ...}, "B": {...}}}, ...]

Only pairs where Freya itself separates A and B (paired test p < 0.1) count: when Freya's own difference is noise its
"winner" is a coin flip and no unit-test score could agree 80% of the time. Rule: >= 8 such pairs and >= 80% same
winner -> unit tests may screen variants and score best-of-K; otherwise regression checks only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentforge.domain.collections import load_unit_tests
from agentforge.experiments.col_common import load_agent
from agentforge.platform import get_platform
from agentforge.stats import ALPHA, paired

MIN_PAIRS = 8
MIN_AGREEMENT = 0.8


def unit_score(agent_path: str, brief: str, platform_name: str = "local", repeats: int = 3) -> dict:
    cfg = load_agent(agent_path)
    platform = get_platform(platform_name, brief=brief if platform_name == "local" else None)
    tests = load_unit_tests(brief)
    verdicts = [platform.run_unit_test(cfg, t) for _ in range(repeats) for t in tests]
    per_test = {t.name: sum(v.passed for v in verdicts if v.check_name == t.name) for t in tests}
    return {"agent": cfg.version_label, "brief": brief, "score": sum(v.passed for v in verdicts) / len(verdicts),
            "per_test": per_test, "repeats": repeats}


def check(pairs: list[dict]) -> dict:
    rows = []
    for pair in pairs:
        freya = paired({k: tuple(v) for k, v in pair["freya"]["A"].items()}, {k: tuple(v) for k, v in pair["freya"]["B"].items()})
        unit_diff = pair["unit"]["B"] - pair["unit"]["A"]
        clear = freya.p < ALPHA and freya.mean_diff != 0
        rows.append({"name": pair.get("name"), "freya_p": freya.p, "freya_diff": freya.mean_diff, "unit_diff": unit_diff,
                     "clear": clear, "same_winner": clear and unit_diff * freya.mean_diff > 0})
    clear_rows = [r for r in rows if r["clear"]]
    rate = sum(r["same_winner"] for r in clear_rows) / len(clear_rows) if clear_rows else None
    if len(clear_rows) < MIN_PAIRS:
        decision = f"undecided: {len(clear_rows)} pairs where Freya separates A and B, need {MIN_PAIRS}; unit tests stay regression-only"
    elif rate >= MIN_AGREEMENT:
        decision = "unit tests screen variants and score best-of-K"
    else:
        decision = "unit tests stay regression-only"
    return {"pairs": rows, "clear_pairs": len(clear_rows), "agreement": rate, "decision": decision}


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_unit = sub.add_parser("unit")
    p_unit.add_argument("--brief", required=True)
    p_unit.add_argument("--agent", required=True)
    p_unit.add_argument("--platform", default="local")
    p_unit.add_argument("--repeats", type=int, default=3)
    p_check = sub.add_parser("check")
    p_check.add_argument("pairs")
    args = parser.parse_args(argv)
    if args.cmd == "unit":
        result = unit_score(args.agent, args.brief, args.platform, args.repeats)
    else:
        result = check(json.loads(Path(args.pairs).read_text()))
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return result


if __name__ == "__main__":
    main()
