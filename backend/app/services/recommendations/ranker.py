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

MODEL_STORE_FORMAT = 2


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
        rows = db.execute(text("""
            SELECT e.rule_id, e.action, e.hour_of_day, e.weekday,
                   r.severity, r.section, r.score
            FROM recommendation_events e
            JOIN recommendations r ON r.id = e.recommendation_id
            WHERE e.action IN ('applied', 'dismissed')
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

            holdout = self._holdout_accuracy(X, y)
            self._model = model
            self._trained_at = local_now().isoformat()
            self._holdout = holdout

        summary = {
            "trained": True,
            "rows": len(rows),
            "applied": positives,
            "dismissed": negatives,
            "rules": len(rule_ids),
            "holdout_accuracy": holdout,
            "trained_at": self._trained_at,
        }
        self._save(summary)
        logger.info("Ranker trained: %s", summary)
        return summary

    @staticmethod
    def _holdout_accuracy(X: "np.ndarray", y: "np.ndarray") -> float | None:
        """Accuracy on a held-out slice, or None when the split is not viable.

        Reported rather than assumed, for the same reason the categoriser
        reports its own: a ranking model that cannot beat chance should be
        visible as such rather than quietly reordering the panel.
        """
        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.model_selection import train_test_split

            if len(y) < 30 or len(np.unique(y)) < 2:
                return None
            X_tr, X_te, y_tr, y_te = train_test_split(
                X, y, test_size=0.3, random_state=42, stratify=y
            )
            if len(np.unique(y_tr)) < 2:
                return None
            probe = LogisticRegression(
                max_iter=1000, solver="lbfgs", random_state=42,
                class_weight="balanced",
            )
            probe.fit(X_tr, y_tr)
            return float(probe.score(X_te, y_te))
        except Exception:
            return None

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
            logger.info(
                "Loaded ranker (trained %s, %s rows, holdout %s)",
                self._trained_at, payload.get("rows"), self._holdout,
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
            "rules_known": len(self._rule_index),
        }


ranker = RecommendationRanker()
