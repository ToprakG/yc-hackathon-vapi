"""Commands for Phase 0, Phase 1, and Phase 2."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from loop.builder import build_agent, load_builder_prompt, template_draft
from loop.llm import make_llm_client
from loop.paths import ROOT, track_b
from loop.phase0 import run_phase0
from loop.store import agent_path, load_binding, load_development_tasks, save_agent, save_binding
from loop.vapi_runtime import VapiRuntime


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def cmd_phase0(args: argparse.Namespace) -> int:
    return run_phase0(args.root)


def cmd_build(args: argparse.Namespace) -> int:
    load_dotenv(args.root / ".env")
    tasks = load_development_tasks(args.root)
    prompt_path = track_b(args.root) / "prompts" / "builder" / "v1.md"
    prompt_version, prompt_text = load_builder_prompt(prompt_path)
    llm = None
    if args.mock:
        prompt_version = "mock-builder"
    else:
        llm = make_llm_client()
    runtime = None
    if args.publish:
        runtime = VapiRuntime.from_env()
    for task in tasks:
        destination = agent_path(args.root, task["id"], "v1")
        if destination.exists() and not args.force:
            if not args.publish:
                print(f"skip {task['id']}: {destination} exists (pass --force to replace)")
                continue
            from loop.schema import load_json, validate_agent

            config = validate_agent(load_json(destination), task)
        else:
            draft = template_draft(task) if args.mock else None
            config = build_agent(
                task,
                prompt_text=prompt_text,
                prompt_version=prompt_version,
                llm=llm,
                draft=draft,
            )
            path = save_agent(args.root, config)
            print(f"stored {config['id']} ({config['prompt_version']}) -> {path}")
        if runtime is not None and config is not None:
            existing = load_binding(args.root, config)
            existing_id = None if existing is None or args.force else existing.get("assistant_id")
            if existing and not args.force:
                print(f"published {config['id']} -> {existing['assistant_id']} (already bound)")
                continue
            if args.force and existing:
                existing_id = existing.get("assistant_id")
            binding = runtime.publish(config, existing_id=existing_id)
            save_binding(args.root, config, binding)
            print(f"published {config['id']} -> {binding['assistant_id']}")
    return 0


def cmd_phase2(args: argparse.Namespace) -> int:
    load_dotenv(args.root / ".env")
    from loop.phase2 import run_phase2

    return run_phase2(
        args.root,
        mock=args.mock,
        simulate=args.simulate,
        force=args.force,
        task_filter=args.task,
    )


def cmd_publish(args: argparse.Namespace) -> int:
    load_dotenv(args.root / ".env")
    from loop.schema import load_json, validate_agent

    runtime = VapiRuntime.from_env()
    tasks = load_development_tasks(args.root)
    published = 0
    for task in tasks:
        if args.task and task["id"] != args.task:
            continue
        path = agent_path(args.root, task["id"], "v1")
        if not path.exists():
            print(f"missing V1 for {task['id']}. Run build first.")
            return 1
        config = validate_agent(load_json(path), task)
        existing = load_binding(args.root, config)
        existing_id = existing.get("assistant_id") if existing and args.force else None
        if existing and not args.force:
            print(f"published {config['id']} -> {existing['assistant_id']} (already bound)")
            published += 1
            continue
        binding = runtime.publish(config, existing_id=existing_id)
        save_binding(args.root, config, binding)
        print(f"published {config['id']} -> {binding['assistant_id']}")
        published += 1
    if published == 0:
        print("no V1 configs published")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=ROOT)
    parser = argparse.ArgumentParser(description="Closed-loop agent builder")
    sub = parser.add_subparsers(dest="command", required=True)

    phase0 = sub.add_parser("phase0", parents=[common], help="Run the canned loop through the gate")
    phase0.set_defaults(func=cmd_phase0)

    build = sub.add_parser("build", parents=[common], help="Build a schema-valid V1 for each development task")
    build.add_argument("--publish", action="store_true", help="Create or update the Vapi assistant")
    build.add_argument("--force", action="store_true", help="Replace an existing V1 and re-publish")
    build.add_argument("--mock", action="store_true", help="Store a template V1 without calling a model")
    build.set_defaults(func=cmd_build)

    phase2 = sub.add_parser("phase2", parents=[common], help="Write 3–5 personas per V1, then stop before the gate")
    phase2.add_argument("--simulate", action="store_true", help="Run the stored personas through Vapi webchat")
    phase2.add_argument("--mock", action="store_true", help="Write template personas without calling a model")
    phase2.add_argument("--force", action="store_true", help="Replace stored personas")
    phase2.add_argument("--task", help="One development task id")
    phase2.set_defaults(func=cmd_phase2)

    publish = sub.add_parser("publish", parents=[common], help="Push stored V1 configs through the Vapi adapter")
    publish.add_argument("--task", help="Publish one task id")
    publish.add_argument("--force", action="store_true", help="PATCH the bound assistant instead of skipping")
    publish.set_defaults(func=cmd_publish)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, ValueError) as error:
        print(f"error: {error}")
        return 1
