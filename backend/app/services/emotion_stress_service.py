"""Derive a stress score from recorded emotion blocks.

The detector emits four classes — Angry, Happy, Neutral, Surprise — as mean
probabilities per 15-minute block. Turning that into "stress" is an
interpretation, so the one used here is written down rather than buried in a
magic constant, and lives in one place so the Dashboard tile and the Insights
chart can never drift into meaning different things.

The mapping follows the valence-arousal view of affect:

  Angry     negative valence, high arousal   -> stress
  Surprise  ambiguous valence, high arousal   -> partial; arousal without a
                                                 clear sign is weak evidence
  Happy     positive valence                  -> relief; actively subtracts,
                                                 so 30% angry alongside 60%
                                                 happy is not read the same as
                                                 30% angry alongside 60% neutral
  Neutral   the baseline                      -> contributes nothing either way

Three things a plain weighted sum gets wrong, and what is done instead:

1. A linear sum has no calibrated middle. Tension is pushed through a logistic
   so an all-neutral block lands at a low-but-nonzero resting score rather than
   a hard zero, and the interesting range is spread across the middle of the
   scale instead of bunched at the bottom.

2. Short blocks are noisy. A block that processed twelve frames is far weaker
   evidence than one that processed nine hundred, so each block is shrunk
   toward the resting baseline in proportion to how much it actually saw.

3. Blocks are not equal in length. Partial blocks exist — the aggregate weights
   by observed minutes and confidence together, so a two-minute tail cannot
   swing a day.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass


# Per-emotion contribution to affective tension.
W_ANGRY = 1.0
W_SURPRISE = 0.25
W_HAPPY = 0.25

# Logistic calibration. MIDPOINT is the tension that reads as 50/100; K sets how
# sharply the score moves around it.
LOGISTIC_K = 6.0
LOGISTIC_MIDPOINT = 0.25

# Frames at which a block is treated as fully trustworthy. The detector runs one
# inference a second, so this is about a minute of observed face time.
CONFIDENCE_FRAMES = 60.0

# Where an all-neutral block sits: calm, not "no stress at all".
RESTING_SCORE = 1.0 / (1.0 + math.exp(LOGISTIC_K * LOGISTIC_MIDPOINT))


@dataclass(frozen=True)
class StressPoint:
    block_start_time: str
    block_end_time: str
    stress: int
    confidence: float
    processed_frame_count: int
    duration_minutes: float
    dominant_emotion: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class StressSummary:
    score: int | None
    observed_minutes: float
    block_count: int
    driver: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def _tension(scores: dict) -> float:
    """Signed affective tension for one block, before calibration."""
    return (
        W_ANGRY * float(scores.get("Angry", 0.0))
        + W_SURPRISE * float(scores.get("Surprise", 0.0))
        - W_HAPPY * float(scores.get("Happy", 0.0))
    )


def _calibrate(tension: float) -> float:
    return 1.0 / (1.0 + math.exp(-LOGISTIC_K * (tension - LOGISTIC_MIDPOINT)))


def block_confidence(processed_frame_count: int) -> float:
    """0..1 — how much this block's frame count justifies trusting it."""
    frames = max(0, int(processed_frame_count))
    return frames / (frames + CONFIDENCE_FRAMES)


def block_stress(block: dict) -> float | None:
    """Stress for one block on a 0..1 scale, or None if it observed nothing."""
    frames = int(block.get("processed_frame_count") or 0)
    if frames <= 0:
        return None

    raw = _calibrate(_tension(block.get("emotion_scores") or {}))
    confidence = block_confidence(frames)
    # Shrink toward the resting baseline: weak evidence should not produce a
    # confident-looking extreme.
    return RESTING_SCORE + confidence * (raw - RESTING_SCORE)


def _driver(blocks: list[dict]) -> str | None:
    """Which emotion contributed most tension across the period."""
    totals = {"Angry": 0.0, "Surprise": 0.0, "Happy": 0.0}
    for block in blocks:
        frames = int(block.get("processed_frame_count") or 0)
        if frames <= 0:
            continue
        scores = block.get("emotion_scores") or {}
        totals["Angry"] += W_ANGRY * float(scores.get("Angry", 0.0)) * frames
        totals["Surprise"] += W_SURPRISE * float(scores.get("Surprise", 0.0)) * frames
        totals["Happy"] += W_HAPPY * float(scores.get("Happy", 0.0)) * frames

    if not any(totals.values()):
        return None
    return max(totals, key=totals.get)


def stress_series(blocks: list[dict]) -> list[StressPoint]:
    """Per-block stress points, oldest first, skipping blocks that saw no face."""
    points: list[StressPoint] = []
    for block in sorted(blocks, key=lambda b: b.get("block_start_time") or ""):
        stress = block_stress(block)
        if stress is None:
            continue
        points.append(
            StressPoint(
                block_start_time=block.get("block_start_time", ""),
                block_end_time=block.get("block_end_time", ""),
                stress=round(stress * 100),
                confidence=round(block_confidence(block.get("processed_frame_count") or 0), 3),
                processed_frame_count=int(block.get("processed_frame_count") or 0),
                duration_minutes=float(block.get("duration_minutes") or 0.0),
                dominant_emotion=block.get("dominant_emotion") or "Unknown",
            )
        )
    return points


def stress_summary(blocks: list[dict]) -> StressSummary:
    """One score for the period, weighted by observed minutes and confidence."""
    weighted_total = 0.0
    weight_total = 0.0
    observed_minutes = 0.0
    counted = 0

    for block in blocks:
        stress = block_stress(block)
        if stress is None:
            continue
        minutes = float(block.get("duration_minutes") or 0.0)
        weight = minutes * block_confidence(block.get("processed_frame_count") or 0)
        if weight <= 0:
            continue
        weighted_total += stress * weight
        weight_total += weight
        observed_minutes += minutes
        counted += 1

    if weight_total <= 0:
        return StressSummary(None, 0.0, 0, None)

    return StressSummary(
        score=round((weighted_total / weight_total) * 100),
        observed_minutes=round(observed_minutes, 1),
        block_count=counted,
        driver=_driver(blocks),
    )
