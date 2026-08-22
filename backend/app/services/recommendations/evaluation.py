"""Offline evaluation of the surfacing policy.

The engine has always been able to say what it recommended. This is the part
that says whether the ordering was any good — and, crucially, whether it was
better than not having a ranker at all.

The design follows the standard offline protocol for a recommender with no A/B
infrastructure. Each *day* is a query, the cards surfaced that day are the
ranked list, and the user's own feedback supplies the relevance labels:
applied or snoozed is relevant, dismissed or expired is not. That turns the
``recommendations`` table into a labelled test set without collecting anything
new. Metrics follow Herlocker et al. (2004) and Shani & Gunawardana (2011);
NDCG is Jarvelin & Kekalainen (2002); coverage and diversity are the
beyond-accuracy objectives surveyed by Kaminskas & Bridge (2016), included
because a recommender that scores well by recommending the same three things
forever is failing in a way accuracy cannot see.

Three decisions are worth stating.

**The split is temporal, never random.** Any baseline that learns from history
— the most-frequent-rule ablation below — is fitted strictly on days before
the one being scored. A random split would let a rule's future acceptance leak
into its own past, which is the same mistake the ranker's holdout used to make.

**Ablations are the point.** A metric with nothing to compare against says
almost nothing: precision@3 of 0.42 is neither good nor bad in isolation. The
engine ordering is therefore scored against the same day's cards reordered by
rules alone (ranker removed), by historical acceptance, by severity, and at
random. If the full engine cannot beat a shuffle, that is the finding.

**The ranker is ablated by recomputation, not by guesswork.** Every input to
the rule-only score — severity, evidence basis, sample count, effect size — is
stored on the row, so the pre-ranker score can be reconstructed exactly rather
than approximated. The stored score divided by it recovers the learned
multiplier that was actually applied.
"""

from __future__ import annotations

import json
import logging
import math
import random
from dataclasses import asdict, dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.recommendations.registry import BY_ID
from app.services.recommendations.types import SEVERITY_WEIGHT, Evidence, Severity

logger = logging.getLogger("smartdesk.recommendations.evaluation")

#: Feedback that counts as the card having been worth showing.
#:
#: Snoozed sits with applied on purpose: "not now" is a judgement about timing,
#: not about relevance, and scoring it as a miss would punish exactly the rules
#: whose problem is delivery rather than content.
RELEVANT_STATUSES = frozenset({"applied", "snoozed"})

#: Feedback that counts as the card not having been worth showing. Cards still
#: ``active`` carry no verdict yet and are excluded from scoring entirely
#: rather than assumed bad.
IRRELEVANT_STATUSES = frozenset({"dismissed", "expired"})

#: Default cut-off. Three is roughly what a user reads before deciding the
#: panel is noise, and it is close to the per-section caps the engine enforces.
DEFAULT_K = 3

#: Seed for the random-ordering ablation, so a reported figure can be
#: reproduced. An unseeded shuffle would make the baseline move every run and
#: turn "we beat random" into a coin toss.
RANDOM_SEED = 20260818


# --------------------------------------------------------------------- #
# One card, as the evaluator sees it
# --------------------------------------------------------------------- #

@dataclass
class LabelledCard:
    """A surfaced card with the verdict the user gave it."""

    rule_id: str
    local_date: str
    section: str
    severity: str
    stored_score: float
    relevant: bool
    propensity: float | None
    #: Rule-only score, recomputed from the stored evidence.
    rule_score: float

    @property
    def learned_multiplier(self) -> float | None:
        """What the ranker actually did to this card, recovered."""
        if self.rule_score <= 0:
            return None
        return self.stored_score / self.rule_score


def _severity_weight(severity: str) -> float:
    """Weight for a stored severity string, defaulting rather than raising.

    Shared by the score reconstruction and the severity ablation. The first
    version of the ablation inlined this as a lambda that rebuilt the set of
    valid severities on every comparison — correct, and O(n log n) set
    constructions to sort a list of four.
    """
    try:
        return SEVERITY_WEIGHT[Severity(severity)]
    except (KeyError, ValueError):
        return SEVERITY_WEIGHT[Severity.LOW]


def _rule_score(severity: str, evidence: Evidence) -> float:
    """Reconstruct the pre-ranker score.

    Deliberately mirrors ``RecommendationEngine._score`` minus its learned
    term. Keeping the arithmetic identical is what makes the ablation an
    ablation rather than a different model: any drift between the two makes
    "rules only" measure a policy the engine never ran.
    """
    weight = _severity_weight(severity)
    effect = abs(evidence.effect or 0.0)
    return weight * evidence.confidence * (1.0 + min(effect, 4.0) / 8.0)


def load_labelled_cards(
    db: Session, user_id: str, since: str | None = None
) -> list[LabelledCard]:
    """Every card that carries a verdict, in date order."""
    # Shadow cards carry no verdict because nobody saw them, so they are not
    # a test set — including them would score the ordering against rows the
    # ordering never produced.
    where = (
        "WHERE user_id = :user_id AND (shadow IS NULL OR shadow != 1)"
        " AND status IN :statuses"
    )
    params: dict = {
        "user_id": user_id,
        "statuses": tuple(RELEVANT_STATUSES | IRRELEVANT_STATUSES),
    }
    if since:
        where += " AND local_date >= :since"
        params["since"] = since

    # ``IN`` over a tuple needs expanding rather than a single bound value.
    statuses = tuple(sorted(RELEVANT_STATUSES | IRRELEVANT_STATUSES))
    placeholders = ", ".join(f":st{i}" for i in range(len(statuses)))
    params.pop("statuses")
    params.update({f"st{i}": value for i, value in enumerate(statuses)})
    rows = db.execute(
        text(f"""
            SELECT rule_id, local_date, section, severity, score, status,
                   evidence_json, propensity
            FROM recommendations
            {where.replace(':statuses', '(' + placeholders + ')')}
            ORDER BY local_date, score DESC
        """),
        params,
    ).mappings().all()

    cards: list[LabelledCard] = []
    for row in rows:
        try:
            payload = json.loads(row["evidence_json"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        evidence = Evidence(
            basis=str(payload.get("basis") or "absolute"),
            n=int(payload.get("n") or 0),
            effect=payload.get("effect"),
        )
        cards.append(LabelledCard(
            rule_id=str(row["rule_id"]),
            local_date=str(row["local_date"]),
            section=str(row["section"]),
            severity=str(row["severity"]),
            stored_score=float(row["score"] or 0.0),
            relevant=str(row["status"]) in RELEVANT_STATUSES,
            propensity=(
                float(row["propensity"]) if row["propensity"] is not None else None
            ),
            rule_score=_rule_score(str(row["severity"]), evidence),
        ))
    return cards


# --------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------- #

def dcg(relevances: list[bool]) -> float:
    """Discounted cumulative gain with binary gains."""
    return sum(
        1.0 / math.log2(position + 2)
        for position, relevant in enumerate(relevances)
        if relevant
    )


def ndcg_at_k(ordered: list[LabelledCard], k: int) -> float | None:
    """NDCG, normalised against the best ordering of the same cards."""
    gains = [card.relevant for card in ordered[:k]]
    ideal = sorted((card.relevant for card in ordered), reverse=True)[:k]
    best = dcg(ideal)
    return None if best <= 0 else dcg(gains) / best


@dataclass
class RankingMetrics:
    """One ordering strategy's scores, macro-averaged over days."""

    strategy: str
    k: int
    days: int = 0
    precision_at_k: float | None = None
    recall_at_k: float | None = None
    ndcg_at_k: float | None = None
    mrr: float | None = None
    hit_rate: float | None = None
    #: Distinct rules that reached the top k, over the whole catalogue. A
    #: recommender that scores well on three rules forever is still failing.
    coverage: float | None = None
    #: Mean distinct sections in a top-k list, over k. Low means the panel
    #: keeps saying one kind of thing.
    diversity: float | None = None
    #: Self-normalised inverse-propensity estimate of this ordering's value —
    #: what share of the cards it would have shown were acted on, reweighted by
    #: how likely the logging policy was to show them.
    #:
    #: The only figure here that estimates a policy the user never saw. The
    #: metrics above score orderings of cards that were shown; this one asks
    #: what would have happened under a different one. ``None`` unless
    #: exploration has produced the propensity variation it needs.
    off_policy_value: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _order(
    cards: list[LabelledCard],
    strategy: str,
    history: dict[str, float],
    rng: random.Random,
) -> list[LabelledCard]:
    """One day's cards, ordered as the named strategy would have them.

    ``history`` holds each rule's acceptance rate over strictly earlier days,
    which is what keeps the most-frequent baseline from reading its own answer
    out of the day it is being scored on.
    """
    if strategy == "engine":
        return sorted(cards, key=lambda c: -c.stored_score)
    if strategy == "rules_only":
        return sorted(cards, key=lambda c: -c.rule_score)
    if strategy == "severity":
        return sorted(cards, key=lambda c: -_severity_weight(c.severity))
    if strategy == "frequent":
        return sorted(cards, key=lambda c: -history.get(c.rule_id, 0.0))
    if strategy == "random":
        shuffled = list(cards)
        rng.shuffle(shuffled)
        return shuffled
    raise ValueError(f"unknown strategy {strategy!r}")


STRATEGIES = ("engine", "rules_only", "frequent", "severity", "random")


def evaluate(
    db: Session,
    user_id: str,
    k: int = DEFAULT_K,
    since: str | None = None,
) -> "EvaluationReport":
    """Score every ordering strategy over the labelled history.

    Leave-one-day-out in the sense that matters: each day is scored by a
    policy that has seen only the days before it. Days with no relevant card
    are counted but contribute nothing to MRR or NDCG, which are undefined
    when there is nothing to rank towards.
    """
    cards = load_labelled_cards(db, user_id, since)
    by_day: dict[str, list[LabelledCard]] = {}
    for card in cards:
        by_day.setdefault(card.local_date, []).append(card)

    rng = random.Random(RANDOM_SEED)
    metrics = {name: RankingMetrics(strategy=name, k=k) for name in STRATEGIES}
    sums: dict[str, dict[str, list[float]]] = {
        name: {"p": [], "r": [], "n": [], "mrr": [], "hit": [], "div": []}
        for name in STRATEGIES
    }
    surfaced: dict[str, set[str]] = {name: set() for name in STRATEGIES}
    # What each strategy would have put in front of the user, for the
    # off-policy estimate below.
    shown_by: dict[str, set[tuple[str, str]]] = {
        name: set() for name in STRATEGIES
    }

    # Running acceptance history, advanced one day at a time so that a day is
    # never scored using its own outcome.
    applied: dict[str, int] = {}
    shown: dict[str, int] = {}
    evaluated_days = 0

    for day in sorted(by_day):
        day_cards = by_day[day]
        history = {
            rule: applied.get(rule, 0) / count
            for rule, count in shown.items() if count
        }
        relevant_total = sum(1 for c in day_cards if c.relevant)
        if len(day_cards) >= 2:
            evaluated_days += 1
            for name in STRATEGIES:
                ordered = _order(day_cards, name, history, rng)
                top = ordered[:k]
                surfaced[name].update(c.rule_id for c in top)
                shown_by[name].update((c.local_date, c.rule_id) for c in top)
                hits = sum(1 for c in top if c.relevant)
                sums[name]["p"].append(hits / max(1, len(top)))
                sums[name]["div"].append(
                    len({c.section for c in top}) / max(1, len(top))
                )
                if relevant_total:
                    sums[name]["r"].append(hits / relevant_total)
                    sums[name]["hit"].append(1.0 if hits else 0.0)
                    rank = next(
                        (i + 1 for i, c in enumerate(ordered) if c.relevant), None
                    )
                    sums[name]["mrr"].append(1.0 / rank if rank else 0.0)
                    score = ndcg_at_k(ordered, k)
                    if score is not None:
                        sums[name]["n"].append(score)

        # Only now does this day become history.
        for card in day_cards:
            shown[card.rule_id] = shown.get(card.rule_id, 0) + 1
            if card.relevant:
                applied[card.rule_id] = applied.get(card.rule_id, 0) + 1

    def mean(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    catalogue = max(1, len(BY_ID))
    support = support_diagnostic(cards)
    for name in STRATEGIES:
        m = metrics[name]
        m.days = evaluated_days
        m.precision_at_k = mean(sums[name]["p"])
        m.recall_at_k = mean(sums[name]["r"])
        m.ndcg_at_k = mean(sums[name]["n"])
        m.mrr = mean(sums[name]["mrr"])
        m.hit_rate = mean(sums[name]["hit"])
        m.diversity = mean(sums[name]["div"])
        m.coverage = len(surfaced[name]) / catalogue
        if support.identified:
            m.off_policy_value = snips(cards, shown_by[name])

    return EvaluationReport(
        user_id=user_id,
        k=k,
        since=since,
        days_evaluated=evaluated_days,
        labelled_cards=len(cards),
        relevant_cards=sum(1 for c in cards if c.relevant),
        strategies={name: metrics[name] for name in STRATEGIES},
        support=support,
    )


# --------------------------------------------------------------------- #
# Off-policy support
# --------------------------------------------------------------------- #

@dataclass
class SupportDiagnostic:
    """Whether the logged data can support an off-policy estimate at all.

    Reported rather than assumed because the answer is usually no, and a
    number produced anyway would be worse than none. IPS and its relatives
    reweight each logged reward by the probability the logging policy had of
    producing it; where every card was shown with probability 1, that weight
    is a constant and the estimator cannot distinguish the policy that ran
    from any other. Exploration is what creates the variation, and until
    ``RECOMMENDATION_EPSILON`` is raised above zero there is none.
    """

    cards_with_propensity: int = 0
    cards_without_propensity: int = 0
    explored_cards: int = 0
    min_propensity: float | None = None
    identified: bool = False
    reason: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def support_diagnostic(cards: list[LabelledCard]) -> SupportDiagnostic:
    """Can an off-policy estimate be identified from this log?"""
    with_p = [c for c in cards if c.propensity is not None]
    diag = SupportDiagnostic(
        cards_with_propensity=len(with_p),
        cards_without_propensity=len(cards) - len(with_p),
        explored_cards=sum(1 for c in with_p if c.propensity and c.propensity < 1.0),
        min_propensity=min((c.propensity for c in with_p), default=None),
    )
    if not with_p:
        diag.reason = (
            "No card carries a propensity. These rows predate the column, so "
            "the probabilities are unknown and cannot be reconstructed."
        )
    elif diag.explored_cards == 0:
        diag.reason = (
            "Every card was shown with probability 1: the policy was "
            "deterministic, so no off-policy estimator is identified. Raise "
            "RECOMMENDATION_EPSILON above zero to begin collecting the "
            "variation these estimators need."
        )
    else:
        diag.identified = True
        diag.reason = (
            f"{diag.explored_cards} card(s) were surfaced with probability "
            f"below 1, so importance weights are defined."
        )
    return diag


def snips(cards: list[LabelledCard], target: set[tuple[str, str]]) -> float | None:
    """Self-normalised inverse propensity estimate of a target policy.

    ``target`` is the set of ``(local_date, rule_id)`` the policy being
    evaluated would have shown. Self-normalised (Swaminathan & Joachims 2015)
    rather than plain IPS because the plain estimator's variance is
    unmanageable at these sample sizes — a single card logged at a small
    propensity dominates the average.

    ``None`` when no logged card has a usable propensity, which is the honest
    answer rather than zero.
    """
    numerator = denominator = 0.0
    for card in cards:
        if card.propensity is None or card.propensity <= 0:
            continue
        if (card.local_date, card.rule_id) not in target:
            continue
        weight = 1.0 / card.propensity
        numerator += weight * (1.0 if card.relevant else 0.0)
        denominator += weight
    return numerator / denominator if denominator > 0 else None


@dataclass
class EvaluationReport:
    """Everything the harness measured."""

    user_id: str
    k: int
    since: str | None
    days_evaluated: int
    labelled_cards: int
    relevant_cards: int
    strategies: dict[str, RankingMetrics] = field(default_factory=dict)
    support: SupportDiagnostic = field(default_factory=SupportDiagnostic)

    @property
    def beats_random(self) -> bool | None:
        """Does the engine ordering beat a shuffle of the same cards?

        The lowest bar there is, and the first thing an examiner will ask.
        """
        engine = self.strategies.get("engine")
        chance = self.strategies.get("random")
        if not engine or not chance:
            return None
        if engine.ndcg_at_k is None or chance.ndcg_at_k is None:
            return None
        return engine.ndcg_at_k > chance.ndcg_at_k

    @property
    def ranker_helps(self) -> bool | None:
        """Does the learned layer improve on the rules alone?"""
        engine = self.strategies.get("engine")
        rules = self.strategies.get("rules_only")
        if not engine or not rules:
            return None
        if engine.ndcg_at_k is None or rules.ndcg_at_k is None:
            return None
        return engine.ndcg_at_k > rules.ndcg_at_k

    def as_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "k": self.k,
            "since": self.since,
            "days_evaluated": self.days_evaluated,
            "labelled_cards": self.labelled_cards,
            "relevant_cards": self.relevant_cards,
            "beats_random": self.beats_random,
            "ranker_helps": self.ranker_helps,
            "strategies": {n: m.as_dict() for n, m in self.strategies.items()},
            "support": self.support.as_dict(),
        }
