"""Score builder-only vs the loop on the blind set. The only numbers that matter."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from agentforge.build import builder
from agentforge.config import DOMAIN_DIR, RESULTS_DIR, RUNS_DIR
from agentforge.domain import load_domain
from agentforge.experiments.noise import load_noise
from agentforge.loop import run_loop
from agentforge.platform import get_platform
from agentforge.run import runner
from agentforge.schemas import AgentConfig, Assertion, Persona
from agentforge.store import load_models, save_json

console = Console()
VARIANTS = {"A": ("builder", None), "B": ("loop", "surgical"), "C": ("loop", "free")}


def load_blind(domain_dir: Path) -> tuple[list[Persona], list[Assertion]]:
    personas_path, assertions_path = domain_dir / "blind_personas.json", domain_dir / "blind_assertions.json"
    if not personas_path.exists() or not assertions_path.exists():
        raise SystemExit(f"blind set missing: {personas_path} / {assertions_path} (stage S4)")
    return load_models(personas_path, Persona), load_models(assertions_path, Assertion)


def loop_counts(run_tag: str) -> dict[str, int]:
    """Count COMMIT/DISCARD for one variant from the loop log."""
    counts = {"committed": 0, "discarded": 0}
    if not run_loop.LOOP_LOG.exists():
        return counts
    for line in run_loop.LOOP_LOG.read_text().splitlines():
        record = json.loads(line)
        if not str(record.get("best_version", "")).startswith(f"{run_tag}-"):
            continue
        if record["decision"] == "COMMIT":
            counts["committed"] += 1
        elif record["decision"] == "DISCARD":
            counts["discarded"] += 1
    return counts


def noise_label(delta: float, noise: dict | None) -> str:
    if noise is None:
        return "no noise.json"
    return "above noise" if abs(delta) > noise["stdev"] else "within noise"


def compare(variants: list[str], platform_name: str = "vapi", max_iters: int = 3, runs: int = 3) -> dict:
    domain_dir = DOMAIN_DIR / "kasko"
    blind_personas, blind_assertions = load_blind(domain_dir)
    platform = get_platform(platform_name)
    v1_path = RUNS_DIR / "v1" / "agent.json"
    if v1_path.exists():
        v1 = AgentConfig.model_validate_json(v1_path.read_text())
    else:
        v1 = builder.build_agent(*load_domain(domain_dir))

    def run_variant(name: str) -> dict:
        mode, patch_mode = VARIANTS[name]
        started = time.monotonic()
        if mode == "builder":
            agent = v1
        else:
            agent = run_loop.run_pipeline(
                domain_dir, platform, mode="loop", max_iters=max_iters,
                patch_mode=patch_mode, runs_per_persona=runs, run_tag=name, v1=v1,
            )
        build_minutes = (time.monotonic() - started) / 60
        scored = runner.run_suite(platform, agent, blind_personas, blind_assertions, runs_per_persona=runs, set_name="blind")
        metrics = runner.metrics(scored)
        return {
            "variant": name,
            "agent_version": agent.version_label,
            "blind_pass_rate": metrics["pass_rate"],
            "pass_hat_3": metrics["pass_hat_3"],
            "per_assertion_fail_counts": metrics["per_assertion_fail_counts"],
            "per_persona": metrics["per_persona"],
            "prompt_chars": len(agent.system_prompt),
            **(loop_counts(name) if mode == "loop" else {"committed": 0, "discarded": 0}),
            "minutes": round(build_minutes + metrics["total_minutes"], 1),
            "cost_usd": round(metrics["total_cost"] or 0, 2),
        }

    # Variants are independent (own version labels and tool sessions), so they run side by side.
    with ThreadPoolExecutor(max_workers=len(variants)) as pool:
        rows = dict(zip(variants, pool.map(run_variant, variants)))

    noise = load_noise()
    base = rows.get("A")
    for row in rows.values():
        if base is None or row is base:
            row["vs_A"] = None
            continue
        delta = row["blind_pass_rate"] - base["blind_pass_rate"]
        row["vs_A"] = {"delta": round(delta, 3), "label": noise_label(delta, noise)}

    result = {"runs_per_persona": runs, "max_iters": max_iters, "noise": noise, "variants": rows}
    save_json(RESULTS_DIR / "compare.json", result)
    (RESULTS_DIR / "compare.md").write_text(to_markdown(result))
    print_table(result)
    return result


def to_markdown(result: dict) -> str:
    noise = result["noise"]
    noise_line = f"{noise['mean']:.3f} ± {noise['stdev']:.3f}" if noise else "not measured"
    lines = [
        "# Blind-set comparison",
        "",
        f"{result['runs_per_persona']} runs per persona, up to {result['max_iters']} loop iterations. "
        f"V1 noise on the blind set: {noise_line}.",
        "",
        "| Variant | Version | Blind pass rate | pass^3 | vs A | Prompt chars | Commit/Discard | Minutes | $ |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in result["variants"].values():
        vs = "—" if row["vs_A"] is None else f"{row['vs_A']['delta']:+.3f} ({row['vs_A']['label']})"
        lines.append(
            f"| {row['variant']} | {row['agent_version']} | {row['blind_pass_rate']:.3f} | {row['pass_hat_3']:.3f} | {vs} "
            f"| {row['prompt_chars']} | {row['committed']}/{row['discarded']} | {row['minutes']} | {row['cost_usd']} |"
        )
    lines += ["", "## Assertion failures", ""]
    for row in result["variants"].values():
        fails = ", ".join(f"{name}: {count}" for name, count in sorted(row["per_assertion_fail_counts"].items())) or "none"
        lines.append(f"- **{row['variant']}**: {fails}")
    return "\n".join(lines) + "\n"


def print_table(result: dict) -> None:
    table = Table(title="Blind set")
    for column in ("Variant", "Pass rate", "pass^3", "vs A", "Prompt", "C/D", "Min", "$"):
        table.add_column(column)
    for row in result["variants"].values():
        vs = "—" if row["vs_A"] is None else f"{row['vs_A']['delta']:+.3f} {row['vs_A']['label']}"
        table.add_row(
            row["variant"], f"{row['blind_pass_rate']:.3f}", f"{row['pass_hat_3']:.3f}", vs,
            str(row["prompt_chars"]), f"{row['committed']}/{row['discarded']}", str(row["minutes"]), str(row["cost_usd"]),
        )
    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(description="A: builder only, B: loop surgical, C: loop free. Scored on the blind set.")
    parser.add_argument("--variants", default="A,B,C")
    parser.add_argument("--platform", default="vapi")
    parser.add_argument("--max-iters", type=int, default=3)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    compare([v.strip() for v in args.variants.split(",")], args.platform, args.max_iters, args.runs)


if __name__ == "__main__":
    main()
