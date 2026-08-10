"""Apply hand-assigned categories to whole groups of segments.

Labelling through ``POST /segments/{id}/label`` does two-thirds of the job: it
stores a training row but never sets ``segment.category``, so a corrected
segment stays uncategorised in the timeline while quietly feeding the model.
And it takes one call per segment — the uncategorised backlog alone is 281
segments across 46 distinct windows.

This applies a label to every segment matching an (app_name, title) pair:

  * sets ``category``, ``category_method='user'`` and ``category_confidence=1.0``
    — the 'user' method is what stops the next rebuild from overwriting it;
  * writes one ``activity_segment_labels`` row per segment with
    ``source='user'``, weighted above backfilled labels during training;
  * recomputes ``focus_score`` where one already exists, since FocusScorer
    reads the category.

Scope decides how far a label travels. ``uncategorized`` (the default) touches
only segments with no category — the backlog someone actually reviewed.
``group`` applies the label to every segment sharing that window title, which
also overrides categories the classifier already assigned. That is right where a
stale URL produced a confident wrong answer — eight "fushiguro" segments filed
as ``learn`` because a handout9.pdf URL from another tab was attached to them —
and wrong where it would stamp 'user' on hundreds of correct labels nobody
looked at, freezing them against future reclassification.

Usage
-----
    python -m scripts.apply_labels --dry-run
    python -m scripts.apply_labels --apply
    python -m scripts.apply_labels --apply --scope group
    python -m scripts.apply_labels --apply --spec my_labels.json

The default spec is LABELS below. A JSON spec is a list of
``{"app": ..., "title": ..., "label": ..., "match": "exact"|"prefix"}``;
``app`` may be null to match any application.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import and_  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.db import ActivitySegmentLabelRecord, ActivitySegmentRecord  # noqa: E402
from app.services.categorizer import categorizer  # noqa: E402
from app.services.embedder import embedder  # noqa: E402
from app.services.focus_scorer import FocusScorer  # noqa: E402

# (app_name, title, label, match). app_name None matches any application.
# "prefix" matches titles starting with the given text, for windows whose title
# carries a changing suffix.
LABELS: List[tuple] = [
    # --- learn: coursework ---
    ("comet", "Statistical Inference Solutions and Explanations", "learn", "prefix"),
    ("chrome", "Prolog Clause Order", "learn", "prefix"),
    ("comet", "Mathematical Solutions: Gamma, Beta, Delta Functions", "learn", "prefix"),
    ("comet", "Illumination Models and Surface-Rendering Methods", "learn", "prefix"),
    ("comet", "3D Transformations  and Viewing", "learn", "prefix"),
    ("comet", "Hypothesis Testing Solutions Provided", "learn", "prefix"),
    ("comet", "Gamma Function Proofs and Evaluations", "learn", "prefix"),
    ("comet", "Fundamental Concepts of Computer Graphics", "learn", "prefix"),
    ("comet", "Computer Graphics Fundamental Concepts Summary", "learn", "prefix"),
    ("comet", "ANOVA and Regression Past Papers", "learn", "prefix"),
    ("comet", "Query Processing and Optimization Explained", "learn", "prefix"),
    ("chrome", "Answer scheme with detailed steps", "learn", "prefix"),
    # A Google Doc named "Cheat code"; the URL on these rows belongs to a
    # different tab entirely (youtube.com, claude.ai).
    ("comet", "Cheat code - Google Docs", "learn", "prefix"),

    # --- work: this project, and personal admin ---
    ("electron", "SmartDesk Desktop", "work", "exact"),
    ("electron", "smartdesk-frontend", "work", "exact"),
    ("electron", "Electron", "work", "exact"),
    ("electron", "electron", "work", "exact"),
    ("comet", "Aysha-Shahanee/smartdesk at FocusScore", "work", "prefix"),
    ("comet", "SmartDesk", "work", "prefix"),
    ("Antigravity IDE", "smartdesk - Antigravity IDE", "work", "prefix"),
    ("comet", "AI model implementation approach selection", "work", "prefix"),
    ("comet", "MY page | Aysha Shahanee", "work", "prefix"),
    ("comet", "Rise Up Mora", "work", "prefix"),
    # CV editing. The Moodle URL on these rows leaked from a background tab and
    # would otherwise file a job application under "learn".
    ("wps", None, "work", "any"),

    # --- entertainment ---
    # Anime. Currently filed as "learn" on the strength of a handout9.pdf URL
    # belonging to another tab.
    ("comet", "fushiguro", "entertainment", "prefix"),
    ("comet", "Buy led photo frame magic mirror", "entertainment", "prefix"),

    # --- system: browser and OS furniture ---
    ("comet", "Wormhole", "system", "prefix"),
    ("chrome", "Welcome", "system", "prefix"),
    ("chrome", "Sign in to continue to Claude", "system", "prefix"),
    ("comet", "comet", "system", "exact"),
    ("chrome", "www.google.com", "system", "prefix"),
    ("ShellExperienceHost", "Jump List for", "system", "prefix"),
    (None, "Select the extension directory.", "system", "exact"),
    ("explorer", "Downloads - File Explorer", "system", "exact"),
    ("comet", "online.uom.lk", "system", "prefix"),
    ("node", "Microsoft Visual C++ Runtime Library", "system", "exact"),
    ("comet", "127.0.0.1", "system", "prefix"),
    ("LiveCaptions", "Live Captions", "system", "exact"),
    ("PhoneExperienceHost", "Phone Link", "system", "exact"),
    ("explorer", "Task Switching", "system", "exact"),
]


def load_spec(path: Optional[str]) -> List[tuple]:
    if not path:
        return LABELS
    entries = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        (e.get("app"), e.get("title"), e["label"], e.get("match", "exact"))
        for e in entries
    ]


def query_group(db, app: Optional[str], title: Optional[str], match: str):
    filters = []
    if app is not None:
        filters.append(ActivitySegmentRecord.app_name == app)
    if match == "exact":
        filters.append(ActivitySegmentRecord.title == title)
    elif match == "prefix":
        filters.append(ActivitySegmentRecord.title.like(f"{title}%"))
    elif match != "any":
        raise ValueError(f"unknown match mode {match!r}")
    return db.query(ActivitySegmentRecord).filter(and_(*filters)).all()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="report only")
    mode.add_argument("--apply", action="store_true", help="write the labels")
    parser.add_argument("--spec", help="JSON label spec (defaults to LABELS)")
    parser.add_argument(
        "--scope", choices=("uncategorized", "group"), default="uncategorized",
        help="'uncategorized' (default) labels only segments with no category; "
             "'group' labels every segment sharing the title, overriding the "
             "classifier",
    )
    args = parser.parse_args()

    spec = load_spec(args.spec)
    for app, title, label, _match in spec:
        if label not in categorizer.PERSISTABLE_CATEGORIES:
            raise SystemExit(
                f"'{label}' is not a storable category "
                f"({app or 'any'} / {title}). Allowed: "
                f"{sorted(categorizer.PERSISTABLE_CATEGORIES)}"
            )

    scorer = FocusScorer()
    db = SessionLocal()
    try:
        total = corrections = focus_updated = 0
        seen: set = set()
        per_label: Dict[str, int] = {}

        print(f"{'segs':>5} {'was':>28}  ->  label")
        for app, title, label, match in spec:
            segments = query_group(db, app, title, match)
            segments = [s for s in segments if s.id not in seen]
            if args.scope == "uncategorized":
                skipped_labeled = sum(1 for s in segments if s.category is not None)
                segments = [s for s in segments if s.category is None]
            else:
                skipped_labeled = 0
            if not segments:
                note = (f"  ({skipped_labeled} already categorised, left alone)"
                        if skipped_labeled else "")
                print(f"{0:>5}  (no match) {app} / {title}{note}")
                continue

            was = {}
            for s in segments:
                was[s.category] = was.get(s.category, 0) + 1
            was_text = ", ".join(
                f"{str(k)}x{v}" for k, v in sorted(was.items(), key=lambda kv: -kv[1])
            )
            changed = sum(n for k, n in was.items() if k != label)
            marker = "*" if changed else " "
            note = f"  (+{skipped_labeled} categorised, left alone)" if skipped_labeled else ""
            print(f"{len(segments):>5} {was_text[:28]:>28} {marker}-> {label}"
                  f"   [{app or 'any'} / {title or 'any'}]{note}")

            total += len(segments)
            corrections += changed
            per_label[label] = per_label.get(label, 0) + len(segments)

            for s in segments:
                seen.add(s.id)
                if not args.apply:
                    continue
                s.category = label
                s.category_method = "user"
                s.category_confidence = 1.0
                if s.focus_score is not None:
                    s.focus_score = scorer.calculate_focus_score(
                        scorer.create_signals_from_segment(s), s.duration_sec
                    )
                    focus_updated += 1
                text = categorizer.build_text(s)
                if text:
                    db.add(
                        ActivitySegmentLabelRecord(
                            id=str(uuid.uuid4()),
                            segment_id=s.id,
                            user_id=s.user_id,
                            device_id=s.device_id,
                            model_name=embedder.model_name,
                            model_version=embedder.model_version,
                            dimensions=embedder.dimensions,
                            embedding=json.dumps(embedder.generate_embedding(text)),
                            correct_label=label,
                            source="user",
                        )
                    )

        if args.apply:
            db.commit()

        print(f"\n{total} segments matched; {corrections} had a different category before.")
        print("Resulting counts: " + ", ".join(
            f"{k}={v}" for k, v in sorted(per_label.items(), key=lambda kv: -kv[1])
        ))
        if args.apply:
            print(f"Applied as category_method='user'; "
                  f"focus_score recomputed for {focus_updated}.")
        else:
            print("Dry run — nothing written. Re-run with --apply.")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
