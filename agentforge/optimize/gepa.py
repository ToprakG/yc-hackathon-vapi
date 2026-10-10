"""GEPA-lite over the agent template (TEST_PLAN section 4).

A candidate is a list of template rules (free text, tools written as {log_promise_to_pay}) appended to every brief's
V1. Instances are (brief, case) pairs, i.e. persona names. The loop, after GEPA (Agrawal et al. 2025), cut down:

1. Split instances into a feedback set (mutations learn from it) and a Pareto set (selection is scored on it).
2. Pick a parent from the Pareto front, sampled by how many Pareto instances it is best on.
3. Run it on a small feedback minibatch; an LLM reads the failed transcripts and failed checks and rewrites the rules.
4. If the child beats the parent on that minibatch, score it on the Pareto set and add it to the pool.
5. Every few iterations, merge two front candidates (union of their rules) and treat the result like a child.

State is saved after every iteration so an overnight run can be resumed. Dev only; never part of the delivered builder.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from agentforge import llm
from agentforge.build.addons import apply_addons
from agentforge.config import settings
from agentforge.domain.collections import brief_dir, load_policy
from agentforge.domain.collections.policy import CANONICAL_TOOLS
from agentforge.run.scorer import render_transcript
from agentforge.schemas import AgentConfig, ScoredRun

MAX_RULES = 12
MAX_RULE_CHARS = 300


@dataclass
class Candidate:
    id: str
    rules: list[str]
    parent: str | None = None
    origin: str = "seed"  # seed | mutation | merge
    pareto: dict[str, float] = field(default_factory=dict)  # instance -> pass rate on the Pareto set

    @property
    def mean(self) -> float:
        return sum(self.pareto.values()) / len(self.pareto) if self.pareto else 0.0


@dataclass
class State:
    feedback: list[str]
    pareto_set: list[str]
    pool: list[Candidate]
    iteration: int = 0
    rollouts: int = 0
    log: list[dict] = field(default_factory=list)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1) + "\n")

    @classmethod
    def load(cls, path: Path) -> "State":
        data = json.loads(path.read_text())
        data["pool"] = [Candidate(**c) for c in data["pool"]]
        return cls(**data)


# --- Pareto selection -------------------------------------------------------------------------------------------


def pareto_front(pool: list[Candidate]) -> list[Candidate]:
    """Candidates that are best on at least one instance and not dominated by another candidate."""
    instances = sorted({i for c in pool for i in c.pareto})
    best = {i: max(c.pareto.get(i, 0.0) for c in pool) for i in instances}
    winners = [c for c in pool if any(c.pareto.get(i, 0.0) == best[i] and best[i] > 0 for i in instances)]

    def dominated(c: Candidate) -> bool:
        return any(all(d.pareto.get(i, 0.0) >= c.pareto.get(i, 0.0) for i in instances)
                   and any(d.pareto.get(i, 0.0) > c.pareto.get(i, 0.0) for i in instances)
                   for d in winners if d is not c)

    front = [c for c in winners if not dominated(c)]
    return front or sorted(pool, key=lambda c: -c.mean)[:1]


def sample_parent(pool: list[Candidate], rng: random.Random) -> Candidate:
    front = pareto_front(pool)
    instances = sorted({i for c in pool for i in c.pareto})
    best = {i: max(c.pareto.get(i, 0.0) for c in pool) for i in instances}
    weights = [max(1, sum(c.pareto.get(i, 0.0) == best[i] for i in instances)) for c in front]
    return rng.choices(front, weights=weights, k=1)[0]


def top(pool: list[Candidate], k: int = 3) -> list[Candidate]:
    return sorted(pool, key=lambda c: -c.mean)[:k]


# --- rules ------------------------------------------------------------------------------------------------------

REFLECT_SYSTEM = f"""You improve the rule list that is appended to a debt-collections voice agent's system prompt. The
same rules are used for many banks, so they must be general: no bank names, no amounts or limits (the agent already has
the bank's limits), no customer data. Write tools as placeholders: {', '.join('{' + t + '}' for t in CANONICAL_TOOLS)}.
Rules are in Turkish, one observable behaviour each, at most {MAX_RULE_CHARS} characters, at most {MAX_RULES} rules.
You get the current rules and calls where the agent failed, with the checks it failed. Keep rules that are not
implicated, fix or replace the ones that are, add a rule only for a failure that recurs. Return JSON {{"rules": [...]}}."""

RULES_SCHEMA = {"type": "object", "properties": {"rules": {"type": "array", "items": {"type": "string"}}}, "required": ["rules"]}


def clean_rules(rules: list) -> list[str]:
    out = [str(r).strip()[:MAX_RULE_CHARS] for r in rules if str(r).strip()]
    return list(dict.fromkeys(out))[:MAX_RULES]


def reflect(parent: Candidate, failures: list[ScoredRun], max_examples: int = 4) -> list[str]:
    examples = []
    for s in failures[:max_examples]:
        failed = [v.check_name for v in s.verdicts if not v.passed]
        examples.append(f"CASE {s.run.persona_name} — failed: {', '.join(failed)}\n{render_transcript(s.run)[:3000]}")
    user = (f"CURRENT RULES:\n{json.dumps(parent.rules, ensure_ascii=False, indent=1)}\n\nFAILED CALLS:\n\n"
            + "\n\n---\n\n".join(examples))
    result = llm.call_llm(REFLECT_SYSTEM, user, model=settings().builder_model, json_schema=RULES_SCHEMA, temperature=0.7)
    return clean_rules(result.get("rules") or [])


def merge(a: Candidate, b: Candidate) -> list[str]:
    """Union, a's rules first; GEPA's merge combines modules from two lineages, here rules are the modules."""
    return clean_rules([*a.rules, *b.rules])


# --- evaluation -------------------------------------------------------------------------------------------------

# (candidate, instances) -> (pass rate per instance, scored runs). Real runs: make_runner below.
Runner = Callable[[Candidate, list[str]], tuple[dict[str, float], list[ScoredRun]]]


def make_runner(base: dict[str, AgentConfig], platform: str, runs: int) -> Runner:
    from agentforge.experiments.col_common import run_cases

    def run(candidate: Candidate, instances: list[str]) -> tuple[dict[str, float], list[ScoredRun]]:
        rates: dict[str, float] = {}
        scored: list[ScoredRun] = []
        for brief in sorted({i.split(":")[0] for i in instances}):
            cases = [i for i in instances if i.startswith(f"{brief}:")]
            agent = apply_addons(base[brief], load_policy(brief_dir(brief)), [], label=f"gepa-{candidate.id}-{brief}",
                                 rules=candidate.rules)
            got, counts = run_cases(agent, brief, platform, runs, f"gepa_{candidate.id}", cases)
            scored += got
            rates.update({c: p / n for c, (p, n) in counts.items()})
        return rates, scored

    return run


def split_instances(instances: list[str], seed: int = 0) -> tuple[list[str], list[str]]:
    shuffled = sorted(instances)
    random.Random(seed).shuffle(shuffled)
    half = len(shuffled) // 2
    return sorted(shuffled[:half]), sorted(shuffled[half:])


def start(instances: list[str], seed_rules: list[str], seed: int = 0) -> State:
    feedback, pareto_set = split_instances(instances, seed)
    return State(feedback=feedback, pareto_set=pareto_set, pool=[Candidate(id="c0", rules=clean_rules(seed_rules))])


def optimize(state: State, run: Runner, budget: int, path: Path, minibatch: int = 6, merge_every: int = 4, seed: int = 0,
             runs_per_case: int = 1, propose: Callable[[Candidate, list[ScoredRun]], list[str]] = reflect) -> State:
    """Run until `budget` conversations are spent. Resumable: `state` may come from State.load."""
    rng = random.Random(seed + state.iteration)
    cost = lambda n: n * runs_per_case  # noqa: E731
    seed_candidate = state.pool[0]
    if not seed_candidate.pareto:
        seed_candidate.pareto, _ = run(seed_candidate, state.pareto_set)
        state.rollouts += cost(len(state.pareto_set))
        state.save(path)

    while state.rollouts + cost(2 * minibatch + len(state.pareto_set)) <= budget:
        state.iteration += 1
        batch = rng.sample(state.feedback, min(minibatch, len(state.feedback)))
        front = pareto_front(state.pool)
        if state.iteration % merge_every == 0 and len(front) >= 2:
            a, b = rng.sample(front, 2)
            parent, rules, origin = a, merge(a, b), "merge"
            parent_rates, _ = run(parent, batch)
            state.rollouts += cost(len(batch))
        else:
            parent = sample_parent(state.pool, rng)
            parent_rates, scored = run(parent, batch)
            state.rollouts += cost(len(batch))
            failures = [s for s in scored if not s.passed]
            if not failures:
                state.log.append({"iteration": state.iteration, "parent": parent.id, "skipped": "no failures on minibatch"})
                state.save(path)
                continue
            rules, origin = propose(parent, failures), "mutation"
        child = Candidate(id=f"c{len(state.pool)}", rules=rules, parent=parent.id, origin=origin)
        child_rates, _ = run(child, batch)
        state.rollouts += cost(len(batch))
        entry = {"iteration": state.iteration, "parent": parent.id, "child": child.id, "origin": origin,
                 "minibatch": {"parent": sum(parent_rates.values()), "child": sum(child_rates.values())}}
        if sum(child_rates.values()) > sum(parent_rates.values()):
            child.pareto, _ = run(child, state.pareto_set)
            state.rollouts += cost(len(state.pareto_set))
            state.pool.append(child)
            entry["accepted"], entry["pareto_mean"] = True, child.mean
        else:
            entry["accepted"] = False
        state.log.append(entry)
        state.save(path)
    return state
