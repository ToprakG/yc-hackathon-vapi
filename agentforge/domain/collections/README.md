# Collections domain (TEST_PLAN "Ön koşul" + section 0)

One folder per bank brief in `briefs/<id>/`. The builder reads only `sop.md` and `tools.json`; everything else is
test-side ground truth.

| File | What | Written by |
|---|---|---|
| `sop.md` | the brief | by hand (practice briefs) / copied in at kickoff |
| `policy.json` | limits and rules as data (`policy.py`) | by hand / `extract_policy` (LLM) at kickoff, then reviewed |
| `tools.json` | the 7 tools under the brief's own names | `prepare` |
| `accounts.json` | 6 mock customers | `prepare` (kept if present) |
| `personas.json` | 16 case types as Freya personas, with `variables` (customerVariables) | `prepare` |
| `unit_tests.json` | 4 critical moments, Freya `tool_call` assertions | `prepare` |
| `checks.json` | decision-model check list (code + yes/no) | `prepare` |

Practice briefs: `marmara_standard` (English, clean), `ege_strict` (strict, verbatim opening, tight limits),
`anadolu_tr` (Turkish prose, discount rule), `karadeniz_noplan` (no plans), `trakya_oddformat` (key:value format,
renamed tools).

## Commands

```bash
python -m agentforge.domain.collections prepare            # regenerate derived files for every brief
python -m agentforge.domain.collections check              # offline consistency check
python -m agentforge.domain.collections new <id> --from brief.md [--tools a,b,c]   # kickoff: real brief in

python -m agentforge.build.builder collections/<id>        # V1 for a brief -> runs/col-<id>-v1/agent.json

# T0.1 baseline x 3 (cached), fixes dev / regression case sets
python -m agentforge.experiments.baseline --brief <id> --agent runs/col-<id>-v1/agent.json --platform local
# T0.3 decision-judge vs Freya verdicts, picks the branch
python -m agentforge.experiments.agreement --brief <id> --runs runs/<label>/<id>_freya.jsonl [--labels labels.json]
# T0.4 unit-test score vs Freya winner
python -m agentforge.experiments.ranking unit --brief <id> --agent A.json
python -m agentforge.experiments.ranking check pairs.json
# Gate: candidate vs current best, practice + fake briefs, re-run and regression rules.
# A change is a builder change, so each brief has its own agent: {brief} is filled in per brief.
python -m agentforge.experiments.paired --best 'runs/col-{brief}-v1/agent.json' --candidate 'runs/col-{brief}-v1+p1/agent.json' --practice <id>

# Section 2
python -m agentforge.experiments.section2 cluster --brief <id> --agent runs/col-<id>-v1/agent.json
python -m agentforge.experiments.section2 p1 --best 'runs/col-{brief}-v1/agent.json' --practice <id>
python -m agentforge.experiments.section2 single --test T2.2 --best 'runs/col-{brief}-v1/agent.json' --practice <id>
python -m agentforge.experiments.section2 rebuild --test T2.5 --practice <id>
```

Section 4 (overnight; `agentforge/optimize/`):

```bash
python -m agentforge.experiments.section4 gepa run --best 'runs/col-{brief}-v1/agent.json' --practice <id> --budget 3000 [--resume]
python -m agentforge.experiments.section4 gepa confirm --best 'runs/col-{brief}-v1/agent.json' --practice <id>   # on Freya
python -m agentforge.experiments.section4 aflow --best 'runs/col-{brief}-v1/agent.json' --practice <id>
python -m agentforge.experiments.section4 lessons mine --runs runs/col-<id>-v1/<id>_baseline_*.jsonl
python -m agentforge.experiments.section4 lessons test --best 'runs/col-{brief}-v1/agent.json' --practice <id>
```

For Freya runs of collections agents, set `COLLECTIONS_TOOLS_BASE_URL` to the tunnel in front of the collections
tools server; each brief's agent then calls `{url}/{brief}/tools/{name}`.

Section 2 add-ons live in `agentforge/build/addons.py` (P1's 8 items, T2.2 order, T2.3 limits format, T2.4
examples). T2.5 (instruction language) and T2.6 (reading of ambiguous rules) are builder options. Winners go to
`results/collections/locked_addons.json`; `python -m agentforge.build.builder collections/<id>` applies them to
every new build.

Mock tools over HTTP (Vapi/Freya webhooks): `uvicorn agentforge.domain.collections.tools_server:app --port 8002`,
tool URL `{tunnel}/{brief}/tools/{name}`. Set `COLLECTIONS_TODAY=YYYY-MM-DD` to pin the date the backend, the
`{{today}}` variable and the checks agree on.

## How the pieces map to Freya

- Customer data travels as Freya **customerVariables** (`{{customer_name}}`, `{{today}}`, ...): `/chat/message`
  `customerVariables`, unit-test `input.customerVariables`, simulation `customerVariablesMap`. LocalPlatform fills
  `{{name}}` the same way.
- Persona fields are Freya's (`name, prompt, successCriteria, evaluationPrompt, tags`); `variables` is ours and is not
  uploaded. Tags: `case:*`, `group:*`, `critical`, `brief:*`.
- Unit-test assertions are Freya `tool_call` assertions (`args` + `argsMatch: subset`, `negate`).
- The local judge is a decision model: one yes/no per check (`agentforge/run/decision.py`), with tool-log facts
  checked in code. Freya's own issue taxonomy has a `decision-llm` category (workflow routing decisions); if the
  final design uses a workflow, its condition nodes are where a decision model sits inside the agent.
