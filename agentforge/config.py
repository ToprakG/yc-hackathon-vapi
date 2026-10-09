"""Settings from .env. Model ids are "provider:model" or a bare name we can infer."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"
RESULTS_DIR = ROOT / "results"
DOMAIN_DIR = Path(__file__).resolve().parent / "domain"

load_dotenv(ROOT / ".env")


def split_model(model: str) -> tuple[str, str]:
    """Return (provider, model_name) for "openai:gpt-4o", "anthropic:claude-...", or a bare name."""
    if ":" in model:
        provider, name = model.split(":", 1)
        return provider.strip().lower(), name.strip()
    lowered = model.lower()
    if lowered.startswith("claude"):
        return "anthropic", model
    return "openai", model


@dataclass(frozen=True)
class Settings:
    vapi_api_key: str
    vapi_base_url: str
    tools_base_url: str
    agent_model: str
    judge_model: str
    builder_model: str
    simulator_model: str
    openai_api_key: str
    anthropic_api_key: str


def settings() -> Settings:
    env = os.environ.get
    return Settings(
        vapi_api_key=env("VAPI_API_KEY", "").strip(),
        vapi_base_url=env("VAPI_BASE_URL", "https://api.vapi.ai").rstrip("/"),
        tools_base_url=env("TOOLS_BASE_URL", "").strip().rstrip("/"),
        agent_model=env("AGENT_MODEL", "openai:gpt-4o-mini"),
        judge_model=env("JUDGE_MODEL", "anthropic:claude-sonnet-5-5"),
        builder_model=env("BUILDER_MODEL", "anthropic:claude-opus-5-5"),
        simulator_model=env("SIMULATOR_MODEL", "openai:gpt-4o-mini"),
        openai_api_key=env("OPENAI_API_KEY", "").strip(),
        anthropic_api_key=env("ANTHROPIC_API_KEY", "").strip(),
    )
