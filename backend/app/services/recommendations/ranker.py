"""The learned ranking layer.

Predicts whether a card will be accepted, from the feedback already recorded,
and folds that into the surfacing score. A rule whose Start Break is always
dismissed sinks on its own rather than needing a threshold retuned by hand.

Deliberately the last component built: with no feedback it has nothing to learn
from, and a ranker trained on twelve rows is worse than no ranker at all. Until
the floor is cleared it returns a flat 1.0 and the engine behaves exactly as it
did before this file existed.

Mirrors :class:`Categorizer` throughout — same joblib persistence, same format
guard, same "refuse the file rather than predict from nonsense" behaviour.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.time import local_now
from app.services.recommendations.stats import (
    PlattScaling,
    expected_calibration_error,
    reliability_curve,
)

logger = logging.getLogger("smartdesk.recommendations.ranker")

#: Feedback rows needed before the model is allowed to influence anything.
#: Below this the coefficients are fitted to noise, and the cost of being wrong
#: is suppressing a card the user would have wanted.
MIN_TRAINING_ROWS = 40

#: Both outcomes must be represented. A user who has only ever pressed Applied
#: gives the model nothing to separate, and it would happily predict 1.0 for
#: everything.
MIN_PER_CLASS = 8

#: How far the learned term may move a score. Bounded on purpose: the ranker is
#: an adjustment to a rule-based judgement, not a replacement for it, and an
#: unbounded multiplier would let a handful of dismissals bury a high-severity
#: safety rule permanently.
MIN_MULTIPLIER = 0.5
MAX_MULTIPLIER = 1.5

#: Bumped for the calibrator. An older file has no Platt parameters, and the
#: format guard below refuses it rather than scoring through an identity map it
#: would have no way to know was missing — the engine falls back to a flat 1.0
#: until the next training pass, which is the same behaviour as a cold start.
MODEL_STORE_FORMAT = 3


def _cyclical(value: float, period: float) -> tuple[float, float]:
    """Encode an hour or weekday as a point on a circle.

    Hour 23 and hour 0 are adjacent, which a raw integer feature cannot express
    — it puts them at opposite ends of the range and asks a linear model to
    treat 23 as maximally unlike 0.
    """
    angle = 2.0 * np.pi * value / period
    return float(np.sin(angle)), float(np.cos(angle))


class RecommendationRanker:
    """Learns which recommendations get acted on."""

    SEVERITIES = ("low", "medium", "high")
    SECTIONS = ("immediate", "insight", "planning", "behaviour")

    def __init__(self) -> None:
        self._model = None
        self._rule_index: dict[str, int] = {}
        self._lock = threading.Lock()
        self._trained_at: str | None = None
        self._holdout: float | None = None
        self._holdout_basis: str = "none"
        self._platt = PlattScaling()
        self._ece_raw: float | None = None
        self._ece_calibrated: float | None = None
        self._reliability: list[dict] = []
        self._load()

    # ------------------------------------------------------------------ #
    # Features                                                            #
    # ------------------------------------------------------------------ #

    def _vector(
        self,
        rule_id: str,
        severity: str,
        section: str,
        hour: int,
        weekday: int,
        score: float,
    ) -> list[float]:
        rules = [0.0] * len(self._rule_index)
        index = self._rule_index.get(rule_id)
        if index is not None:
            rules[index] = 1.0

        severity_hot = [1.0 if severity == s else 0.0 for s in self.SEVERITIES]
        section_hot = [1.0 if section == s else 0.0 for s in self.SECTIONS]
        hour_sin, hour_cos = _cyclical(hour, 24.0)
        day_sin, day_cos = _cyclical(weekday, 7.0)

        return [
            *rules, *severity_hot, *section_hot,
            hour_sin, hour_cos, day_sin, day_cos, score,
        ]

    # ------------------------------------------------------------------ #
    # Scoring                                                             #
    # ------------------------------------------------------------------ #

    def multiplier(
        self,
        rule_id: str,
        severity: str,
        section: str,
        hour: int,
        weekday: int,
        score: float,
    ) -> float:
        """A bounded adjustment in [0.5, 1.5]. Exactly 1.0 when untrained."""
        with self._lock:
            if self._model is None:
                return 1.0
            try:
                vector = self._vector(rule_id, severity, section, hour, weekday, score)
                probability = float(self._model.predict_proba([vector])[0][1])
                # Calibrated before it is used, because the number is not only
                # ranked with — it is mapped linearly onto the multiplier band.
                # A raw 0.8 that really means 0.5 moves a card by more than the
                # evidence supports, and the band cannot tell the difference.
                if self._platt.fitted:
                    probability = self._platt.transform(probability)
            except Exception:
                # A rule added since the last training changes the vector width.
                # Falling back to neutral is correct: the model has no opinion
                # about a rule it has never seen.
                logger.debug("Ranker could not score %s; using 1.0", rule_id)
                return 1.0

        # Map an acceptance probability onto the multiplier band, centred so
        # that a coin-flip prediction leaves the rule-based score untouched.
        return MIN_MULTIPLIER + (MAX_MULTIPLIER - MIN_MULTIPLIER) * probability

    # ------------------------------------------------------------------ #
    # Training                                                            #
    # ------------------------------------------------------------------ #

    def train(self, db: Session) -> dict[str, Any]:
        """Fit on the recorded feedback. Returns a summary, trained or not."""
        # Ordered, because the holdout below is a temporal split and needs
        # the rows in the sequence they actually happened. ``created_at`` is
        # ISO-8601 text, which sorts lexicographically the same way it sorts
        # chronologically.
        rows = db.execute(text("""
            SELECT e.rule_id, e.action, e.hour_of_day, e.weekday,
                   r.severity, r.section, r.score
            FROM recommendation_events e
            JOIN recommendations r ON r.id = e.recommendation_id
            WHERE e.action IN ('applied', 'dismissed')
            ORDER BY e.created_at
        """)).mappings().all()

        if len(rows) < MIN_TRAINING_ROWS:
            return {
                "trained": False,
                "reason": f"{len(rows)} feedback rows, need {MIN_TRAINING_ROWS}",
                "rows": len(rows),
            }

        labels = [1 if row["action"] == "applied" else 0 for row in rows]
        positives = sum(labels)
        negatives = len(labels) - positives
        if positives < MIN_PER_CLASS or negatives < MIN_PER_CLASS:
            return {
                "trained": False,
                "reason": (
                    f"needs {MIN_PER_CLASS} of each outcome; have "
                    f"{positives} applied, {negatives} dismissed"
                ),
                "rows": len(rows),
            }

        rule_ids = sorted({row["rule_id"] for row in rows})
        with self._lock:
            self._rule_index = {rule: i for i, rule in enumerate(rule_ids)}
            vectors = [
                self._vector(
                    row["rule_id"], row["severity"] or "low",
                    row["section"] or "insight",
                    int(row["hour_of_day"] or 0), int(row["weekday"] or 0),
                    float(row["score"] or 0.0),
                )
                for row in rows
            ]

            from sklearn.linear_model import LogisticRegression

            X = np.array(vectors)
            y = np.array(labels)
            model = LogisticRegression(
                max_iter=1000, solver="lbfgs", random_state=42,
                # The two outcomes are rarely balanced — most cards are simply
                # never touched — and an unweighted fit buys its accuracy by
                # always predicting the majority.
                class_weight="balanced",
            )
            model.fit(X, y)

            holdout, basis = self._holdout_accuracy(X, y)
            calibration = self._calibrate(X, y)
            self._model = model
            self._trained_at = local_now().isoformat()
            self._holdout = holdout
            self._holdout_basis = basis

        summary = {
            "trained": True,
            "rows": len(rows),
            "applied": positives,
            "dismissed": negatives,
            "rules": len(rule_ids),
            "holdout_accuracy": holdout,
            "holdout_basis": basis,
            "calibrated": self._platt.fitted,
            "ece_raw": self._ece_raw,
            "ece_calibrated": self._ece_calibrated,
            "trained_at": self._trained_at,
        }
        summary.update(calibration)
        self._save(summary)
        logger.info("Ranker trained: %s", summary)
        return summary

    def _calibrate(self, X: "np.ndarray", y: "np.ndarray") -> dict:
        """Fit the score-to-probability map, and measure whether it helped.

        Fitted on the *later* slice, never on the rows the model trained on.
        Calibrating against data a model has already memorised measures how
        well it remembers, which is exactly the quantity that does not
        generalise — the model looks perfectly calibrated and is not.

        Reports ECE before and after so the improvement is visible rather than
        assumed. If the calibrated figure is no better, the honest reading is
        that the scores were already as good as this transform can make them.
        """
        self._platt = PlattScaling()
        self._ece_raw = self._ece_calibrated = None
        self._reliability = []
        try:
            from sklearn.linear_model import LogisticRegression

            cut = int(len(y) * 0.7)
            if cut < 10 or len(y) - cut < 10:
                return {"calibration": "too few rows to hold a calibration set"}
            if len(np.unique(y[:cut])) < 2 or len(np.unique(y[cut:])) < 2:
                return {"calibration": "a split arm carried only one outcome"}

            probe = LogisticRegression(
                max_iter=1000, solver="lbfgs", random_state=42,
                class_weight="balanced",
            )
            probe.fit(X[:cut], y[:cut])
            raw = [float(p) for p in probe.predict_proba(X[cut:])[:, 1]]
            actual = [bool(v) for v in y[cut:]]

            self._ece_raw = expected_calibration_error(raw, actual)
            if not self._platt.fit(raw, actual):
                return {"calibration": "Platt fit did not converge on this data"}
            adjusted = [self._platt.transform(p) for p in raw]
            self._ece_calibrated = expected_calibration_error(adjusted, actual)
            self._reliability = reliability_curve(adjusted, actual, bins=5)
            return {"calibration": "platt"}
        except Exception:
            logger.exception("Calibration failed; scores stay uncalibrated")
            self._platt = PlattScaling()
            return {"calibration": "failed"}

    @staticmethod
    def _holdout_accuracy(
        X: "np.ndarray", y: "np.ndarray"
    ) -> tuple[float | None, str]:
        """Balanced accuracy on the most recent slice, and the basis for it.

        Reported rather than assumed, for the same reason the categoriser
        reports its own: a ranking model that cannot beat chance should be
        visible as such rather than quietly reordering the panel.

        The split is *temporal* — train on the earlier 70% of feedback, test
        on the later 30% — because a random slice measures the wrong thing.
        Feedback is autocorrelated: a run of dismissals in one bad afternoon
        lands rows on both sides of a random split, so the model is scored on
        presses it effectively saw during training, and the figure comes out
        flattering. A temporal split asks the only question that matters in
        deployment: having learned from what the user did up to now, does the
        model predict what they do next?

        The metric is *balanced* accuracy — the mean of per-class recall —
        rather than raw accuracy. A temporal test arm cannot be stratified, so
        it is routinely lopsided (most cards are dismissed), and raw accuracy
        on a 90%-dismissed slice reads 0.90 for a model that has learned only
        to say "dismissed". Balanced accuracy sits at 0.5 for that model
        regardless of the skew, which is the honest floor.

        Returns ``(score, basis)`` where basis is ``"temporal"`` or ``"none"``
        when no viable split exists. There is deliberately no random-split
        fallback: a leaky number is worse than no number.
        """
        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.metrics import balanced_accuracy_score

            if len(y) < 30 or len(np.unique(y)) < 2:
                return None, "none"

            cut = int(len(y) * 0.7)
            X_tr, X_te = X[:cut], X[cut:]
            y_tr, y_te = y[:cut], y[cut:]

            # Both arms need both outcomes. Training on one class fits
            # nothing; testing on one class makes recall on the missing class
            # undefined and balanced accuracy meaningless.
            if len(np.unique(y_tr)) < 2 or len(np.unique(y_te)) < 2:
                return None, "none"

            probe = LogisticRegression(
                max_iter=1000, solver="lbfgs", random_state=42,
                class_weight="balanced",
            )
            probe.fit(X_tr, y_tr)
            return (
                float(balanced_accuracy_score(y_te, probe.predict(X_te))),
                "temporal",
            )
        except Exception:
            return None, "none"

    # ------------------------------------------------------------------ #
    # Persistence                                                         #
    # ------------------------------------------------------------------ #

    @property
    def _path(self) -> Path:
        return Path(settings.MODEL_STORE_DIR) / "recommendation_ranker.joblib"

    def _save(self, summary: dict[str, Any]) -> None:
        try:
            path = self._path
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "format": MODEL_STORE_FORMAT,
                "model": self._model,
                "rule_index": self._rule_index,
                "trained_at": self._trained_at,
                "holdout_accuracy": summary.get("holdout_accuracy"),
                "holdout_basis": summary.get("holdout_basis"),
                "platt": (
                    (self._platt.a, self._platt.b) if self._platt.fitted else None
                ),
                "ece_raw": self._ece_raw,
                "ece_calibrated": self._ece_calibrated,
                "reliability": self._reliability,
                "rows": summary.get("rows"),
            }
            # Temp-then-replace, so an interrupted save cannot leave a
            # half-written model that fails to load on the next start.
            tmp = path.with_suffix(".joblib.tmp")
            joblib.dump(payload, tmp)
            tmp.replace(path)
        except Exception:
            logger.exception("Could not persist the ranker")

    def _load(self) -> bool:
        path = self._path
        if not path.exists():
            return False
        try:
            payload = joblib.load(path)
            if payload.get("format") != MODEL_STORE_FORMAT:
                logger.warning(
                    "Ignoring ranker at %s: format %s, expected %s",
                    path, payload.get("format"), MODEL_STORE_FORMAT,
                )
                return False
            self._model = payload["model"]
            self._rule_index = payload.get("rule_index", {})
            self._trained_at = payload.get("trained_at")
            self._holdout = payload.get("holdout_accuracy")
            self._holdout_basis = str(payload.get("holdout_basis") or "none")
            platt = payload.get("platt")
            self._platt = PlattScaling()
            if platt:
                self._platt.a, self._platt.b = float(platt[0]), float(platt[1])
                self._platt.fitted = True
            self._ece_raw = payload.get("ece_raw")
            self._ece_calibrated = payload.get("ece_calibrated")
            self._reliability = payload.get("reliability") or []
            logger.info(
                "Loaded ranker (trained %s, %s rows, holdout %s on %s basis)",
                self._trained_at, payload.get("rows"), self._holdout,
                self._holdout_basis,
            )
            return True
        except Exception:
            logger.exception("Could not load the ranker at %s", path)
            return False

    def status(self) -> dict[str, Any]:
        return {
            "trained": self._model is not None,
            "trained_at": self._trained_at,
            "holdout_accuracy": self._holdout,
            "holdout_basis": self._holdout_basis,
            "calibrated": self._platt.fitted,
            "ece_raw": self._ece_raw,
            "ece_calibrated": self._ece_calibrated,
            "reliability": self._reliability,
            "rules_known": len(self._rule_index),
        }


ranker = RecommendationRanker()
