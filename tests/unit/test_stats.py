"""Gate statistics (design 005 §6.1)."""

from __future__ import annotations

import itertools
import math

import pytest

from flycolony.engine.stats import fisher_one_sided, mannwhitney_one_sided


def test_fisher_matches_the_hypergeometric_tail():
    # Lady tasting tea: 3 of 4 vs 1 of 4 → P = 17/70.
    assert fisher_one_sided(3, 4, 1, 4, "greater") == pytest.approx(17 / 70)
    assert fisher_one_sided(1, 4, 3, 4, "less") == pytest.approx(17 / 70)
    assert fisher_one_sided(2, 4, 2, 4, "greater") == pytest.approx(53 / 70)
    # A gate-sized clear effect is far below α; no effect is not.
    assert fisher_one_sided(40, 50, 5, 50, "greater") < 1e-10
    assert fisher_one_sided(10, 50, 10, 50, "greater") > 0.4
    with pytest.raises(ValueError):
        fisher_one_sided(1, 2, 1, 2, "two-sided")


def _exact_mw_greater(x, y) -> float:
    pooled = [*x, *y]
    n1 = len(x)

    def u(sample):
        return sum((a > b) + 0.5 * (a == b) for a in sample[0] for b in sample[1])

    observed = u((x, y))
    count = total = 0
    for idx in itertools.combinations(range(len(pooled)), n1):
        s = set(idx)
        a = [pooled[i] for i in idx]
        b = [pooled[i] for i in range(len(pooled)) if i not in s]
        total += 1
        count += u((a, b)) >= observed
    return count / total


def test_mannwhitney_approximation_tracks_the_exact_test():
    x = [3.1, 4.0, 5.2, 6.8, 7.7, 8.0, 9.4, 2.2]
    y = [1.0, 2.5, 2.9, 3.3, 4.4, 1.7, 0.6, 5.0]
    exact = _exact_mw_greater(x, y)
    assert mannwhitney_one_sided(x, y, "greater") == pytest.approx(exact, abs=0.01)
    # With ties (many zeros, as in sleep minutes).
    x2 = [0, 0, 5, 10, 12, 0, 8, 15]
    y2 = [0, 0, 0, 0, 3, 0, 0, 1]
    assert mannwhitney_one_sided(x2, y2, "greater") == pytest.approx(
        _exact_mw_greater(x2, y2), abs=0.02
    )
    assert mannwhitney_one_sided(y, x, "less") == pytest.approx(
        mannwhitney_one_sided(x, y, "greater")
    )


def test_mannwhitney_edge_cases():
    assert mannwhitney_one_sided([0.0] * 5, [0.0] * 5, "greater") == 1.0
    big = mannwhitney_one_sided(list(range(50, 100)), list(range(50)), "greater")
    assert big < 1e-15 and not math.isnan(big)
    with pytest.raises(ValueError):
        mannwhitney_one_sided([], [1.0], "greater")
