"""Offline tests for the agentic builder. No network, no SDK calls."""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

FAKES = sorted((REPO / "testbed" / "fake_briefs").glob("*/tools.openapi.json"))


@pytest.fixture
def kit_api():
    from builder.agentic.tools import openapi_summary

    return openapi_summary.load(REPO / "tools" / "openapi.json")


@pytest.fixture
def base_agent():
    return json.loads((REPO / "examples" / "base-agent.json").read_text())


@pytest.fixture(autouse=True)
def no_real_local_sims(monkeypatch):
    """Offline tests never play real local simulations (they would call OpenRouter)."""
    monkeypatch.setenv("LOCALSIM_OFF", "1")
