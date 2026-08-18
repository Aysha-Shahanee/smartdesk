"""Significance tests and multiplicity control.

The engine could measure an effect long before it could say whether the effect
was real. A Theil–Sen slope with no confidence statement is a direction, not a
trend; a Spearman rho of 0.34 over seven points is what noise looks like about
a fifth of the time. This module supplies the missing half, and then the gate
that stops the whole battery from manufacturing findings by sheer volume.

Multiplicity is the part that is easy to miss and hardest to defend without.
Seventy-four rules re-evaluated daily is a lot of chances to be surprised: at
alpha = 0.05, twenty independent true nulls give roughly a 64% chance that at
least one of them looks significant. A system that publishes each claim the
moment it clears 0.05 will therefore publish something almost every day, and
almost all of it will be noise wearing a p-value. Benjamini–Hochberg is the
standard, cheap answer — rank the day's p-values, keep only those that clear a
threshold that rises with rank — and it controls the false discovery rate
rather than merely flagging the problem.

Everything here is written out rather than imported. That is the same choice
``percentile``, ``theil_sen_slope`` and ``spearman`` already made next door: the
functions are small, the inputs are tiny, and a statistics stack is a large
dependency to add for four closed-form expressions. It also keeps the tests
honest, since each function can be checked against published values rather than
against another implementation of the same idea.

References: Mann (1945) and Kendall (1975) for the trend test; Benjamini &
Hochberg (1995) JRSS-B 57(1) 289-300 for the FDR procedure; Numerical Recipes
for the continued-fraction expansion of the incomplete beta.
"""

from __future__ import annotations

import math

# --------------------------------------------------------------------- #
# Distributions                                                          #
# --------------------------------------------------------------------- #

def norm_sf(z: float) -> float:
    """Upper tail of the standard normal, ``P(Z > z)``.

    ``erf`` is in the standard library and exact enough for this: the tail
    probabilities here are read at two decimal places and compared against a
    threshold, never reported to the user as a figure.
    """
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta, by modified Lentz."""
    max_iter, eps, tiny = 300, 3.0e-16, 1.0e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def betai(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta ``I_x(a, b)``."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def student_t_p(t: float, df: int) -> float:
    """Two-sided p for a t statistic.

    The normal approximation is not good enough at this scale — with six or
    seven observations, which is the usual size of a weekly comparison here,
    it understates the tail and would let through claims a proper t test
    rejects.
    """
    if df <= 0:
        return 1.0
    if not math.isfinite(t):
        return 0.0
    return betai(df / 2.0, 0.5, df / (df + t * t))


# --------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------- #

def mann_kendall(values: list[float]) -> tuple[int, float, float]:
    """Trend test companion to Theil–Sen. Returns ``(S, z, p)``.

    Theil–Sen gives the slope; this gives the answer to "could that direction
    have arisen from an unordered sample?". Rank-based and therefore untroubled
    by the same non-normality that motivated the slope estimator, and it shares
    the estimator's tolerance of one outlying week.

    Ties are corrected for in the variance because they are common here: two
    weeks with identical rounded deep-work minutes is an ordinary event, and
    ignoring it inflates the variance and makes the test conservative.
    """
    n = len(values)
    if n < 3:
        return 0, 0.0, 1.0

    s = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            diff = values[j] - values[i]
            s += (diff > 0) - (diff < 0)

    counts: dict[float, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    tie_term = sum(c * (c - 1) * (2 * c + 5) for c in counts.values() if c > 1)
    variance = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0
    if variance <= 0:
        return s, 0.0, 1.0

    # The continuity correction: S is integer-valued, and without the -1/+1
    # the normal approximation is anti-conservative at these sample sizes.
    if s > 0:
        z = (s - 1) / math.sqrt(variance)
    elif s < 0:
        z = (s + 1) / math.sqrt(variance)
    else:
        z = 0.0
    return s, z, min(1.0, 2.0 * norm_sf(abs(z)))


def spearman_p(rho: float, n: int) -> float:
    """Two-sided p for a Spearman correlation.

    The |rho| >= 0.3 floor the weekly rules already apply is an effect-size
    threshold, and answers a different question from this one. A correlation
    can be large and unsupported — with n = 6, rho = 0.6 is not significant —
    so both bars have to be cleared before the association is worth printing.
    """
    if n < 3:
        return 1.0
    if abs(rho) >= 1.0:
        return 0.0
    t = rho * math.sqrt((n - 2) / (1.0 - rho * rho))
    return student_t_p(t, n - 2)


def mann_whitney_u(
    first: list[float], second: list[float]
) -> tuple[float, float]:
    """Two-sample rank test. Returns ``(U, two-sided p)``.

    The right companion for the unpaired comparisons: this month against last,
    this week's learning share against the weeks before it, the days after a
    habit changed against the days before. Those are two independent samples of
    daily values, and a t test on them assumes a normality daily focus data
    does not have — one holiday week is enough to move a mean and not enough to
    move a rank.

    Distinct from :func:`sign_test`, which is for *paired* observations. Using
    the paired test here would be wrong twice over: the samples are different
    sizes, and nothing links the third day of one month to the third of the
    next.

    Normal approximation with a tie correction and a continuity correction.
    Exact enumeration is unnecessary above about eight per arm, and the callers
    already refuse to speak below ten days.
    """
    n1, n2 = len(first), len(second)
    if n1 == 0 or n2 == 0:
        return 0.0, 1.0

    combined = sorted([(v, 0) for v in first] + [(v, 1) for v in second])
    ranks = [0.0] * len(combined)
    index = 0
    tie_term = 0.0
    while index < len(combined):
        stop = index
        while stop + 1 < len(combined) and combined[stop + 1][0] == combined[index][0]:
            stop += 1
        # Tied observations share the average of the ranks they span.
        average = (index + stop + 2) / 2.0
        for position in range(index, stop + 1):
            ranks[position] = average
        group = stop - index + 1
        if group > 1:
            tie_term += group ** 3 - group
        index = stop + 1

    rank_sum_first = sum(
        rank for rank, (_v, origin) in zip(ranks, combined) if origin == 0
    )
    u1 = rank_sum_first - n1 * (n1 + 1) / 2.0
    u2 = n1 * n2 - u1
    u = min(u1, u2)

    total = n1 + n2
    mean = n1 * n2 / 2.0
    variance = (n1 * n2 / 12.0) * (
        (total + 1) - tie_term / (total * (total - 1))
    ) if total > 1 else 0.0
    if variance <= 0:
        return u, 1.0
    z = (abs(u - mean) - 0.5) / math.sqrt(variance)
    return u, min(1.0, 2.0 * norm_sf(max(0.0, z)))


def sign_test(differences: list[float]) -> float:
    """Exact two-sided p for paired differences, under median difference zero.

    The right test for the matched-pair rules: it assumes nothing about the
    shape of the differences, only that under the null a positive one is as
    likely as a negative. Exact rather than approximated because the pair
    counts here are small enough for :func:`math.comb` to be instant, and the
    normal approximation is poor below about twenty pairs.

    Zero differences are discarded, which is the standard treatment — a pair
    that moved in neither direction is evidence for neither.
    """
    positive = sum(1 for d in differences if d > 0)
    negative = sum(1 for d in differences if d < 0)
    n = positive + negative
    if n == 0:
        return 1.0
    smaller = min(positive, negative)
    tail = sum(math.comb(n, k) for k in range(smaller + 1)) / (2.0 ** n)
    return min(1.0, 2.0 * tail)


# --------------------------------------------------------------------- #
# Multiplicity
# --------------------------------------------------------------------- #

def benjamini_hochberg(p_values: list[float], q: float) -> list[bool]:
    """Which of a day's claims survive false-discovery-rate control at ``q``.

    Sort the p-values ascending, find the largest rank k where
    ``p_(k) <= q*k/m``, and keep every claim at or below that rank. Keeping
    everything below the largest surviving rank — rather than each p-value that
    individually clears its own bar — is the step-up part of the procedure, and
    skipping it makes the test both wrong and needlessly strict.

    Returns a mask in the caller's original order. An empty input gives an
    empty mask; a single test is still subject to the procedure, where it
    reduces to comparing against ``q``.
    """
    m = len(p_values)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: p_values[i])
    highest_rank = 0
    for rank, index in enumerate(order, start=1):
        if p_values[index] <= q * rank / m:
            highest_rank = rank
    survives = [False] * m
    for rank, index in enumerate(order, start=1):
        if rank <= highest_rank:
            survives[index] = True
    return survives


# --------------------------------------------------------------------- #
# Calibration
# --------------------------------------------------------------------- #

def expected_calibration_error(
    probabilities: list[float],
    outcomes: list[bool],
    bins: int = 10,
) -> float | None:
    """Weighted gap between predicted probability and observed frequency.

    A logistic model's output is not automatically a probability. It can rank
    perfectly and still be systematically overconfident, and the ranker's
    output is not merely ranked — it is mapped linearly onto a multiplier band,
    so a score that reads 0.8 when the real acceptance rate is 0.5 moves cards
    by more than the evidence supports.

    ECE bins the predictions, compares the mean prediction in each bin with the
    fraction that actually came true, and averages those gaps weighted by bin
    population (Niculescu-Mizil & Caruana 2005). Zero is perfect; 0.1 means the
    stated confidence is off by ten points on average.

    ``None`` when there is nothing to measure. Bins are equal-width rather than
    equal-mass because the question is "is a stated 0.9 really 0.9", which is
    about the value, not about the rank.
    """
    if not probabilities or len(probabilities) != len(outcomes):
        return None
    total = len(probabilities)
    error = 0.0
    for index in range(bins):
        low = index / bins
        high = (index + 1) / bins
        members = [
            (p, o) for p, o in zip(probabilities, outcomes)
            # The top bin owns its upper edge, or a prediction of exactly 1.0
            # would fall outside every bin and be silently dropped.
            if (low <= p < high) or (index == bins - 1 and p == 1.0)
        ]
        if not members:
            continue
        mean_predicted = sum(p for p, _ in members) / len(members)
        observed = sum(1 for _, o in members if o) / len(members)
        error += (len(members) / total) * abs(mean_predicted - observed)
    return error


def reliability_curve(
    probabilities: list[float],
    outcomes: list[bool],
    bins: int = 10,
) -> list[dict]:
    """Per-bin predicted-versus-observed, for a reliability diagram.

    The picture behind the ECE figure: a perfectly calibrated model traces the
    diagonal. Returned as data rather than a plot so the caller can render it
    or serialise it.
    """
    curve: list[dict] = []
    if not probabilities or len(probabilities) != len(outcomes):
        return curve
    for index in range(bins):
        low = index / bins
        high = (index + 1) / bins
        members = [
            (p, o) for p, o in zip(probabilities, outcomes)
            if (low <= p < high) or (index == bins - 1 and p == 1.0)
        ]
        if not members:
            continue
        curve.append({
            "bin_low": low,
            "bin_high": high,
            "count": len(members),
            "mean_predicted": sum(p for p, _ in members) / len(members),
            "observed_rate": sum(1 for _, o in members if o) / len(members),
        })
    return curve


class PlattScaling:
    """A one-dimensional logistic fit that turns a score into a probability.

    Platt scaling rather than isotonic regression, and the reason is sample
    size: isotonic is non-parametric and fits a free-form monotone step
    function, which at the tens-of-events scale this ranker trains on will
    reproduce its calibration set rather than generalise from it. Platt has two
    parameters, which is about what a hundred observations can support.

    Fitted by Newton-Raphson on the two parameters. Deliberately not a second
    scikit-learn ``LogisticRegression``: this is a scalar fit run over a few
    dozen points, and expressing it directly keeps the gradient visible and
    the failure modes local.
    """

    def __init__(self) -> None:
        self.a: float = 1.0
        self.b: float = 0.0
        self.fitted: bool = False

    def fit(
        self,
        scores: list[float],
        outcomes: list[bool],
        iterations: int = 100,
    ) -> bool:
        """Fit ``sigmoid(a * score + b)``. False when the data cannot support it."""
        if len(scores) < 10 or len(scores) != len(outcomes):
            return False
        if len({bool(o) for o in outcomes}) < 2:
            # One class only: any monotone map is equally consistent, and the
            # fit would run off to infinity chasing a perfect separation.
            return False

        a, b = 1.0, 0.0
        targets = [1.0 if o else 0.0 for o in outcomes]
        for _ in range(iterations):
            grad_a = grad_b = 0.0
            h_aa = h_ab = h_bb = 0.0
            for score, target in zip(scores, targets):
                z = a * score + b
                p = 1.0 / (1.0 + math.exp(-max(-500.0, min(500.0, z))))
                residual = p - target
                weight = p * (1.0 - p)
                grad_a += residual * score
                grad_b += residual
                h_aa += weight * score * score
                h_ab += weight * score
                h_bb += weight
            # Ridge term on the diagonal: with separable data the Hessian goes
            # singular and the step becomes infinite.
            h_aa += 1e-9
            h_bb += 1e-9
            det = h_aa * h_bb - h_ab * h_ab
            if abs(det) < 1e-12:
                break
            step_a = (h_bb * grad_a - h_ab * grad_b) / det
            step_b = (h_aa * grad_b - h_ab * grad_a) / det
            a -= step_a
            b -= step_b
            if abs(step_a) < 1e-9 and abs(step_b) < 1e-9:
                break

        if not (math.isfinite(a) and math.isfinite(b)):
            return False
        self.a, self.b, self.fitted = a, b, True
        return True

    def transform(self, score: float) -> float:
        """Calibrated probability. The identity-ish default when unfitted."""
        z = self.a * score + self.b
        return 1.0 / (1.0 + math.exp(-max(-500.0, min(500.0, z))))


# --------------------------------------------------------------------- #
# Change detection
# --------------------------------------------------------------------- #

def cusum_change_point(
    values: list[float],
    threshold: float = 1.0,
) -> tuple[int | None, float]:
    """Where a series most likely shifted level. Returns ``(index, strength)``.

    Comparing three consecutive weekly medians against a prior median — the
    approach this replaces — asks a fixed question at a fixed lag: it can only
    see a change that lasted exactly three weeks and moved by exactly one
    spread. A change that took four weeks, or moved by two thirds of a spread
    and stayed, is invisible to it, and the "three" and the "one" are both
    numbers nobody chose for a reason.

    CUSUM (Page 1954) asks the more useful question — is there a point in this
    series after which the mean is different — and answers it at whatever lag
    the data actually shows. The statistic is the cumulative sum of deviations
    from the overall mean; its largest absolute excursion locates the most
    likely split, and the size of that excursion, normalised by the series
    spread, says how convincing it is.

    The returned index is the first element of the *after* segment, so
    ``values[:index]`` and ``values[index:]`` are the two levels. The CUSUM
    extremum falls on the last element before the shift, so this is that
    position plus one — without the offset the split carries one post-change
    point into the pre-change mean and understates the size of the jump.

    ``strength`` is in units of the series standard deviation, so ``threshold``
    is comparable across metrics. ``(None, 0.0)`` when the series is too short
    or perfectly flat, which is the honest answer rather than index zero.
    """
    n = len(values)
    if n < 4:
        return None, 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    if variance <= 0:
        return None, 0.0
    sigma = math.sqrt(variance)

    cumulative = 0.0
    best_index, best_value = None, 0.0
    # The endpoints are excluded: a "change" at index 0 or n-1 splits the series
    # into one point and the rest, which no amount of evidence can support.
    for index, value in enumerate(values[:-1]):
        cumulative += value - mean
        if index == 0:
            continue
        if abs(cumulative) > abs(best_value):
            best_index, best_value = index, cumulative

    if best_index is None:
        return None, 0.0
    strength = abs(best_value) / (sigma * math.sqrt(n))
    split = best_index + 1
    return (split, strength) if strength >= threshold else (None, strength)


def level_shift(
    values: list[float],
    threshold: float = 1.0,
) -> dict | None:
    """A detected level change, with the two levels and a significance test.

    CUSUM locates the split; the Mann-Whitney-style comparison is left to the
    caller's own gate. What is returned here is the description: where, in which
    direction, and how far the two halves sit apart in spread units.

    ``None`` when nothing convincing was found, so a caller can treat the
    absence as "no change" rather than having to interpret a weak result.
    """
    index, strength = cusum_change_point(values, threshold)
    if index is None:
        return None
    before, after = values[:index], values[index:]
    if not before or not after:
        return None
    mean_before = sum(before) / len(before)
    mean_after = sum(after) / len(after)
    pooled = math.sqrt(
        (
            sum((v - mean_before) ** 2 for v in before)
            + sum((v - mean_after) ** 2 for v in after)
        ) / max(1, len(values) - 2)
    )
    if pooled <= 0:
        # Both halves perfectly constant. The within-group spread really is
        # zero, so a standardised effect is undefined rather than absent —
        # reporting 0.0 here would describe the cleanest possible shift as no
        # shift at all. The whole-series spread is the sensible denominator,
        # and it is non-zero or CUSUM would not have returned an index.
        overall = sum(values) / len(values)
        pooled = math.sqrt(
            sum((v - overall) ** 2 for v in values) / len(values)
        )
    return {
        "index": index,
        "strength": strength,
        "before": mean_before,
        "after": mean_after,
        "direction": "up" if mean_after > mean_before else "down",
        "effect_sigma": (
            abs(mean_after - mean_before) / pooled if pooled > 0 else 0.0
        ),
        "n_before": len(before),
        "n_after": len(after),
    }


def deseasonalise_weekday(
    values: list[float],
    weekdays: list[int],
) -> list[float]:
    """Remove day-of-week effect by subtracting each weekday's own median.

    Daily focus data has a strong weekly cycle, which violates the
    independence the percentile and z-score claims assume: a run of low
    Saturdays is not a downward trend, and a trend test fed the raw series will
    keep finding one. Subtracting each weekday's median leaves a remainder
    where a genuine shift is visible and the weekly rhythm is not.

    A cheap stand-in for full STL decomposition, and the right size for the
    data — STL over thirty points estimates a seasonal component from four
    observations per phase. Returns the input unchanged when the two lists
    disagree in length, since a mismatch means the pairing is unknown.
    """
    if len(values) != len(weekdays) or not values:
        return list(values)
    groups: dict[int, list[float]] = {}
    for value, day in zip(values, weekdays):
        groups.setdefault(day, []).append(value)
    medians = {
        day: sorted(group)[len(group) // 2] for day, group in groups.items()
    }
    return [value - medians[day] for value, day in zip(values, weekdays)]
