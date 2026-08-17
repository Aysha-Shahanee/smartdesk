"""Core types for the recommendation engine.

The shape here is what keeps 70+ rules cheap: a rule never touches the
database. It receives a :class:`FeatureContext` — a frozen mapping of named
scalars built once per tick — and returns a :class:`Finding` or ``None``.
Everything a rule needs must therefore be a feature, which is deliberate: it
forces the cost of a new signal to be paid once per tick rather than once per
rule that reads it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from typing import Any, Callable, Iterator, Mapping


class Scope(str, Enum):
    """When a rule is evaluated. Also the registry's partition key — a live
    tick never iterates the non-live rules."""

    LIVE = "live"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


#: Weight each severity contributes to the surfacing score. Spread wide enough
#: that a high-severity finding on weak evidence still outranks a low-severity
#: one on strong evidence — the user's attention is the scarce resource, and a
#: 90-minute unbroken stretch matters more than a well-measured triviality.
SEVERITY_WEIGHT: dict[Severity, float] = {
    Severity.LOW: 0.4,
    Severity.MEDIUM: 0.7,
    Severity.HIGH: 1.0,
}


class Section(str, Enum):
    """Which panel of the Recommendations page a finding belongs in.

    These mirror the four groups the page already renders, so the engine's
    output drops into the existing layout rather than requiring it to be
    redesigned around whatever the rules happen to produce.
    """

    IMMEDIATE = "immediate"      # act now — the live family
    INSIGHT = "insight"          # what happened, stated plainly
    PLANNING = "planning"        # change the shape of the day/week
    BEHAVIOUR = "behaviour"      # change a habit, with the measurement behind it


@dataclass(frozen=True)
class Evidence:
    """Why a finding is believed, carried alongside every claim.

    ``n`` is not decoration. A test asserts that every emitted finding carries
    a sample count meeting its rule's declared minimum, which is what stops the
    engine ever printing an effect size it cannot support — the exact failure
    the hardcoded "40% decrease in focus after meetings" represented.
    """

    basis: str
    n: int = 0
    effect: float | None = None
    comparison: str | None = None

    @property
    def confidence(self) -> float:
        """0..1 confidence used in scoring.

        Grows with sample size and saturates at n=30 — past that, more samples
        of a personal baseline stop meaningfully changing what we believe. An
        absolute rule (one that needs no history, like "a meeting starts in ten
        minutes") reports n=0 and is fully confident by construction.
        """
        if self.basis == "absolute":
            return 1.0
        if self.n <= 0:
            return 0.3
        return min(1.0, 0.35 + 0.65 * min(self.n, 30) / 30)


@dataclass(frozen=True)
class Finding:
    """What a rule returns when it fires.

    Carries facts, not prose. The wording is applied later from the rule's own
    templates, so the same finding can render into a card, a report paragraph
    or a notification without three copies of the sentence drifting apart.
    """

    dedup_key: str
    facts: dict[str, Any] = field(default_factory=dict)
    evidence: Evidence = field(default_factory=lambda: Evidence(basis="absolute"))
    #: Overrides the rule's declared severity when the magnitude warrants it.
    severity: Severity | None = None


@dataclass(frozen=True)
class RuleSpec:
    """A registered rule: its metadata, its predicate and its copy."""

    id: str
    version: int
    scope: Scope
    section: Section
    severity: Severity
    title: str
    why: str
    action: str
    fn: Callable[["FeatureContext"], Finding | None]
    requires: frozenset[str] = frozenset()
    min_days: int = 0
    cooldown: timedelta = timedelta(hours=6)
    #: Minimum sample count the finding's evidence must carry. Enforced by the
    #: engine, so a rule cannot quietly ship an under-powered comparison.
    min_n: int = 0
    action_label: str | None = None

    def gated(self, ctx: "FeatureContext") -> bool:
        """True when this rule cannot run against the given context.

        Checked before the predicate is called — the whole point of declaring
        ``requires`` is that an unavailable signal costs a set operation rather
        than a function call and a KeyError.
        """
        if ctx.days_of_history < self.min_days:
            return True
        return not self.requires <= ctx.keys()


class FeatureContext(Mapping[str, Any]):
    """An immutable snapshot of everything the rules may read.

    Built once per tick and shared by every rule in scope. Missing keys are a
    normal condition, not an error: an offline IDE extension simply means the
    IDE features are absent and the four rules requiring them are gated out.
    """

    __slots__ = ("_data", "days_of_history", "as_of", "user_id", "day_summaries")

    def __init__(
        self,
        data: dict[str, Any],
        *,
        as_of,
        user_id: str,
        days_of_history: int,
        day_summaries: list | None = None,
    ) -> None:
        # Keys carrying None are dropped rather than stored: a feature that
        # could not be computed must be *absent* so requirement gating catches
        # it, not present-and-null for every rule to re-check by hand.
        self._data = {k: v for k, v in data.items() if v is not None}
        self.as_of = as_of
        self.user_id = user_id
        self.days_of_history = days_of_history
        # The per-day rows the period builders already reduced, carried for the
        # report to reuse. Deliberately an attribute rather than a feature: it
        # is a list of dataclasses, and putting it in the mapping would expose
        # it to `requires` gating and to the debug endpoint's feature dump.
        self.day_summaries = day_summaries or []

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def keys(self):  # type: ignore[override]
        return self._data.keys()

    def num(self, key: str, default: float = 0.0) -> float:
        """Read a numeric feature with a default, for optional signals."""
        value = self._data.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
