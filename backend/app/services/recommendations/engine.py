"""Engine orchestration: gate, evaluate, score, dedup, cap, persist.

A rule firing is not yet a recommendation. The stages between them are what
separate a useful panel from seventy cards nobody reads, and they all run
before anything is written — so a busy tick costs the same number of database
writes as a quiet one, which is zero.
"""

from __future__ import annotations

import json
import logging
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
from app.services.recommendations.types import (
    SEVERITY_WEIGHT,
    FeatureContext,
    Finding,
    RuleSpec,
    Scope,
    Section,
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

    # ------------------------------------------------------------------ #
    # Generation                                                          #
    # ------------------------------------------------------------------ #

    def generate(
        self,
        db: Session,
        user_id: str,
        as_of: datetime | None = None,
        scopes: tuple[Scope, ...] = (Scope.LIVE, Scope.DAILY),
    ) -> int:
        """Run the requested scopes and persist what survives. Returns the count."""
        as_of = as_of or local_now()
        baselines = self.baselines(db, user_id, as_of)

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
            written += self._run_scope(db, scope, ctx, as_of)

        self._expire_stale(db, user_id, as_of)
        return written

    def _run_scope(
        self,
        db: Session,
        scope: Scope,
        ctx: FeatureContext,
        as_of: datetime,
    ) -> int:
        candidates = self._evaluate(REGISTRY[scope], ctx)
        if not candidates:
            return 0

        # Highest score first, then dedup and cap. Ordering before deduping
        # matters: when two rules share a dedup key the stronger finding is the
        # one that survives, not whichever happened to be registered first.
        candidates.sort(key=lambda item: item[2], reverse=True)

        # Two grouped reads for the whole family, replacing one cooldown query
        # per surviving candidate — a busy daily run issued seventeen of those,
        # each filtering on a column trio no index covered.
        local_date = as_of.strftime("%Y-%m-%d")
        last_fired = self._last_fired(db, ctx.user_id, REGISTRY[scope], as_of)
        # Seeding the seen set from what is already stored turns the common
        # duplicate — a rule that fired earlier today — into a set lookup
        # instead of a rendered record and a caught IntegrityError.
        seen_keys: set[str] = self._existing_keys(db, ctx.user_id, local_date)

        per_section: dict[Section, int] = {}
        staged: list[RecommendationRecord] = []

        for spec, finding, score in candidates:
            if finding.dedup_key in seen_keys:
                continue
            cap = SECTION_CAPS.get(spec.section, 3)
            if per_section.get(spec.section, 0) >= cap:
                continue
            if self._on_cooldown(last_fired, spec, as_of):
                continue
            record = self._build(spec, finding, score, ctx, as_of)
            if record is None:
                continue
            staged.append(record)
            seen_keys.add(finding.dedup_key)
            per_section[spec.section] = per_section.get(spec.section, 0) + 1

        return self._write(db, staged)

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
        return out

    @staticmethod
    def _score(spec: RuleSpec, finding: Finding, as_of: datetime | None = None) -> float:
        """Surfacing score: severity x confidence x effect x learned acceptance.

        Each term is bounded, so no single one can dominate. Effect enters
        through a gentle saturating curve rather than linearly — a finding
        three MADs out is meaningfully more urgent than one at one MAD, but
        thirty MADs is not thirty times more urgent than one, it is a
        measurement error.

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
    ) -> dict[str, str]:
        """When each rule in a family last fired, in one grouped read.

        Bounded by the longest cooldown in the family — nothing older than that
        could suppress anything, so there is no reason to read it. Comparison
        stays on the ISO strings the column already holds, exactly as the
        per-rule query did.
        """
        if not specs:
            return {}
        horizon = max(spec.cooldown for spec in specs)
        rows = db.execute(
            text("""
                SELECT rule_id, MAX(generated_at) AS last_at
                FROM recommendations
                WHERE user_id = :user_id AND generated_at >= :since
                GROUP BY rule_id
            """),
            {"user_id": user_id, "since": (as_of - horizon).isoformat()},
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
        """Everything still worth showing for a given local day."""
        return db.query(RecommendationRecord).filter(
            RecommendationRecord.user_id == user_id,
            RecommendationRecord.local_date == local_date,
            RecommendationRecord.status.in_(("active", "applied")),
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
        rules = []
        for spec in REGISTRY[scope]:
            missing = sorted(spec.requires - ctx.keys())
            gated = spec.gated(ctx)
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
