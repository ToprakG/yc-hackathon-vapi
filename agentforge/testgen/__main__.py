"""python -m agentforge.testgen kasko -> runs/testsets/{personas,assertions}.json"""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.table import Table

from agentforge.config import RUNS_DIR
from agentforge.domain import load_domain
from agentforge.schemas import AgentConfig, Persona
from agentforge.store import load_model, save_json
from agentforge.testgen.adversary import generate_adversary
from agentforge.testgen.assertions import generate_assertions
from agentforge.testgen.coverage import generate_coverage
from agentforge.testgen.split import split_personas


def print_personas(personas: list[Persona]) -> None:
    table = Table(title="Personas")
    for column in ("name", "split", "tags", "successCriteria"):
        table.add_column(column)
    for persona in personas:
        table.add_row(persona.name, persona.split or "-", ", ".join(persona.tags), persona.successCriteria[:80])
    Console().print(table)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("domain")
    parser.add_argument("--agent", default=str(RUNS_DIR / "v1" / "agent.json"))
    parser.add_argument("--adversary", type=int, default=4)
    parser.add_argument("--coverage", type=int, default=6)
    args = parser.parse_args()

    task_md, tools = load_domain(args.domain)
    cfg = load_model(Path(args.agent), AgentConfig)
    personas = generate_adversary(task_md, tools, cfg, n=args.adversary) + generate_coverage(task_md, tools, n=args.coverage)
    personas = split_personas(personas)
    assertions = generate_assertions(task_md)
    save_json(RUNS_DIR / "testsets" / "personas.json", personas)
    save_json(RUNS_DIR / "testsets" / "assertions.json", assertions)
    print_personas(personas)
    Console().print(f"{len(assertions)} assertions: " + ", ".join(a.name for a in assertions))


if __name__ == "__main__":
    main()
