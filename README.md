# agentforge

Builds Turkish voice agents for insurance/banking, attacks them with simulated callers, and patches them
until a held-out gate stops improving. Vapi today, Freya tomorrow: all platform code sits behind
`agentforge/platform/base.py`. The plan and schedule live in `ROADMAP.md`.

```
TASK + TOOLS -> LLM BUILDER -> V1 -> LLM ADVERSARY (3-5 personas) + COVERAGE -> SIMULATIONS -> TRANSCRIPTS
-> LLM ANALYZER (generalized behavioral bugs) -> FAILURE REPORT
   -> LLM TEST GENERATOR -> UNIT TESTS
   -> LLM PATCHER -> V2
-> SIMULATIONS + TESTS -> REGRESSION GATE -> COMMIT / DISCARD -> BEST
```

| Folder | Box |
|---|---|
| `agentforge/schemas.py` | Shared shapes. `Persona` and `Assertion` match Freya's format. |
| `agentforge/llm.py` | `call_llm(system, user, model, json_schema, temperature)` for Anthropic and OpenAI. |
| `agentforge/platform/` | `Platform` interface, `vapi.py`, `freya.py`. |
| `agentforge/domain/kasko/` | Car-insurance claim SOP, tools, synthetic policies, mock tool server. |
| `agentforge/build/` | LLM builder: task + tools -> V1. |
| `agentforge/testgen/` | Adversary + coverage personas, train/heldout split, assertions, unit tests. |
| `agentforge/run/` | Freya-style LLM judge and the suite runner. |
| `agentforge/analyze/` | Failure analyzer. |
| `agentforge/patch/` | Patcher (surgical or free). |
| `agentforge/loop/` | Regression gate and the loop. |
| `agentforge/experiments/` | Noise test and the A/B/C comparison on the blind set. |
| `runs/`, `results/` | Outputs (gitignored). |

`track_a/` and `track_b/` hold the earlier prototype and are not used by `agentforge`.

## Setup

```bash
uv venv -p 3.12 .venv && uv pip install -p .venv -e .
cp .env.example .env   # fill in keys and models
.venv/bin/python -m pytest
```
