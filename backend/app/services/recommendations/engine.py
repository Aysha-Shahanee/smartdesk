"""Engine orchestration: gate, evaluate, score, dedup, cap, persist.

A rule firing is not yet a recommendation. The stages between them are what
separate a useful panel from seventy cards nobody reads, and they all run
before anything is written — so a busy tick costs the same number of database
writes as a quiet one, which is zero.
"""

from __future__ import annotations

import json
import logging
import random
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.time import local_now
from app.models.db import RecommendationEventRecord, RecommendationRecord
from app.repositories.preference_repository import PreferenceRepository
from app.services.recommendations import narrative
from app.services.recommendations.baselines import BaselineBuilder, BaselineSet
from app.services.recommendations.features import (
    build_daily_context,
    build_live_context,
)
from app.services.recommendations.periods import (
    build_monthly_context,
    build_weekly_context,
)
from app.services.recommendations.ranker import ranker
from app.services.recommendations.registry import BY_ID, REGISTRY, load_all_rules
from app.services.recommendations.stats import benjamini_hochberg
from app.services.recommendations.types import (
    SEVERITY_WEIGHT,
    FeatureContext,
    Finding,
    RuleSpec,
    Scope,
    Section,
    Severity,
)

logger = logging.getLogger("smartdesk.recommendations.engine")

#: How many cards each section may show at once. The live cap is the tight one:
#: two things to act on is a prompt, six is a to-do list the user did not ask
#: for and will close.
SECTION_CAPS: dict[Section, int] = {
    Section.IMMEDIATE: 2,
    Section.INSIGHT: 4,
    Section.PLANNING: 3,
    Section.BEHAVIOUR: 4,
}

#: A live card stops being true quickly — the stretch it described has ended,
#: the meeting has started. Daily cards stand until the next day's run.
LIVE_TTL = timedelta(minutes=45)

#: Exploration's source of randomness, kept private so that seeding it in a
#: test cannot perturb anything else drawing from the global ``random``.
_RNG = random.Random()


class RecommendationEngine:
    """Generates, stores and serves recommendations."""

    def __init__(self, session_factory=SessionLocal) -> None:
        self._session_factory = session_factory
        self._baseline_builder = BaselineBuilder(session_factory)
        self._baselines: dict[str, tuple[str, BaselineSet]] = {}
        load_all_rules()

    # ------------------------------------------------------------------ #
    # Baselines                                                           #
    # ------------------------------------------------------------------ #

    def baselines(
        self,
        db: Session,
        user_id: str,
        as_of: datetime,
        force: bool = False,
    ) -> BaselineSet:
        """Cached per user per local day.

        Percentiles over a 30-day window do not move meaningfully inside a
        day, and recomputing them on a 60-second timer would dominate the tick
        budget the whole design exists to protect.
        """
        day_key = as_of.strftime("%Y-%m-%d")
        cached = self._baselines.get(user_id)
        if not force and cached is not None and cached[0] == day_key:
            return cached[1]

        computed = self._baseline_builder.compute(db, user_id, as_of)
        self._baselines[user_id] = (day_key, computed)
        logger.info(
            "Computed baselines for %s: %d metrics, %d days of history",
            user_id, len(computed.global_stats), computed.days_of_history,
        )
        return computed

    def invalidate_baselines(self, user_id: str) -> None:
        """Drop the cached baselines for a user.

        The cache is keyed by day, which is right while the inputs only change
        when a new day starts. Resetting the baseline epoch changes them
        immediately, and without this the user would set the control, see
        nothing happen, and reasonably conclude it was broken.
        """
        self._baselines.pop(user_id, None)

    # ------------------------------------------------------------------ #
    # Generation                                                          #
    # ------------------------------------------------------------------ #

    def generate(
        self,
        db: Session,
        user_id: str,
        as_of: datetime | None = None,
        scopes: tuple[Scope, ...] = (Scope.LIVE, Scope.DAILY),
        supersede: bool = False,
    ) -> int:
        """Run the requested scopes and persist what survives. Returns the count.

        ``supersede`` retires the cards already stored for the same day and
        scope before generating, instead of deduplicating against them. Off by
        default, because the interactive path calls this on every page load and
        rewriting the panel underneath a reader is not an improvement.

        The nightly pass sets it. That pass runs after the window roll-up and
        the clustering it depends on, so it is the only caller whose inputs are
        known to be complete — and dedup by itself makes the first card of a
        day permanent, which is wrong precisely when an early card was computed
        from data that had not finished arriving.
        """
        as_of = as_of or local_now()
        baselines = self.baselines(db, user_id, as_of)
        # Read once for the whole pass. A muted rule is a standing instruction,
        # not something that changes between two scopes of the same tick.
        prefs = PreferenceRepository(db)
        muted = prefs.muted_rules(user_id)
        # A rule that is both muted and shadowed is simply muted: not computing
        # it is the stronger of the two instructions.
        shadowed = prefs.shadowed_rules(user_id) - muted

        superseded = self._supersede(db, user_id, as_of, scopes) if supersede else set()

        written = 0
        for scope in scopes:
            if scope is Scope.LIVE:
                ctx = build_live_context(db, user_id, as_of, baselines)
            elif scope is Scope.DAILY:
                ctx = build_daily_context(db, user_id, as_of, baselines)
            elif scope is Scope.WEEKLY:
                ctx = build_weekly_context(db, user_id, as_of, baselines)
            elif scope is Scope.MONTHLY:
                ctx = build_monthly_context(db, user_id, as_of, baselines)
            else:
                logger.debug("Scope %s not implemented yet; skipping.", scope)
                continue
            written += self._run_scope(
                db, scope, ctx, as_of, muted, shadowed, superseded
            )

        self._expire_stale(db, user_id, as_of)
        return written

    def _run_scope(
        self,
        db: Session,
        scope: Scope,
        ctx: FeatureContext,
        as_of: datetime,
        muted: set[str] | None = None,
        shadowed: set[str] | None = None,
        superseded: set[str] | None = None,
    ) -> int:
        # Muting is applied before evaluation rather than by filtering cards
        # afterwards. A rule the user has switched off should cost nothing and
        # leave no trace: no finding, no card, no row that a later count could
        # mistake for something the engine chose not to show.
        specs = REGISTRY[scope]
        if muted:
            specs = [spec for spec in specs if spec.id not in muted]

        # Shadow rules run down a separate path so they cannot influence what
        # the user sees. They take no cap slot, join no dedup contest and are
        # never chosen by exploration — a rule under trial must not be able to
        # displace one that has earned its place.
        shadow_specs = (
            [spec for spec in specs if spec.id in shadowed] if shadowed else []
        )
        if shadowed:
            specs = [spec for spec in specs if spec.id not in shadowed]

        candidates = self._evaluate(specs, ctx)
        shadow_written = self._run_shadow(db, shadow_specs, ctx, as_of)
        if not candidates:
            return shadow_written

        # Highest score first, then dedup and cap. Ordering before deduping
        # matters: when two rules share a dedup key the stronger finding is the
        # one that survives, not whichever happened to be registered first.
        candidates.sort(key=lambda item: item[2], reverse=True)

        # Two grouped reads for the whole family, replacing one cooldown query
        # per surviving candidate — a busy daily run issued seventeen of those,
        # each filtering on a column trio no index covered.
        local_date = as_of.strftime("%Y-%m-%d")
        # When this pass is rebuilding a day, that day's own cards are not
        # evidence that a rule has fired too recently — they are precisely what
        # is being replaced. Cooldown still applies across every other day.
        last_fired = self._last_fired(
            db, ctx.user_id, REGISTRY[scope], as_of,
            exclude_local_date=local_date if superseded else None,
        )
        # Seeding the seen set from what is already stored turns the common
        # duplicate — a rule that fired earlier today — into a set lookup
        # instead of a rendered record and a caught IntegrityError.
        seen_keys: set[str] = self._existing_keys(db, ctx.user_id, local_date)
        if superseded:
            # A card this pass just retired must not also be the reason its own
            # replacement is skipped. Only those keys are dropped: a card the
            # user dismissed still counts, because replacing a stale figure is
            # no reason to put something back that someone said no to.
            seen_keys -= superseded

        # Eligibility is settled before selection because exploration has to
        # know what it is choosing between, and the staging loop below cannot
        # tell it: that loop drops a candidate the moment its section is full
        # and never learns how many more were waiting. The pool is the set of
        # cards the policy genuinely had the option of showing.
        pool: dict[Section, list[tuple[RuleSpec, Finding, float]]] = {}
        for spec, finding, score in candidates:
            if finding.dedup_key in seen_keys:
                continue
            if self._on_cooldown(last_fired, spec, as_of):
                continue
            pool.setdefault(spec.section, []).append((spec, finding, score))

        ordered: list[tuple[RuleSpec, Finding, float, float, bool]] = []
        for section, entries in pool.items():
            ordered.extend(self._explore(entries, SECTION_CAPS.get(section, 3)))

        per_section: dict[Section, int] = {}
        staged: list[RecommendationRecord] = []

        for spec, finding, score, propensity, explored in ordered:
            # Still checked here as well as above: two rules can produce the
            # same key within a single run, which the stored set cannot know.
            if finding.dedup_key in seen_keys:
                continue
            cap = SECTION_CAPS.get(spec.section, 3)
            if per_section.get(spec.section, 0) >= cap:
                continue
            record = self._build(spec, finding, score, ctx, as_of)
            if record is None:
                continue
            record.propensity = propensity
            record.explored = explored
            staged.append(record)
            seen_keys.add(finding.dedup_key)
            per_section[spec.section] = per_section.get(spec.section, 0) + 1

        return self._write(db, staged) + shadow_written

    def _run_shadow(
        self,
        db: Session,
        specs: list[RuleSpec],
        ctx: FeatureContext,
        as_of: datetime,
    ) -> int:
        """Evaluate rules under trial and record what they would have said.

        Everything the real path does to decide *whether to show* a card is
        skipped, because nothing here is shown: no cooldown, no cap, no dedup
        against real cards. What is kept is the evaluation and the rendering,
        which is the part being tested — a rule that fires forty times a day or
        cannot satisfy its own templates should be discovered here rather than
        by the person it was meant to help.

        Deduped only against other shadow rows for the same day, so a rule
        under trial cannot inflate its own fire count by being evaluated twice
        in one day by two different scopes.
        """
        if not specs:
            return 0
        local_date = as_of.strftime("%Y-%m-%d")
        existing = self._existing_shadow_keys(db, ctx.user_id, local_date)
        staged: list[RecommendationRecord] = []
        for spec, finding, score in self._evaluate(specs, ctx):
            if finding.dedup_key in existing:
                continue
            record = self._build(spec, finding, score, ctx, as_of)
            if record is None:
                continue
            record.shadow = True
            # No propensity: nothing was surfaced, so there was no surfacing
            # decision to assign a probability to.
            record.propensity = None
            staged.append(record)
            existing.add(finding.dedup_key)
        if staged:
            logger.info(
                "Shadow mode recorded %d card(s) from %s",
                len(staged), ", ".join(sorted({r.rule_id for r in staged})),
            )
        return self._write(db, staged)

    @staticmethod
    def _existing_shadow_keys(
        db: Session, user_id: str, local_date: str
    ) -> set[str]:
        rows = db.execute(text("""
            SELECT dedup_key FROM recommendations
            WHERE user_id = :user_id AND local_date = :local_date
              AND shadow = 1
        """), {"user_id": user_id, "local_date": local_date}).fetchall()
        return {row[0] for row in rows}

    @staticmethod
    def _explore(
        entries: list[tuple[RuleSpec, Finding, float]],
        cap: int,
        epsilon: float | None = None,
        rng: random.Random | None = None,
    ) -> list[tuple[RuleSpec, Finding, float, float, bool]]:
        """Order one section's candidates and price each one's chance of a slot.

        The ranker is a learned model whose effect on the panel nobody can
        currently measure. Off-policy estimators exist for exactly this
        situation — they reweight each logged outcome by how likely the policy
        was to produce it — but every one of them needs the logging policy to
        have had a real choice. Ranking strictly by score means the top cards
        appear with probability 1 and everything else with probability 0, and a
        weight of "reward / 0" is not a number. No later analysis recovers this:
        the information is destroyed when the panel is built.

        So with probability ``epsilon`` the lowest slot in the section goes to
        a card drawn uniformly from those that missed the cut. Every candidate
        then has a known, non-zero chance of being seen, which is the property
        the estimators actually require.

        The cost is bounded deliberately. Only the marginal slot is ever at
        stake, so the strongest cards in a section are never touched; and a
        high-severity card is never displaced, on the same reasoning that keeps
        the ranker's multiplier clamped — a learned adjustment may reorder
        suggestions, never bury a finding that matters.

        Returns each entry with ``(propensity, explored)`` appended. The
        propensity describes the *policy*, not the draw, so it stays correct
        for a card that reaches the panel by some later path — a failed render
        above it, say — rather than describing only the branch that was taken.
        """
        eps = settings.RECOMMENDATION_EPSILON if epsilon is None else epsilon
        eps = min(max(eps, 0.0), 1.0)
        n = len(entries)

        # Nothing was passed over, so the policy faced no choice and showing
        # everything is not a decision that needs a probability attached.
        if cap <= 0 or n <= cap:
            return [(s, f, sc, 1.0, False) for s, f, sc in entries]

        marginal = entries[cap - 1]
        bench = entries[cap:]

        if eps <= 0.0 or marginal[0].severity is Severity.HIGH:
            return [
                (s, f, sc, 1.0 if i < cap else 0.0, False)
                for i, (s, f, sc) in enumerate(entries)
            ]

        rng = rng or _RNG
        p_bench = eps / len(bench)
        tagged: list[tuple[RuleSpec, Finding, float, float, bool]] = [
            (s, f, sc, 1.0, False) for s, f, sc in entries[: cap - 1]
        ]

        if rng.random() < eps:
            pick = rng.randrange(len(bench))
            tagged.append((*bench[pick], p_bench, True))
            tagged.append((*marginal, 1.0 - eps, False))
            tagged.extend(
                (*entry, p_bench, False)
                for i, entry in enumerate(bench)
                if i != pick
            )
        else:
            tagged.append((*marginal, 1.0 - eps, False))
            tagged.extend((*entry, p_bench, False) for entry in bench)
        return tagged

    def _evaluate(
        self,
        specs: list[RuleSpec],
        ctx: FeatureContext,
    ) -> list[tuple[RuleSpec, Finding, float]]:
        """Run every rule in a scope. Pure, no I/O, the cheap part of a tick."""
        out: list[tuple[RuleSpec, Finding, float]] = []
        for spec in specs:
            if spec.gated(ctx):
                continue
            try:
                finding = spec.fn(ctx)
            except Exception:
                # One broken rule must not take the panel down with it.
                logger.exception("Rule %s raised; skipping it this tick.", spec.id)
                continue
            if finding is None:
                continue
            # The evidence gate. A rule declaring it needs 8 samples and
            # emitting a finding backed by 3 is a bug, and shipping the claim
            # anyway is exactly the failure this engine exists to avoid.
            if finding.evidence.n < spec.min_n:
                logger.warning(
                    "Rule %s fired with n=%d below its declared min_n=%d; dropped.",
                    spec.id, finding.evidence.n, spec.min_n,
                )
                continue
            out.append((spec, finding, self._score(spec, finding, ctx.as_of)))
        return self._control_false_discovery(out)

    @staticmethod
    def _control_false_discovery(
        candidates: list[tuple[RuleSpec, Finding, float]],
    ) -> list[tuple[RuleSpec, Finding, float]]:
        """Drop statistical claims that do not survive the day's multiplicity.

        Every rule that ends in a hypothesis test is another chance to be
        fooled, and they all run against the same day. Judged one at a time at
        the conventional 0.05 the battery would produce a significant-looking
        finding most days from nothing at all — with twenty true nulls the odds
        of at least one false positive are about 64%. Benjamini-Hochberg holds
        the share of published claims that are false to
        ``RECOMMENDATION_FDR_Q`` instead of pretending each test stands alone.

        Only findings carrying a ``p_value`` take part. An absolute claim — the
        IDE has stopped reporting, the calendar has not synced — is an
        observation rather than an inference, has no null to reject, and must
        not be suppressed because some unrelated correlation was weak. That
        distinction is the whole reason ``p_value`` defaults to ``None`` rather
        than 1.0.
        """
        tested = [
            (index, item) for index, item in enumerate(candidates)
            if item[1].evidence.p_value is not None
        ]
        if not tested:
            return candidates

        survives = benjamini_hochberg(
            [float(item[1].evidence.p_value) for _, item in tested],
            settings.RECOMMENDATION_FDR_Q,
        )
        dropped = {
            index for (index, _), kept in zip(tested, survives) if not kept
        }
        if dropped:
            for position in sorted(dropped):
                spec, finding, _ = candidates[position]
                logger.info(
                    "Rule %s dropped by FDR control: p=%.4f over %d tests at q=%.2f",
                    spec.id, finding.evidence.p_value, len(tested),
                    settings.RECOMMENDATION_FDR_Q,
                )
        return [
            item for index, item in enumerate(candidates) if index not in dropped
        ]

    @staticmethod
    def _score(spec: RuleSpec, finding: Finding, as_of: datetime | None = None) -> float:
        """Surfacing score: severity x confidence x effect x learned acceptance.

        Each term is bounded, so no single one can dominate. Effect enters
        through a gentle saturating curve rather than linearly — a finding
        three sigma out is meaningfully more urgent than one at one sigma, but
        thirty sigma is not thirty times more urgent, it is a measurement
        error.

        The learned term is exactly 1.0 until the ranker has enough feedback to
        train, so cold start behaves identically to the unlearned engine.
        """
        severity = finding.severity or spec.severity
        base = SEVERITY_WEIGHT[severity] * finding.evidence.confidence
        effect = abs(finding.evidence.effect or 0.0)
        effect_term = 1.0 + min(effect, 4.0) / 8.0
        rule_score = base * effect_term

        moment = as_of or local_now()
        learned = ranker.multiplier(
            rule_id=spec.id,
            severity=severity.value,
            section=spec.section.value,
            hour=moment.hour,
            weekday=moment.weekday(),
            score=rule_score,
        )
        return round(rule_score * learned, 4)

    # ------------------------------------------------------------------ #
    # Persistence                                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _last_fired(
        db: Session,
        user_id: str,
        specs: list[RuleSpec],
        as_of: datetime,
        exclude_local_date: str | None = None,
    ) -> dict[str, str]:
        """When each rule in a family last fired, in one grouped read.

        Bounded by the longest cooldown in the family — nothing older than that
        could suppress anything, so there is no reason to read it. Comparison
        stays on the ISO strings the column already holds, exactly as the
        per-rule query did.

        ``exclude_local_date`` omits one day from the answer, for the caller
        that has just retired that day's cards and is about to rewrite them.
        Without it the rows being replaced would suppress their own
        replacements and the day would come back empty.
        """
        if not specs:
            return {}
        horizon = max(spec.cooldown for spec in specs)
        clause = "" if exclude_local_date is None else " AND local_date != :exclude"
        params = {"user_id": user_id, "since": (as_of - horizon).isoformat()}
        if exclude_local_date is not None:
            params["exclude"] = exclude_local_date
        rows = db.execute(
            text(f"""
                SELECT rule_id, MAX(generated_at) AS last_at
                FROM recommendations
                WHERE user_id = :user_id AND generated_at >= :since{clause}
                GROUP BY rule_id
            """),
            params,
        ).mappings().all()
        return {row["rule_id"]: row["last_at"] for row in rows}

    @staticmethod
    def _existing_keys(db: Session, user_id: str, local_date: str) -> set[str]:
        """Dedup keys already stored for this user on this local day.

        The same trio the unique index guards, read once so the engine can
        decline to build a card the database would reject anyway.
        """
        rows = db.execute(
            text("""
                SELECT DISTINCT dedup_key FROM recommendations
                WHERE user_id = :user_id AND local_date = :local_date
            """),
            {"user_id": user_id, "local_date": local_date},
        ).scalars().all()
        return set(rows)

    @staticmethod
    def _on_cooldown(
        last_fired: dict[str, str],
        spec: RuleSpec,
        as_of: datetime,
    ) -> bool:
        """True when this rule fired recently enough that repeating it would nag."""
        last = last_fired.get(spec.id)
        return last is not None and last >= (as_of - spec.cooldown).isoformat()

    @staticmethod
    def _write(db: Session, records: list[RecommendationRecord]) -> int:
        """Commit a scope's cards in one transaction. Returns the count written.

        One commit rather than one per card. That matters more than it looks on
        SQLite, where each commit is an fsync: eight rows measured at 51.6 ms
        written singly against 6.7 ms written together.

        SAVEPOINT is deliberately not used to isolate the rows. The pysqlite
        driver runs in its legacy mode (``isolation_level == ''``) and issues an
        implicit COMMIT before any non-DML statement, so wrapping each row in
        ``begin_nested()`` silently commits the batch a row at a time and gives
        back nothing. The dedup pre-check above is what makes a violation here
        rare instead; the retry below is what makes it survivable.
        """
        if not records:
            return 0
        try:
            db.add_all(records)
            db.commit()
            return len(records)
        except IntegrityError:
            # Two writers produced the same card in the same instant — the live
            # job and an on-demand API call. Rare, real, and not worth losing
            # the rest of the batch over.
            db.rollback()
            logger.debug("Batch write raced a concurrent writer; retrying singly.")

        written = 0
        for record in records:
            try:
                db.add(record)
                db.commit()
                written += 1
            except IntegrityError:
                db.rollback()
                logger.debug(
                    "Duplicate recommendation for %s / %s; keeping the existing row.",
                    record.rule_id, record.dedup_key,
                )
        return written

    @staticmethod
    def _build(
        spec: RuleSpec,
        finding: Finding,
        score: float,
        ctx: FeatureContext,
        as_of: datetime,
    ) -> RecommendationRecord | None:
        """Render a finding into a row. Pure — no session, no I/O.

        ``None`` when the rule's templates could not be satisfied, which
        ``narrative.render`` has already logged as the rule bug it is.
        """
        rendered = narrative.render(spec, finding)
        if rendered is None:
            return None
        title, why, action = rendered

        severity = finding.severity or spec.severity
        # A live card describes a moment and stops being true quickly. A weekly
        # or monthly one stays relevant until its scope comes round again, and
        # must not vanish at midnight the way a daily card does.
        if spec.scope is Scope.LIVE:
            valid_until = (as_of + LIVE_TTL).isoformat()
        elif spec.scope is Scope.WEEKLY:
            valid_until = (as_of + timedelta(days=7)).isoformat()
        elif spec.scope is Scope.MONTHLY:
            valid_until = (as_of + timedelta(days=30)).isoformat()
        else:
            valid_until = None

        record = RecommendationRecord(
            id=str(uuid.uuid4()),
            user_id=ctx.user_id,
            device_id=settings.DEVICE_ID,
            rule_id=spec.id,
            rule_version=spec.version,
            scope=spec.scope.value,
            section=spec.section.value,
            severity=severity.value,
            title=title,
            why=why,
            action=action,
            action_label=spec.action_label,
            based_on=narrative.describe_evidence(
                finding.evidence, ctx.days_of_history
            ),
            facts_json=json.dumps(finding.facts, ensure_ascii=False, default=str),
            evidence_json=json.dumps(asdict(finding.evidence), ensure_ascii=False),
            score=score,
            dedup_key=finding.dedup_key,
            local_date=as_of.strftime("%Y-%m-%d"),
            generated_at=as_of.isoformat(),
            valid_until=valid_until,
            status="active",
        )
        return record

    def _supersede(
        self,
        db: Session,
        user_id: str,
        as_of: datetime,
        scopes: tuple[Scope, ...],
    ) -> set[str]:
        """Retire the cards an authoritative re-run is about to replace.

        Returns the dedup keys retired, because retiring a card is only half
        the job: dedup and cooldown both read the rows that are still there,
        and would otherwise suppress the very replacements this exists to
        produce — leaving the panel empty instead of merely stale.

        Without this, ``_existing_keys`` makes the first card written for a
        dedup key on a given day the permanent one. That is the right default
        for repeated reads of a finished day, and wrong for the case that
        actually occurs: a card computed at 01:20 from a roll-up that was
        hours behind, still sitting on the panel next to one computed at 01:28
        from complete data, quoting a different total for the same day.

        Only ``active`` rows are touched. Applied, dismissed and snoozed rows
        are the user's own answers and the ranker's training set — replacing a
        card is not grounds for discarding what someone said about it. Shadow
        rows are left alone too: they are a record of what a rule under trial
        produced, and their own path already dedups them separately.

        A delete rather than a status change, which is not the obvious choice
        and is the only one that works. ``uq_recommendations_dedup_day`` is
        unique on (user, dedup_key, local_date), so marking the old row
        ``expired`` leaves it holding the key and the replacement cannot be
        inserted at all — the day empties instead of refreshing.

        Nothing is lost by removing it. That same index caps a rule at one card
        per day, so the fired-count telemetry reads is unchanged the moment the
        replacement lands. Feedback events are not orphaned either: recording
        feedback moves a card out of ``active``, so an active row has none.
        """
        if not scopes:
            return set()
        local_date = as_of.strftime("%Y-%m-%d")
        doomed = db.query(RecommendationRecord).filter(
            RecommendationRecord.user_id == user_id,
            RecommendationRecord.status == "active",
            RecommendationRecord.local_date == local_date,
            RecommendationRecord.scope.in_([scope.value for scope in scopes]),
            RecommendationRecord.shadow.isnot(True),
        )
        keys = {row.dedup_key for row in doomed.all()}
        superseded = doomed.delete(synchronize_session=False)
        if superseded:
            db.commit()
            logger.info(
                "Superseded %d card(s) for %s on %s before regenerating.",
                superseded, user_id, local_date,
            )
        return keys

    def _expire_stale(self, db: Session, user_id: str, as_of: datetime) -> int:
        """Retire live cards whose moment has passed."""
        expired = db.query(RecommendationRecord).filter(
            RecommendationRecord.user_id == user_id,
            RecommendationRecord.status == "active",
            RecommendationRecord.valid_until.isnot(None),
            RecommendationRecord.valid_until < as_of.isoformat(),
        ).update(
            {"status": "expired", "status_at": as_of.isoformat()},
            synchronize_session=False,
        )
        if expired:
            db.commit()
        return expired

    # ------------------------------------------------------------------ #
    # Reading                                                             #
    # ------------------------------------------------------------------ #

    def active_for(
        self,
        db: Session,
        user_id: str,
        local_date: str,
    ) -> list[RecommendationRecord]:
        """Everything still worth showing for a given local day.

        Shadow rows are excluded here rather than filtered by the caller. This
        is the single read the panel and the reports both go through, and a
        shadow card reaching a user would defeat the entire purpose of running
        one — ``isnot(True)`` rather than ``== False`` because rows written
        before the column existed hold NULL.
        """
        return db.query(RecommendationRecord).filter(
            RecommendationRecord.user_id == user_id,
            RecommendationRecord.local_date == local_date,
            RecommendationRecord.status.in_(("active", "applied")),
            RecommendationRecord.shadow.isnot(True),
        ).order_by(RecommendationRecord.score.desc()).all()

    def record_feedback(
        self,
        db: Session,
        recommendation_id: str,
        action: str,
        as_of: datetime | None = None,
    ) -> RecommendationRecord | None:
        """Apply a user's verdict and log it as training data.

        The event row is the ranker's entire input, so it is written even when
        the status transition is a no-op — a second dismissal of the same card
        is still information about the card.
        """
        as_of = as_of or local_now()
        record = db.get(RecommendationRecord, recommendation_id)
        if record is None:
            return None

        if action in ("applied", "dismissed", "snoozed"):
            record.status = action
            record.status_at = as_of.isoformat()

        seconds_to_action = None
        try:
            generated = datetime.fromisoformat(record.generated_at)
            seconds_to_action = max(0, int((as_of - generated).total_seconds()))
        except (TypeError, ValueError):
            pass

        db.add(RecommendationEventRecord(
            id=str(uuid.uuid4()),
            recommendation_id=record.id,
            user_id=record.user_id,
            rule_id=record.rule_id,
            action=action,
            hour_of_day=as_of.hour,
            weekday=as_of.weekday(),
            seconds_to_action=seconds_to_action,
            created_at=as_of.isoformat(),
        ))
        db.commit()
        return record

    # ------------------------------------------------------------------ #
    # Introspection                                                       #
    # ------------------------------------------------------------------ #

    def describe_context(
        self,
        db: Session,
        user_id: str,
        as_of: datetime | None = None,
        scope: Scope = Scope.LIVE,
    ) -> dict:
        """Dump a feature snapshot and the gate status of every rule.

        The debugging tool for "why did nothing fire?", which is otherwise an
        opaque question once there are seventy rules.
        """
        as_of = as_of or local_now()
        baselines = self.baselines(db, user_id, as_of)
        builders = {
            Scope.LIVE: build_live_context,
            Scope.DAILY: build_daily_context,
            Scope.WEEKLY: build_weekly_context,
            Scope.MONTHLY: build_monthly_context,
        }
        ctx = builders[scope](db, user_id, as_of, baselines)
        muted = PreferenceRepository(db).muted_rules(user_id)
        rules = []
        for spec in REGISTRY[scope]:
            missing = sorted(spec.requires - ctx.keys())
            is_muted = spec.id in muted
            gated = is_muted or spec.gated(ctx)
            fired = None
            if not gated:
                try:
                    fired = spec.fn(ctx) is not None
                except Exception as exc:  # surfaced, not swallowed, in the debug view
                    fired = f"error: {exc}"
            rules.append({
                "id": spec.id,
                "section": spec.section.value,
                "gated": gated,
                "muted": is_muted,
                "missing_features": missing,
                "needs_days": spec.min_days,
                "fired": fired,
            })
        return {
            "as_of": as_of.isoformat(),
            "scope": scope.value,
            "days_of_history": ctx.days_of_history,
            "feature_count": len(ctx),
            "features": {
                k: v for k, v in sorted(ctx.items()) if not k.startswith("baseline.")
            },
            "baselines": {
                k: round(v, 4) for k, v in sorted(ctx.items())
                if k.startswith("baseline.")
            },
            "rules": rules,
        }


#: Module-level singleton, matching how the other services in this app are held.
engine = RecommendationEngine()
