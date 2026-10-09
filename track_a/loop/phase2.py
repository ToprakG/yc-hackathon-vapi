"""Phase 2: store 3–5 personas per V1, then stop unless Vapi simulation was requested.

The regression gate is a later phase. It does not run on these results.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loop.adversary import accept_scenarios, generate_scenarios, load_adversary_prompt, mock_scenarios
from loop.llm import LLMClient, make_llm_client
from loop.paths import shared, track_b
from loop.schema import dump_json, load_json, validate_agent, validate_run
from loop.store import load_binding, load_development_tasks
from loop.vapi_runtime import VapiRuntime


def scenarios_path(root: Path, task_id: str, version: str) -> Path:
    return shared(root) / "versions" / task_id / version / "scenarios.json"


def run_path(root: Path, run: dict[str, Any]) -> Path:
    return shared(root) / "runs" / run["task_id"] / run["agent_version"] / f"{run['scenario_id']}.json"


def run_phase2(
    root: Path,
    *,
    mock: bool = False,
    simulate: bool = False,
    force: bool = False,
    task_filter: str | None = None,
    llm: LLMClient | None = None,
    runtime: VapiRuntime | None = None,
) -> int:
    tasks = [task for task in load_development_tasks(root) if not task_filter or task["id"] == task_filter]
    if task_filter and not tasks:
        print(f"no development task named {task_filter}")
        return 1
    prompt_path = track_b(root) / "prompts" / "adversary" / "v1.md"
    prompt_version, prompt_text = load_adversary_prompt(prompt_path)
    if mock:
        prompt_version = "mock-adversary"
    elif llm is None and not _all_scenarios_cached(root, tasks, force):
        llm = make_llm_client()

    for task in tasks:
        config_path = shared(root) / "versions" / task["id"] / "v1" / "agent_config.json"
        if not config_path.exists():
            print(f"missing V1 for {task['id']}. Run build before phase 2.")
            return 1
        config = validate_agent(load_json(config_path), task)
        bundle_path = scenarios_path(root, task["id"], config["version"])
        if bundle_path.exists() and not force:
            bundle = load_json(bundle_path)
            scenarios = accept_scenarios(task, bundle)
            print(f"using {len(scenarios)} stored scenarios for {config['id']} ({bundle.get('prompt_version')})")
        else:
            draft = mock_scenarios(task) if mock else None
            scenarios = generate_scenarios(
                task,
                config,
                prompt_text=prompt_text,
                llm=llm,
                draft=draft,
            )
            dump_json(
                bundle_path,
                {
                    "prompt_version": prompt_version,
                    "agent_version": config["id"],
                    "scenarios": scenarios,
                },
            )
            print(f"stored {len(scenarios)} scenarios for {config['id']} ({prompt_version}) -> {bundle_path}")
        if not simulate:
            continue
        binding = load_binding(root, config)
        if not binding or not binding.get("assistant_id"):
            print(f"{config['id']} is not published. Run build --publish before Vapi testing.")
            return 1
        if runtime is None:
            runtime = VapiRuntime.from_env()
        runs = runtime.simulate(config, scenarios, binding["assistant_id"], task)
        if not 3 <= len(runs) <= 5:
            print(f"{config['id']} simulation returned {len(runs)} transcripts; expected 3 to 5")
            return 1
        for run in runs:
            saved = validate_run(run)
            path = run_path(root, saved)
            dump_json(path, saved)
            print(f"stored transcript {saved['scenario_id']} -> {path}")

    if not simulate:
        print("Vapi testing is the next step. The regression gate does not run until each task has 3–5 transcripts.")
        print("python3 track_a/scripts/run_loop.py phase2 --simulate")
    return 0


def _all_scenarios_cached(root: Path, tasks: list[dict[str, Any]], force: bool) -> bool:
    if force:
        return False
    return all(scenarios_path(root, task["id"], "v1").exists() for task in tasks)
