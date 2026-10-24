"""One-sided tests for the emergence gates (design 005 §6.1): no SciPy dependency.

- Fisher's exact test on a 2×2 table, from the hypergeometric distribution (exact).
- Mann–Whitney U, normal approximation with tie and continuity corrections (n ≥ 50 per group
  in the gates, where the approximation is standard).
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def fisher_one_sided(k1: int, n1: int, k2: int, n2: int, alternative: str) -> float:
    """P-value that group 1's success rate k1/n1 is greater ('greater') or less ('less') than
    group 2's, conditional on the margins."""
    if alternative not in ("greater", "less"):
        raise ValueError(f"alternative must be 'greater' or 'less', not {alternative!r}")
    k = k1 + k2
    n = n1 + n2
    lo, hi = max(0, k - n2), min(k, n1)
    total = math.comb(n, k)

    def pmf(x: int) -> float:
        return math.comb(n1, x) * math.comb(n2, k - x) / total

    xs = range(k1, hi + 1) if alternative == "greater" else range(lo, k1 + 1)
    return min(1.0, sum(pmf(x) for x in xs))


def _ranks(values: Sequence[float]) -> tuple[list[float], float]:
    """Mid-ranks (1-based) and the tie term Σ(t³ − t)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    ties = 0.0
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        mid = (i + j) / 2 + 1
        for m in range(i, j + 1):
            ranks[order[m]] = mid
        t = j - i + 1
        ties += t**3 - t
        i = j + 1
    return ranks, ties


def mannwhitney_one_sided(x: Sequence[float], y: Sequence[float], alternative: str) -> float:
    """P-value that x tends to be greater ('greater') or less ('less') than y."""
    if alternative not in ("greater", "less"):
        raise ValueError(f"alternative must be 'greater' or 'less', not {alternative!r}")
    n1, n2 = len(x), len(y)
    if n1 == 0 or n2 == 0:
        raise ValueError("both groups need at least one value")
    ranks, ties = _ranks([*x, *y])
    u1 = sum(ranks[:n1]) - n1 * (n1 + 1) / 2
    mu = n1 * n2 / 2
    n = n1 + n2
    var = n1 * n2 / 12 * ((n + 1) - ties / (n * (n - 1)))
    if var <= 0:  # every value tied: no evidence either way
        return 1.0
    d = u1 - mu if alternative == "greater" else mu - u1
    z = (d - 0.5) / math.sqrt(var)  # continuity correction
    return 0.5 * math.erfc(z / math.sqrt(2))
