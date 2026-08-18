"""Read and write user preferences."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.db.preference import UserPreferenceRecord


# Consent for webcam capture. Absent means "not granted": emotion detection is
# opt-in, so a fresh install never opens the camera until someone says yes.
WEBCAM_EMOTION_CONSENT = "webcam_emotion_consent"

#: Prefix for "do not show me this rule again".
#:
#: Stored as ordinary preferences rather than in a table of their own. The
#: shape is exactly what this store is for — one flag, per user, keyed by name
#: — and a rule id is a name. A dedicated table would buy nothing but a
#: migration and a second thing to keep in sync.
RULE_MUTED_PREFIX = "rule_muted:"

#: Prefix for "evaluate this rule but do not show me the result".
#:
#: Shadow and mute are different instructions and must not share a key. Muted
#: means "stop computing this"; shadowed means "keep computing it, record what
#: it would have said, and keep it off my screen". A rule that is both is
#: muted, since not computing it is the stronger request.
RULE_SHADOW_PREFIX = "rule_shadow:"

#: Date before which recorded activity is excluded from personal baselines.
#:
#: "My habits changed, stop comparing me to who I was" is a legitimate request
#: and the engine had no answer to it — a new job or a new project makes thirty
#: days of history actively misleading, and every comparative rule keeps
#: measuring against a person who no longer exists.
#:
#: An exclusion date rather than a delete, because this table records a
#: *preference* and the activity data is not ours to destroy on a slider. It
#: also means the reset is reversible, which a deletion never is. The separate
#: question of erasing data on request is a real one and deliberately not
#: answered here.
BASELINE_EPOCH = "baseline_epoch"

#: Multiplier on the deviation bar the comparative rules use.
#:
#: The rules fire when a day sits more than 0.67 sigma from the median. Some
#: people want to hear about less than that and some about more, and the choice
#: is genuinely a preference rather than a fact about the data. Exposed as one
#: number over all of them rather than a slider per rule, which nobody would
#: use.
SENSITIVITY = "recommendation_sensitivity"

#: Bounds on that multiplier. Below the floor every day is remarkable and the
#: panel becomes noise; above the ceiling nothing short of a four-sigma day
#: registers and the engine goes quiet.
SENSITIVITY_MIN = 0.5
SENSITIVITY_MAX = 2.0


class PreferenceRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_bool(self, user_id: str, key: str, default: bool = False) -> bool:
        row = self.db.get(UserPreferenceRecord, (user_id, key))
        if row is None:
            return default
        return row.value == "true"

    def set_bool(self, user_id: str, key: str, value: bool) -> bool:
        stored = "true" if value else "false"
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        row = self.db.get(UserPreferenceRecord, (user_id, key))
        if row is None:
            self.db.add(
                UserPreferenceRecord(
                    user_id=user_id, key=key, value=stored, updated_at=now
                )
            )
        else:
            row.value = stored
            row.updated_at = now
        self.db.commit()
        return value

    # ------------------------------------------------------------------ #
    # Rule muting                                                         #
    # ------------------------------------------------------------------ #

    def muted_rules(self, user_id: str) -> set[str]:
        """Every rule this user has switched off.

        Read in one query per generation pass rather than one per rule. The
        engine asks this question against seventy-four specs on every tick,
        and a lookup each would put the preference table on the hot path for
        no reason — the answer changes when someone presses a button, not
        sixty times a minute.
        """
        rows = self.db.query(UserPreferenceRecord).filter(
            UserPreferenceRecord.user_id == user_id,
            UserPreferenceRecord.key.like(f"{RULE_MUTED_PREFIX}%"),
            UserPreferenceRecord.value == "true",
        ).all()
        return {row.key[len(RULE_MUTED_PREFIX):] for row in rows}

    def set_rule_muted(self, user_id: str, rule_id: str, muted: bool) -> bool:
        """Switch one rule off, or back on."""
        return self.set_bool(user_id, f"{RULE_MUTED_PREFIX}{rule_id}", muted)

    def is_rule_muted(self, user_id: str, rule_id: str) -> bool:
        return self.get_bool(user_id, f"{RULE_MUTED_PREFIX}{rule_id}")

    # ------------------------------------------------------------------ #
    # Shadow mode                                                         #
    # ------------------------------------------------------------------ #

    def shadowed_rules(self, user_id: str) -> set[str]:
        """Rules being evaluated silently. One query, as with mutes."""
        rows = self.db.query(UserPreferenceRecord).filter(
            UserPreferenceRecord.user_id == user_id,
            UserPreferenceRecord.key.like(f"{RULE_SHADOW_PREFIX}%"),
            UserPreferenceRecord.value == "true",
        ).all()
        return {row.key[len(RULE_SHADOW_PREFIX):] for row in rows}

    def set_rule_shadowed(self, user_id: str, rule_id: str, shadow: bool) -> bool:
        return self.set_bool(user_id, f"{RULE_SHADOW_PREFIX}{rule_id}", shadow)

    # ------------------------------------------------------------------ #
    # Baseline epoch and sensitivity                                      #
    # ------------------------------------------------------------------ #

    def get_text(self, user_id: str, key: str) -> str | None:
        row = self.db.get(UserPreferenceRecord, (user_id, key))
        return row.value if row is not None else None

    def set_text(self, user_id: str, key: str, value: str) -> str:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        row = self.db.get(UserPreferenceRecord, (user_id, key))
        if row is None:
            self.db.add(UserPreferenceRecord(
                user_id=user_id, key=key, value=value, updated_at=now
            ))
        else:
            row.value = value
            row.updated_at = now
        self.db.commit()
        return value

    def baseline_epoch(self, user_id: str) -> str | None:
        """``YYYY-MM-DD`` before which history is ignored, or None."""
        value = self.get_text(user_id, BASELINE_EPOCH)
        return value or None

    def set_baseline_epoch(self, user_id: str, date: str | None) -> str | None:
        """Set or clear the epoch. Clearing restores the full history."""
        self.set_text(user_id, BASELINE_EPOCH, date or "")
        return date or None

    def sensitivity(self, user_id: str) -> float:
        """How eager the comparative rules should be, as a multiplier on their
        deviation bar. 1.0 is the shipped behaviour; below 1 fires more often.

        Clamped rather than trusted: a zero would make every rule fire on every
        day and a negative one would invert them.
        """
        raw = self.get_text(user_id, SENSITIVITY)
        try:
            value = float(raw) if raw else 1.0
        except (TypeError, ValueError):
            value = 1.0
        return min(max(value, SENSITIVITY_MIN), SENSITIVITY_MAX)

    def set_sensitivity(self, user_id: str, value: float) -> float:
        clamped = min(max(float(value), SENSITIVITY_MIN), SENSITIVITY_MAX)
        self.set_text(user_id, SENSITIVITY, f"{clamped:.3f}")
        return clamped
