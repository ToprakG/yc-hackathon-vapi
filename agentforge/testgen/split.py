"""Train / held-out split, stratified by persona kind (adversary vs coverage)."""

from __future__ import annotations

import random
from collections import defaultdict

from agentforge.schemas import SPLIT_TAGS, Persona


def mode_tag(persona: Persona) -> str | None:
    return next((tag for tag in persona.tags if tag.startswith(("fm:", "path:"))), None)


def kind(persona: Persona) -> str:
    return next((tag for tag in ("adversary", "coverage") if tag in persona.tags), "other")


def split_personas(personas: list[Persona], heldout_frac: float = 0.4, seed: int = 0) -> list[Persona]:
    # Stratify by failure mode / path when it repeats, otherwise by kind (adversary vs coverage).
    mode_counts = defaultdict(int)
    for persona in personas:
        mode_counts[mode_tag(persona)] += 1
    groups: dict[str, list[int]] = defaultdict(list)
    for index, persona in enumerate(personas):
        tag = mode_tag(persona)
        groups[tag if tag and mode_counts[tag] >= 2 else kind(persona)].append(index)
    heldout: set[int] = set()
    rng = random.Random(seed)
    for key in sorted(groups):
        members = sorted(groups[key], key=lambda i: personas[i].name)
        rng.shuffle(members)
        count = round(len(members) * heldout_frac)
        if len(members) >= 2:
            count = min(max(count, 1), len(members) - 1)
        heldout.update(members[:count])
    result = []
    for index, persona in enumerate(personas):
        tags = [tag for tag in persona.tags if tag not in SPLIT_TAGS]
        tags.append("heldout" if index in heldout else "train")
        result.append(persona.model_copy(update={"tags": tags}))
    return result
