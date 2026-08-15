"""Re-classify activity segments with the repaired categorizer, and record the
results as training labels.

Why this exists
---------------
The zero-shot embedding classifier reported ``(cosine + 1) / 2`` as its
confidence. That maps a cosine of 0.28 — a weak match by any standard — to
0.64, comfortably above the 0.30 acceptance threshold, so no prediction could
ever be rejected and the step was a bare argmax over eight labels. Browser
window titles ("Search", "Extensions - Comet", "Google Gemini - Comet") are
short strings of product nouns, and so is the label text for meetings ("google
meet, teams, zoom, webex, ..."), so meetings won that argmax on browser chrome
over and over: 3,797 Comet segments and 36% of all active time, filed as
meetings on similarities that peaked around 0.3.

``Categorizer`` now consults evidence before resemblance and holds the
embedding step to a real bar. This script applies that to segments already in
the database, which the fix cannot reach on its own — segments are categorized
once, at build time.

What it does
------------
1. Re-runs the categorizer over the selected segments and rewrites
   ``category`` / ``category_method`` / ``category_confidence``.
2. Recomputes ``focus_score`` for rows that already had one, because
   ``FocusScorer`` reads the category — a meetings label adds 0.1 to a
   segment's engagement signal, so 1,795 scored segments are currently carrying
   a bonus they did not earn.
3. Writes each new category into ``activity_segment_labels`` as a training row
   (``source='backfill'``), with the embedding built by the same code path the
   classifier uses at predict time.

On step 3: these are derived labels, not ground truth. A model trained on them
learns to imitate the rule layer, including wherever it is wrong. That is
deliberate — it generalises the host and chrome rules to segments the tables do
not name — but it is why the rows are stamped 'backfill' and why user
corrections must stay distinguishable from them.

Usage
-----
    python -m scripts.recategorize_segments --dry-run       # report only
    python -m scripts.recategorize_segments --apply
    python -m scripts.recategorize_segments --apply --scope all
    python -m scripts.recategorize_segments --apply --no-labels
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal  # noqa: E402
from app.models.db import ActivitySegmentLabelRecord, ActivitySegmentRecord  # noqa: E402
from app.services.categorizer import categorizer  # noqa: E402
from app.services.embedder import embedder  # noqa: E402
from app.services.focus_scorer import FocusScorer  # noqa: E402

# Rows are re-embedded one at a time by the categorizer; committing in batches
# keeps a failure from costing the whole run.
COMMIT_EVERY = 500


def select_segments(db, scope: str) -> List[ActivitySegmentRecord]:
    """Return the segments to re-classify.

    'mislabeled-meetings' is the default because it is the population the bug
    actually produced: the embedding classifier is the only thing that ever
    emitted this label, and it emitted it for browser chrome. 'all' re-runs
    every segment, which also picks up the rule-layer changes.
    """
    query = db.query(ActivitySegmentRecord)
    if scope == "mislabeled-meetings":
        query = query.filter(
            ActivitySegmentRecord.category == "meetings",
            ActivitySegmentRecord.category_method == "embedding",
        )
    elif scope != "all":
        raise ValueError(f"unknown scope {scope!r}")
    return query.order_by(ActivitySegmentRecord.start_time_utc).all()


def reclassify(
    segment: ActivitySegmentRecord,
) -> Tuple[Optional[str], Optional[str], Optional[float], Optional[List[float]]]:
    """Return the new (category, method, confidence, embedding) for a segment.

    The embedding is returned alongside so the training row stores the exact
    vector the classifier would score, rather than re-deriving it from
    differently-normalised text later.
    """
    category, method, confidence = categorizer.predict(segment)
    text = categorizer.build_text(segment)
    embedding = embedder.generate_embedding(text) if text else None
    return category, method, confidence, embedding


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run", action="store_true",
        help="report what would change without writing anything",
    )
    mode.add_argument(
        "--apply", action="store_true", help="write the changes",
    )
    parser.add_argument(
        "--scope", choices=("mislabeled-meetings", "all"),
        default="mislabeled-meetings",
        help="which segments to re-classify (default: mislabeled-meetings)",
    )
    parser.add_argument(
        "--no-labels", action="store_true",
        help="rewrite categories but do not write training labels",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="stop after N segments (for spot checks)",
    )
    parser.add_argument(
        "--samples", type=int, default=15,
        help="how many example changes to print (default: 15)",
    )
    parser.add_argument(
        "--train", action="store_true",
        help="train the supervised model on the stored labels afterwards. "
             "Writes regardless of --dry-run: it marks the labels it consumed "
             "as used_in_training.",
    )
    args = parser.parse_args()

    scorer = FocusScorer()
    db = SessionLocal()
    try:
        segments = select_segments(db, args.scope)
        if args.limit:
            segments = segments[: args.limit]
        print(f"Re-classifying {len(segments)} segments (scope={args.scope})\n")

        transitions: Counter = Counter()
        duration_moved: Counter = Counter()
        samples: List[str] = []
        changed = labels_written = focus_updated = 0

        for index, segment in enumerate(segments, start=1):
            old_category = segment.category
            new_category, method, confidence, embedding = reclassify(segment)

            transitions[(old_category, new_category)] += 1
            duration_moved[new_category] += segment.duration_sec

            if new_category != old_category:
                changed += 1
                if len(samples) < args.samples:
                    samples.append(
                        f"  {str(old_category):<10} -> {str(new_category):<14}"
                        f" [{str(method):<10}] {(segment.title or '')[:62]!r}"
                    )

            if args.apply:
                segment.category = new_category
                segment.category_method = method
                segment.category_confidence = confidence

                # Only rows that already carried a score are rescored; inventing
                # scores for the rest is a different job than this one.
                if segment.focus_score is not None:
                    signals = scorer.create_signals_from_segment(segment)
                    segment.focus_score = scorer.calculate_focus_score(
                        signals, segment.duration_sec
                    )
                    focus_updated += 1

                if not args.no_labels and new_category and embedding:
                    db.add(
                        ActivitySegmentLabelRecord(
                            id=str(uuid.uuid4()),
                            segment_id=segment.id,
                            user_id=segment.user_id,
                            device_id=segment.device_id,
                            model_name=embedder.model_name,
                            model_version=embedder.model_version,
                            dimensions=embedder.dimensions,
                            embedding=json.dumps(embedding),
                            correct_label=new_category,
                            source="backfill",
                        )
                    )
                    labels_written += 1

                if index % COMMIT_EVERY == 0:
                    db.commit()
                    print(f"  ... {index}/{len(segments)} committed")

        if args.apply:
            db.commit()

        _report(transitions, duration_moved, samples, changed, len(segments))
        if args.apply:
            print(f"\nApplied. focus_score recomputed for {focus_updated} segments; "
                  f"{labels_written} training labels written (source='backfill').")
        else:
            print("\nDry run — nothing written. Re-run with --apply.")

        if args.train:
            _train()
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _train() -> None:
    """Train the supervised classifier on the stored labels and report."""
    print("\nTraining supervised model on stored labels...")
    summary = categorizer.train_from_labels()
    if not summary.get("trained"):
        print(f"  Not trained: {summary.get('error', 'not enough usable labels')}")
        return
    accuracy = summary.get("holdout_accuracy")
    accuracy_text = "n/a" if accuracy is None else f"{accuracy:.1%}"
    print(f"  Trained on {summary['samples']} labels "
          f"({summary['skipped']} skipped), classes: {', '.join(summary['classes'])}")
    print(f"  Held-out agreement with stored labels: {accuracy_text}")
    print("  Note: the model is held in memory by this process only — it is not")
    print("  persisted, so the running backend still classifies by rules and")
    print("  embeddings until something trains it there too.")


def _report(
    transitions: Counter,
    duration_moved: Counter,
    samples: List[str],
    changed: int,
    total: int,
) -> None:
    print("Transitions (old -> new):")
    for (old, new), count in transitions.most_common():
        marker = " " if old == new else "*"
        print(f" {marker} {str(old):<10} -> {str(new):<14} {count:>6}")

    print("\nTime by resulting category:")
    total_sec = sum(duration_moved.values()) or 1
    for category, seconds in duration_moved.most_common():
        share = 100.0 * seconds / total_sec
        print(f"   {str(category):<14} {seconds/3600:7.2f} h  ({share:5.1f}%)")

    if samples:
        print("\nExamples:")
        for line in samples:
            print(line)

    print(f"\n{changed} of {total} segments changed category.")


if __name__ == "__main__":
    raise SystemExit(main())
