# Running the builder (T-CC)

## The one command

    scripts/final_run.sh <brief file> [<more brief material> ...] <tool-api.json> <out dir>

e.g. `scripts/final_run.sh briefs/brief-a.md tools/openapi.json out/final/brief-a`. Several brief files = one brief given in parts (a later
part overrides an earlier one). `scripts/final_run.sh` does: extraction (two readings + verifier + deterministic fixups; with
`FINAL_VOTES=3` the default, three extractions voted on two fields) -> compile with the kept flags (`M1_FLAGS.txt` / `FINAL_FLAGS.txt`) ->
lint -> Freya self-test and repair rounds (patcher mode in `FINAL_MODE.txt`, `patcher_on`) -> the last green build in `<out dir>`
(`workflow.json`, `policy.json`, `build_report.json`, `final_run.log`). Only the brief files and the tool API are read; no test data.

Package for the submission form: `scripts/package_submission.sh <out dir>`.

## Setup (from a fresh clone; checked on Python 3.14 with no API keys set: `python -m pytest tests/template_cc -q` -> 536 passed, 1 skipped)

    python3 -m venv .venv310 && .venv310/bin/python -m pip install pydantic httpx python-dotenv fastapi uvicorn pyyaml rich anthropic openai pytest claude-agent-sdk
    git clone https://github.com/ToprakG/build-the-builder vendor/build-the-builder     # the hackathon kit; gitignored, see below

- `claude-agent-sdk` (the patcher) is not listed in `pyproject.toml`; the packages above are everything the builder, the tests and the mock bank import.
- `vendor/build-the-builder` is the hackathon kit repo (we used commit `4fb4849`). The builder itself (extraction, compile, lint) does not
  need it. The Freya self-test, the mock bank and the evaluation scripts do (they import its chat driver, mock bank and scorer), and the
  tests run without it. It is not committed (`.gitignore`), so clone it as above.
- `.env` is never committed. Put the names from the table below in it, or export them.

## Environment (names only; set them in the shell or in a `.env` next to the repo, never commit values)

| name | needed for |
|---|---|
| `TCC_LLM_PROVIDER` | which LLM backend the builder uses: `anthropic`, `openrouter`, or `claude_cli` (default when unset: the model strings in `builder/template_cc/io.py`, i.e. `claude_cli:sonnet`, which needs a Claude Code login) |
| `ANTHROPIC_API_KEY` | **documented path without a Claude Code login**: `TCC_LLM_PROVIDER=anthropic` -> `anthropic:claude-sonnet-5-5` |
| `OPENROUTER_API_KEY` | `TCC_LLM_PROVIDER=openrouter` (Sonnet 5.5 through OpenRouter) |
| `FREYA_API_KEY` | the Freya workspace (self-test, save, export). One key only. |
| `TCC_EXTRACT_MODEL`, `TCC_ANALYZE_MODEL`, `TCC_PATCH_MODEL`, `DECISION_MODEL` | optional model overrides |
| `FEATURES`, `FINAL_VOTES`, `FINAL_MODE`, `MAX_ROUNDS` | optional build knobs (see the header of `scripts/final_run.sh`, `scripts/final_build.sh`) |
| `FREYA_BANK_TEAM_KEY` | only for the evaluation scripts under `scripts/` that talk to the mock bank; not needed to build |

Reproducing without a Claude Code login:

    export TCC_LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=...      # value from your own account
    export FREYA_API_KEY=...
    scripts/final_run.sh briefs/brief-a.md tools/openapi.json out/final/brief-a

## Runtime and Python

- Python: 3.10 or newer (`requires-python = ">=3.10"` in `pyproject.toml`); developed and tested on 3.10.20 (`.venv310`). Standard library plus the packages in `pyproject.toml`; the patcher
  uses the Claude Agent SDK (`claude_agent_sdk`).
- Expected runtime: at most 30 minutes per brief (`--budget-min 30 --ship-min 26`; the build ships the last green workflow by minute 26 at the latest).
  Extraction takes about 2-4 minutes per brief, compile and lint seconds, the rest is the Freya self-test and repair rounds.
- Tests (offline, no network): `python -m pytest tests/template_cc -q`.

## Known behaviour worth knowing

- Amounts: the first persuasion attempt asks for the full past-due amount (or the floor when the customer already said the full amount is too
  much). If the customer names their own amount between the floor and the full amount, both included, the agent accepts it as the brief's rules say;
  it does not push for the full amount, so a promised total can be below the maximum. This is deliberate and was not changed.
