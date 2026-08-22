"""Synthetic days with known patterns, for measuring rule accuracy.

The standing objection to every rule in this engine is that nothing verifies
it. The user's feedback tells us whether a card was *wanted*, which is not the
same question as whether it was *right*: a user may dismiss a true finding and
apply a false one. Without a case where the answer is known in advance there is
no way to say a rule detects what it claims to detect.

This module manufactures those cases. It generates feature snapshots in which
a condition has been deliberately planted or deliberately withheld, runs the
real rules against them, and counts hits and misses. Because the planting is
done here, the ground truth is exact — which turns "does DY-03 detect a
fragmented day?" from an opinion into a precision and recall figure.

What it does not do is simulate a person. Generating activity segments,
sessions and calendar rows realistic enough to drive the whole feature pipeline
would be a second system with its own bugs, and a rule that passed against it
would only have proved the generator agrees with the rule. Injecting at the
feature boundary keeps the thing under test — the rule predicate — honest,
and keeps the generator too simple to be wrong in an interesting way. The
limitation is real and worth stating: this validates rule *logic*, not feature
extraction.

Deterministic by construction. Every scenario is seeded, so a figure quoted
from a run can be reproduced from the same seed.
"""

from __future__ import annotations

import logging
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime

from app.services.recommendations.baselines import MIN_SAMPLES
from app.services.recommendations.registry import BY_ID
from app.services.recommendations.types import FeatureContext

logger = logging.getLogger("smartdesk.recommendations.simulation")

#: Seed for every generator here. Fixed so a reported precision is a fact
#: about the rule rather than about which afternoon it was measured on.
DEFAULT_SEED = 20260818

#: A fixed moment for every scenario. Rules that read the clock must see the
#: same one each run, or a suite passing at 09:00 could fail at midnight.
SYNTHETIC_AS_OF = datetime(2026, 8, 14, 15, 0, 0)

#: Days of history the synthetic user is presumed to have. Comfortably past
#: MIN_SAMPLES so that requirement gating never silently causes a "miss" that
#: is really a gate.
SYNTHETIC_HISTORY_DAYS = 45


@dataclass
class Scenario:
    """One synthetic day, and whether the rule under test should fire on it."""

    name: str
    features: dict[str, float]
    should_fire: bool


@dataclass
class RuleAccuracy:
    """How a rule performed against known ground truth."""

    rule_id: str
    positives: int = 0
    negatives: int = 0
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    true_negatives: int = 0
    #: Scenarios where the rule could not run at all because a feature it
    #: declares was absent. Counted separately: a gated rule is a generator
    #: that did not supply enough, not a rule that got it wrong.
    gated: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float | None:
        fired = self.true_positives + self.false_positives
        return self.true_positives / fired if fired else None

    @property
    def recall(self) -> float | None:
        return (
            self.true_positives / self.positives if self.positives else None
        )

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None or p + r == 0:
            return None
        return 2 * p * r / (p + r)

    def as_dict(self) -> dict:
        payload = asdict(self)
        payload.update(
            precision=self.precision, recall=self.recall, f1=self.f1
        )
        return payload


def _baseline(metric: str, median: float, sigma: float, n: int = 30) -> dict:
    """The flattened baseline keys a rule reads for one metric."""
    mad = sigma / 1.4826
    return {
        f"baseline.{metric}.p10": median - 1.6 * sigma,
        f"baseline.{metric}.p25": median - 0.67 * sigma,
        f"baseline.{metric}.p50": median,
        f"baseline.{metric}.p75": median + 0.67 * sigma,
        f"baseline.{metric}.p90": median + 1.28 * sigma,
        f"baseline.{metric}.mad": mad,
        f"baseline.{metric}.sigma": sigma,
        f"baseline.{metric}.n": float(n),
    }


def deviation_scenarios(
    rule_id: str,
    metric: str,
    feature_key: str,
    median: float,
    sigma: float,
    extra: dict[str, float] | None = None,
    count: int = 40,
    seed: int = DEFAULT_SEED,
) -> list[Scenario]:
    """Days above and below a rule's threshold, labelled with the truth.

    Half the days are drawn from the ordinary distribution — the rule should
    stay quiet — and half are planted well beyond the bar it declares, where it
    should fire. The planted days sit at 2-4 sigma rather than just over the
    line, because a scenario a hair past the threshold tests floating-point
    arithmetic rather than detection, and would report as a rule failure when
    it is really a tie.
    """
    rng = random.Random(seed)
    scenarios: list[Scenario] = []
    for index in range(count):
        planted = index % 2 == 0
        if planted:
            value = median + sigma * rng.uniform(2.0, 4.0)
        else:
            value = median + sigma * rng.uniform(-0.4, 0.4)
        features = {feature_key: value}
        features.update(_baseline(metric, median, sigma))
        features.update(extra or {})
        scenarios.append(Scenario(
            name=f"{rule_id}/{'planted' if planted else 'ordinary'}/{index}",
            features=features,
            should_fire=planted,
        ))
    return scenarios


def measure(rule_id: str, scenarios: list[Scenario]) -> RuleAccuracy:
    """Run one rule against labelled scenarios and score it.

    A rule that raises is recorded rather than allowed to abort the run: an
    exception is a finding about the rule, and losing the other thirty-nine
    scenarios to it would hide more than it reveals.
    """
    spec = BY_ID.get(rule_id)
    result = RuleAccuracy(rule_id=rule_id)
    if spec is None:
        result.errors.append(f"unknown rule {rule_id}")
        return result

    for scenario in scenarios:
        ctx = FeatureContext(
            dict(scenario.features),
            as_of=SYNTHETIC_AS_OF,
            user_id="synthetic",
            days_of_history=SYNTHETIC_HISTORY_DAYS,
        )
        if scenario.should_fire:
            result.positives += 1
        else:
            result.negatives += 1

        if spec.gated(ctx):
            result.gated += 1
            continue
        try:
            fired = spec.fn(ctx) is not None
        except Exception as exc:
            result.errors.append(f"{scenario.name}: {exc}")
            continue

        if scenario.should_fire and fired:
            result.true_positives += 1
        elif scenario.should_fire and not fired:
            result.false_negatives += 1
        elif not scenario.should_fire and fired:
            result.false_positives += 1
        else:
            result.true_negatives += 1
    return result


#: The rules this module can generate ground truth for, and how.
#:
#: Deliberately a short list rather than all 74. A scenario is only ground
#: truth if the planted condition really is the condition the rule claims to
#: detect; inventing one for a rule whose trigger is a calendar shape or an
#: IDE session count would be asserting the rule's own logic back at it. These
#: are the threshold-on-a-baseline rules, where the planted value and the
#: declared bar are the same quantity.
DEVIATION_RULES: dict[str, dict] = {
    # DY-04, fragmentation: activities per active hour against its baseline.
    "DY-04": {
        "metric": "frag_index",
        "feature_key": "frag_index",
        "median": 6.0,
        "sigma": 2.0,
        "extra": {"segment_count": 80.0},
    },
    # DY-06, distraction share of the day.
    "DY-06": {
        "metric": "distraction_share",
        "feature_key": "distraction_share",
        "median": 0.15,
        "sigma": 0.05,
        "extra": {"distraction_min": 90.0},
    },
    # DY-07, idle share.
    "DY-07": {
        "metric": "idle_share",
        "feature_key": "idle_share",
        "median": 0.20,
        "sigma": 0.06,
        "extra": {"idle_min": 120.0},
    },
    # DY-03 is two-sided — it fires on an unusually good day as well as a bad
    # one — so the "ordinary" arm is the only clean negative and the planted
    # arm tests detection upward.
    "DY-03": {
        "metric": "deep_work_min",
        "feature_key": "deep_work_min",
        "median": 120.0,
        "sigma": 35.0,
    },
}


def sensitivity_sweep(
    rule_id: str,
    metric: str,
    feature_key: str,
    median: float,
    sigma: float,
    extra: dict[str, float] | None = None,
    steps: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0),
    per_step: int = 20,
    seed: int = DEFAULT_SEED,
) -> dict[float, float]:
    """Detection rate as the planted deviation grows. Returns {sigmas: rate}.

    The pass/fail suite above plants deviations at two to four sigma against a
    bar of two thirds of one, so every rule scores perfectly and the number
    means little beyond "the logic is not inverted". This is the more useful
    measurement: it walks the deviation up from nothing and reports where the
    rule actually starts firing.

    That answers the "magic numbers" objection directly. A threshold nobody
    can justify is a weakness; the same threshold with a curve showing what it
    does to the detection rate is a design decision. It is also how a
    threshold gets tuned deliberately rather than by feel.
    """
    rates: dict[float, float] = {}
    spec = BY_ID.get(rule_id)
    if spec is None:
        return rates
    for step in steps:
        rng = random.Random(seed + int(step * 1000))
        fired = 0
        for _ in range(per_step):
            value = median + sigma * step * rng.uniform(0.9, 1.1)
            features = {feature_key: value}
            features.update(_baseline(metric, median, sigma))
            features.update(extra or {})
            ctx = FeatureContext(
                features, as_of=SYNTHETIC_AS_OF, user_id="synthetic",
                days_of_history=SYNTHETIC_HISTORY_DAYS,
            )
            if spec.gated(ctx):
                continue
            try:
                if spec.fn(ctx) is not None:
                    fired += 1
            except Exception:
                continue
        rates[step] = fired / per_step
    return rates


def run_sweeps(seed: int = DEFAULT_SEED) -> dict[str, dict[float, float]]:
    """Sensitivity curve for every rule with ground truth."""
    return {
        rule_id: sensitivity_sweep(
            rule_id,
            metric=spec["metric"],
            feature_key=spec["feature_key"],
            median=spec["median"],
            sigma=spec["sigma"],
            extra=spec.get("extra"),
            seed=seed,
        )
        for rule_id, spec in DEVIATION_RULES.items()
    }


def run_suite(seed: int = DEFAULT_SEED, count: int = 40) -> dict[str, RuleAccuracy]:
    """Measure every rule the module has ground truth for."""
    results: dict[str, RuleAccuracy] = {}
    for rule_id, spec in DEVIATION_RULES.items():
        results[rule_id] = measure(
            rule_id,
            deviation_scenarios(
                rule_id,
                metric=spec["metric"],
                feature_key=spec["feature_key"],
                median=spec["median"],
                sigma=spec["sigma"],
                extra=spec.get("extra"),
                count=count,
                seed=seed,
            ),
        )
    return results


def summarise(results: dict[str, RuleAccuracy]) -> dict:
    """Suite-level totals, for a single headline figure."""
    tp = sum(r.true_positives for r in results.values())
    fp = sum(r.false_positives for r in results.values())
    fn = sum(r.false_negatives for r in results.values())
    tn = sum(r.true_negatives for r in results.values())
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    return {
        "rules": len(results),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "precision": precision,
        "recall": recall,
        "gated": sum(r.gated for r in results.values()),
        "errors": [e for r in results.values() for e in r.errors],
        "per_rule": {k: v.as_dict() for k, v in results.items()},
    }


#: Re-exported so callers can sanity-check that the synthetic history clears
#: the engine's own floor rather than assuming it.
assert SYNTHETIC_HISTORY_DAYS > MIN_SAMPLES
