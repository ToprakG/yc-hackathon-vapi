"""Paired, per-case statistics for TEST_PLAN's decision rules.

Inputs are per-case pass counts: {case_name: (passed, runs)} for config A (current best) and B (candidate), run on the
same cases. Per-case difference = B rate - A rate. Ties (same rate, e.g. both 3/3 or both 0/3) drop out of both tests,
so dropping saturated cases only saves runs; it never changes the result.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from itertools import product

Counts = dict[str, tuple[int, int]]

ALPHA = 0.1


def sign_test(wins: int, losses: int) -> float:
    """Two-sided exact binomial sign test, ties excluded."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def wilcoxon(diffs: list[float]) -> float:
    """Two-sided Wilcoxon signed-rank p-value; zeros dropped, tied ranks averaged.
    Exact (enumerating sign flips) up to 16 non-zero differences, normal approximation above."""
    nz = [d for d in diffs if abs(d) > 1e-12]
    n = len(nz)
    if n == 0:
        return 1.0
    ranks = _ranks([abs(d) for d in nz])
    w_plus = sum(r for r, d in zip(ranks, nz) if d > 0)
    total = sum(ranks)
    observed = abs(w_plus - total / 2)
    if n <= 16:
        extreme = sum(1 for signs in product((0, 1), repeat=n)
                      if abs(sum(r for r, s in zip(ranks, signs) if s) - total / 2) >= observed - 1e-9)
        return extreme / 2**n
    var = sum(r * r for r in ranks) / 4
    z = observed / math.sqrt(var)
    return math.erfc(z / math.sqrt(2))


@dataclass
class Paired:
    n_cases: int
    wins: int  # cases where B > A
    losses: int
    ties: int
    mean_diff: float  # mean per-case pass-rate difference, B - A
    p_sign: float
    p_wilcoxon: float
    worse_cases: list[str] = field(default_factory=list)

    @property
    def p(self) -> float:
        """The p-value the rules use: Wilcoxon (more power on 0-3 counts); the sign test is reported alongside."""
        return self.p_wilcoxon

    def to_dict(self) -> dict:
        return {**asdict(self), "p": self.p}


def paired(a: Counts, b: Counts, cases: list[str] | None = None) -> Paired:
    names = [c for c in (cases or sorted(set(a) & set(b))) if c in a and c in b]
    diffs = {c: b[c][0] / max(1, b[c][1]) - a[c][0] / max(1, a[c][1]) for c in names}
    values = list(diffs.values())
    wins = sum(d > 1e-12 for d in values)
    losses = sum(d < -1e-12 for d in values)
    return Paired(
        n_cases=len(names), wins=wins, losses=losses, ties=len(names) - wins - losses,
        mean_diff=sum(values) / len(values) if values else 0.0,
        p_sign=sign_test(wins, losses), p_wilcoxon=wilcoxon(values),
        worse_cases=sorted(c for c, d in diffs.items() if d < -1e-12),
    )


def critical_veto(a: Counts, b: Counts, groups: dict[str, str], critical_groups: tuple[str, ...]) -> list[str]:
    """Reasons to block B. Hard rule: any critical case that A always passed and B always fails. Plan rule: a critical
    group that is worse with p < ALPHA in the paired test."""
    reasons = []
    for case, group in groups.items():
        if group in critical_groups and case in a and case in b:
            (pa, na), (pb, nb) = a[case], b[case]
            if na and nb and pa == na and pb == 0:
                reasons.append(f"{case}: {pa}/{na} -> {pb}/{nb}")
    for group in critical_groups:
        members = [c for c, g in groups.items() if g == group]
        result = paired(a, b, members)
        if result.n_cases and result.mean_diff < 0 and result.p < ALPHA:
            reasons.append(f"group {group} worse (p={result.p:.3f}, mean {result.mean_diff:+.2f})")
    return reasons


def verdict(result: Paired, veto: list[str]) -> str:
    """'win' | 'loss' | 'equal' for one paired comparison (before the fresh re-run that a win still needs)."""
    if veto:
        return "loss"
    if result.p < ALPHA:
        return "win" if result.mean_diff > 0 else "loss"
    return "equal"


def counts_from_scored(scored) -> Counts:
    counts: dict[str, list[int]] = {}
    for item in scored:
        entry = counts.setdefault(item.run.persona_name, [0, 0])
        entry[0] += int(item.passed)
        entry[1] += 1
    return {k: (v[0], v[1]) for k, v in counts.items()}


def merge(*many: Counts) -> Counts:
    out: dict[str, list[int]] = {}
    for counts in many:
        for case, (p, n) in counts.items():
            entry = out.setdefault(case, [0, 0])
            entry[0] += p
            entry[1] += n
    return {k: (v[0], v[1]) for k, v in out.items()}
