from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2

from src.emotion import EmotionPredictor, prediction_to_plain_dict
from src.pipeline import SmartDeskPipeline


CLASSES = ["Happy", "Neutral", "Confusion"]


def main() -> None:
    args = parse_args()
    if args.label not in CLASSES:
        raise ValueError(f"--label must be one of: {', '.join(CLASSES)}")

    predictor = EmotionPredictor()
    counts = {label: 0 for label in CLASSES}
    counts["NO_FACE"] = 0
    probability_sums = {label: 0.0 for label in CLASSES}
    rows: list[dict[str, object]] = []

    capture = cv2.VideoCapture(args.camera_index)
    if not capture.isOpened():
        raise RuntimeError(f"Could not open webcam index {args.camera_index}")

    print(f"Manual label: {args.label}")
    print(f"Hold the {args.label} expression for {args.seconds:.1f} seconds.")
    print("Starting in 3 seconds...")
    time.sleep(3.0)
    print("Recording now.")

    started = time.time()
    next_sample_at = started
    sample_index = 0

    try:
        with SmartDeskPipeline() as pipeline:
            pipeline.emotion_predictor = predictor
            while time.time() - started < args.seconds:
                ok, frame = capture.read()
                if not ok:
                    continue

                now = time.time()
                if now < next_sample_at:
                    continue
                next_sample_at = now + (1.0 / args.sample_fps)
                sample_index += 1

                update = pipeline.process_frame(frame, timestamp=float(sample_index))
                result = update.frame_result
                if result.emotion is None:
                    counts["NO_FACE"] += 1
                    rows.append(
                        {
                            "sample": sample_index,
                            "face_detected": result.detection.face_detected,
                            "predicted": "NO_FACE",
                        }
                    )
                    print(f"{sample_index:03d} NO_FACE")
                    continue

                plain = prediction_to_plain_dict(result.emotion)
                predicted = str(plain["top_class"])
                counts[predicted] += 1
                probabilities = plain["probabilities"]
                for label in CLASSES:
                    probability_sums[label] += float(probabilities[label])

                rows.append(
                    {
                        "sample": sample_index,
                        "face_detected": result.detection.face_detected,
                        "predicted": predicted,
                        "state": plain["state"],
                        "happy": probabilities["Happy"],
                        "neutral": probabilities["Neutral"],
                        "confusion": probabilities["Confusion"],
                    }
                )
                print(
                    f"{sample_index:03d} pred={predicted:<9} state={plain['state']:<10} "
                    f"H={probabilities['Happy']:.3f} "
                    f"N={probabilities['Neutral']:.3f} "
                    f"C={probabilities['Confusion']:.3f}"
                )
    finally:
        capture.release()

    valid_count = sum(counts[label] for label in CLASSES)
    correct_count = counts[args.label]
    average_probabilities = {
        label: (probability_sums[label] / valid_count if valid_count else 0.0)
        for label in CLASSES
    }
    summary = {
        "manual_label": args.label,
        "seconds": args.seconds,
        "sample_fps": args.sample_fps,
        "valid_predictions": valid_count,
        "no_face": counts["NO_FACE"],
        "correct": correct_count,
        "accuracy": correct_count / valid_count if valid_count else 0.0,
        "prediction_counts": counts,
        "average_probabilities": average_probabilities,
    }

    print("\nSummary")
    print(json.dumps(summary, indent=2))

    if args.output:
        output_path = args.output.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps({"summary": summary, "samples": rows}, indent=2),
            encoding="utf-8",
        )
        print(f"Saved: {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a 20-second live SmartDesk emotion test.")
    parser.add_argument("--label", required=True, choices=CLASSES)
    parser.add_argument("--seconds", type=float, default=20.0)
    parser.add_argument("--sample-fps", type=float, default=2.0)
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    main()
