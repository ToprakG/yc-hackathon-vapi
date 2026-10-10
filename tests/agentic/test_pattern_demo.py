import json

import pytest

from builder.agentic.tools import lint, openapi_summary
from tests.agentic.conftest import REPO

FIX = REPO / "tests" / "agentic" / "fixtures"
SKILL = REPO / "builder" / "agentic" / "skill" / "build-collections-agent"


@pytest.fixture
def demo():
    return json.loads((FIX / "pattern_demo.workflow.json").read_text())


@pytest.fixture
def demo_api():
    return openapi_summary.load(FIX / "pattern_demo.openapi.json")


def test_demo_lints_clean(demo, demo_api):
    report = lint.lint(demo, demo_api, call_vars=["customer_id", "first_name", "last_name", "title", "now"])
    assert report == {"errors": [], "warnings": []}


def test_fragments_are_exact_pieces_of_the_demo(demo):
    from tests.agentic.fixtures.make_pattern_demo import FRAGMENTS

    files = sorted(p.name for p in (SKILL / "templates" / "fragments").glob("*.json"))
    assert files == sorted(FRAGMENTS)
    for name, path in FRAGMENTS.items():
        part = demo
        for key in path:
            part = part[key]
        assert json.loads((SKILL / "templates" / "fragments" / name).read_text()) == part, name


def test_generator_is_in_sync(demo):
    from tests.agentic.fixtures.make_pattern_demo import API, WF

    assert WF == demo and API == json.loads((FIX / "pattern_demo.openapi.json").read_text())


def test_skill_files_exist_and_skill_md_is_short():
    for rel in ("SKILL.md", "reference/freya-cookbook.md", "reference/call-architecture.md", "reference/policy-schema.md",
                "reference/self-check.md", "templates/calendar.py"):
        assert (SKILL / rel).exists(), rel
    text = (SKILL / "SKILL.md").read_text()
    assert text.startswith("---\nname: build-collections-agent\n") and len(text.splitlines()) < 250
