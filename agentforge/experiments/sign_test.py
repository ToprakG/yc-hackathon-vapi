"""Paired sign test on per-case pass counts from 0 to 3. No aggregate standard-deviation rule."""

from __future__ import annotations

import math
from dataclasses import dataclass

CRITICAL_TAGS = ("third_party", "verification", "promise_to_pay")
WIN_P = 0.1


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    passes: int
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.passes < 0 or self.passes > 3:
            raise ValueError(f"{self.case_id} passes must be 0 to 3, got {self.passes}")


def sign_p(diffs: list[int]) -> tuple[float, int]:
    """Two-sided sign-test p-value and the positive-minus-negative count."""
    nonzero = [diff for diff in diffs if diff != 0]
    n = len(nonzero)
    positive = sum(1 for diff in nonzero if diff > 0)
    return _two_sided(positive, n), positive - (n - positive)


def is_drop(candidate: list[CaseScore], best: list[CaseScore]) -> bool:
    """Worsening at p < 0.1. One failed case is not enough."""
    p_value, direction = sign_p(_diffs(candidate, best))
    return p_value < WIN_P and direction < 0


def is_win(candidate: list[CaseScore], best: list[CaseScore], repeat: list[CaseScore]) -> bool:
    """p < 0.1, the same direction on a second run, and no critical tag drops."""
    p_value, direction = sign_p(_diffs(candidate, best))
    if not (p_value < WIN_P and direction > 0):
        return False
    repeat_p, repeat_direction = sign_p(_diffs(repeat, best))
    if not (repeat_p < WIN_P and repeat_direction > 0):
        return False
    for tag in CRITICAL_TAGS:
        tagged_best = _tagged(best, tag)
        if not tagged_best:
            continue
        if is_drop(_tagged(candidate, tag), tagged_best):
            return False
        if is_drop(_tagged(repeat, tag), tagged_best):
            return False
    return True


def _diffs(candidate: list[CaseScore], best: list[CaseScore]) -> list[int]:
    best_by_id = {item.case_id: item.passes for item in best}
    missing = [item.case_id for item in candidate if item.case_id not in best_by_id]
    if missing:
        raise ValueError(f"candidate cases missing from the current best: {missing}")
    return [item.passes - best_by_id[item.case_id] for item in candidate]


def _tagged(scores: list[CaseScore], tag: str) -> list[CaseScore]:
    return [item for item in scores if tag in item.tags]


def _two_sided(positive: int, n: int) -> float:
    if n == 0:
        return 1.0
    probs = [math.comb(n, i) / 2**n for i in range(n + 1)]
    cutoff = probs[positive]
    return min(1.0, sum(prob for prob in probs if prob <= cutoff + 1e-12))
