"""Validate detected events against expert-annotated ground truth.

Computes standard detection metrics (precision, recall, F1, sensitivity,
specificity) by matching pipeline-detected events to manually annotated
events from real recordings.

Annotation format (CSV):
    timestamp,duration,channel,event_type,annotator
    12.345,0.5,5,SW,Dan
    13.001,0.1,5,IED,Dan

Usage:
    from dnb.validation.ground_truth import validate, load_annotations

    annotations = load_annotations("annotations.csv")
    detections = pipeline.run_offline()
    report = validate(detections, annotations)
    print(report.summary())
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from dnb.core.types import Event, EventType

logger = logging.getLogger(__name__)


@dataclass
class Annotation:
    """A single ground truth annotation.

    Attributes:
        timestamp: Event time in seconds from recording start.
        duration: Event duration in seconds.
        channel: Channel ID.
        event_type: String label (e.g. 'SW', 'IED', 'spindle').
        annotator: Who made the annotation.
    """
    timestamp: float
    duration: float
    channel: int
    event_type: str
    annotator: str = ""


@dataclass
class MatchedEvent:
    """A detection matched to a ground truth annotation."""
    detection: Event
    annotation: Annotation
    time_error: float  # seconds (detection.timestamp - annotation.timestamp)


@dataclass
class ValidationReport:
    """Full validation report with per-type and aggregate metrics.

    Attributes:
        matched: Detections correctly matched to ground truth.
        false_positives: Detections with no matching annotation.
        false_negatives: Annotations with no matching detection.
        metrics: Dict of computed metrics.
        event_details: Per-event detail records for inspection.
    """
    matched: list[MatchedEvent] = field(default_factory=list)
    false_positives: list[Event] = field(default_factory=list)
    false_negatives: list[Annotation] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    event_details: list[dict[str, Any]] = field(default_factory=list)

    def _compute_metrics(self) -> None:
        """Compute precision, recall, F1, sensitivity, specificity."""
        tp = len(self.matched)
        fp = len(self.false_positives)
        fn = len(self.false_negatives)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)
               if (precision + recall) > 0 else 0.0)

        # Sensitivity = recall (true positive rate)
        sensitivity = recall

        # Specificity requires true negatives — we approximate by counting
        # IED annotations that were NOT detected as SW (i.e. correctly
        # rejected).  If no IED annotations exist, specificity is N/A.
        self.metrics = {
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "sensitivity": sensitivity,
        }

        if self.matched:
            errors = [m.time_error for m in self.matched]
            self.metrics["timing_error_mean"] = float(np.mean(errors))
            self.metrics["timing_error_std"] = float(np.std(errors))
            self.metrics["timing_error_abs_mean"] = float(np.mean(np.abs(errors)))

    def summary(self) -> str:
        """Return a human-readable summary string."""
        self._compute_metrics()
        m = self.metrics
        lines = [
            "=" * 60,
            "VALIDATION REPORT",
            "=" * 60,
            f"  True positives:   {m['true_positives']}",
            f"  False positives:  {m['false_positives']}",
            f"  False negatives:  {m['false_negatives']}",
            f"  Precision:        {m['precision']:.3f}",
            f"  Recall:           {m['recall']:.3f}",
            f"  F1:               {m['f1']:.3f}",
            f"  Sensitivity:      {m['sensitivity']:.3f}",
        ]
        if "timing_error_mean" in m:
            lines.extend([
                f"  Timing error:     {m['timing_error_mean']*1000:.1f} ± "
                f"{m['timing_error_std']*1000:.1f} ms",
                f"  |Timing error|:   {m['timing_error_abs_mean']*1000:.1f} ms",
            ])
        lines.append("=" * 60)
        return "\n".join(lines)

    def save(self, path: str | Path) -> None:
        """Save the report to a JSON file."""
        self._compute_metrics()
        path = Path(path)

        data = {
            "metrics": self.metrics,
            "matched": [
                {
                    "detection_time": m.detection.timestamp,
                    "annotation_time": m.annotation.timestamp,
                    "annotation_type": m.annotation.event_type,
                    "channel": m.detection.channel_id,
                    "time_error_ms": m.time_error * 1000,
                    "detection_phase": m.detection.metadata.get("phase"),
                    "detection_amplitude": m.detection.metadata.get("amplitude"),
                }
                for m in self.matched
            ],
            "false_positives": [
                {
                    "detection_time": e.timestamp,
                    "channel": e.channel_id,
                    "type": e.event_type.name,
                    "phase": e.metadata.get("phase"),
                    "amplitude": e.metadata.get("amplitude"),
                }
                for e in self.false_positives
            ],
            "false_negatives": [
                {
                    "annotation_time": a.timestamp,
                    "channel": a.channel,
                    "type": a.event_type,
                    "annotator": a.annotator,
                }
                for a in self.false_negatives
            ],
            "event_details": self.event_details,
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info("Validation report saved to %s", path)

    def save_npz(self, path: str | Path) -> None:
        """Save the report to a .npz file for analysis in numpy."""
        self._compute_metrics()
        path = Path(path)

        arrays = {}
        if self.matched:
            arrays["matched_detection_times"] = np.array(
                [m.detection.timestamp for m in self.matched])
            arrays["matched_annotation_times"] = np.array(
                [m.annotation.timestamp for m in self.matched])
            arrays["matched_timing_errors"] = np.array(
                [m.time_error for m in self.matched])
            arrays["matched_annotation_types"] = np.array(
                [m.annotation.event_type for m in self.matched])

        if self.false_positives:
            arrays["fp_times"] = np.array(
                [e.timestamp for e in self.false_positives])

        if self.false_negatives:
            arrays["fn_times"] = np.array(
                [a.timestamp for a in self.false_negatives])
            arrays["fn_types"] = np.array(
                [a.event_type for a in self.false_negatives])

        np.savez(str(path), **arrays)
        logger.info("Validation data saved to %s", path)


def load_annotations(
    path: str | Path,
    event_types: list[str] | None = None,
) -> list[Annotation]:
    """Load ground truth annotations from a CSV file.

    Expected CSV columns: timestamp, duration, channel, event_type, annotator
    (header row required).  Additional columns are ignored.

    Args:
        path: Path to the CSV file.
        event_types: If given, only load annotations with these types
            (e.g. ['SW', 'IED']).

    Returns:
        List of Annotation objects sorted by timestamp.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Annotation file not found: {path}")

    annotations = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ann = Annotation(
                timestamp=float(row["timestamp"]),
                duration=float(row.get("duration", 0.0)),
                channel=int(row.get("channel", 0)),
                event_type=row.get("event_type", "SW").strip(),
                annotator=row.get("annotator", "").strip(),
            )
            if event_types is None or ann.event_type in event_types:
                annotations.append(ann)

    annotations.sort(key=lambda a: a.timestamp)
    logger.info(
        "Loaded %d annotations from %s (types: %s)",
        len(annotations), path.name,
        sorted(set(a.event_type for a in annotations)),
    )
    return annotations


def validate(
    detections: list[Event],
    annotations: list[Annotation],
    time_tolerance: float = 0.05,
    target_annotation_type: str = "SW",
) -> ValidationReport:
    """Match detections to annotations and compute metrics.

    Uses greedy nearest-neighbour matching: for each detection, find the
    closest unmatched annotation within time_tolerance.  Detections
    matched to target_annotation_type count as true positives.  Detections
    matched to other types (e.g. IED) are logged in event_details for
    specificity analysis.

    Args:
        detections: List of detected events from the pipeline.
        annotations: List of ground truth annotations.
        time_tolerance: Maximum time difference (seconds) for a match.
        target_annotation_type: Which annotation type counts as a true
            detection (default "SW").

    Returns:
        ValidationReport with matched, false positive, false negative lists
        and computed metrics.
    """
    report = ValidationReport()

    if not detections or not annotations:
        if not detections:
            report.false_negatives = [a for a in annotations
                                       if a.event_type == target_annotation_type]
        report._compute_metrics()
        return report

    # Sort both by timestamp
    det_sorted = sorted(detections, key=lambda e: e.timestamp)
    ann_sorted = sorted(annotations, key=lambda a: a.timestamp)

    # Track which annotations have been matched
    ann_matched = [False] * len(ann_sorted)
    ann_times = np.array([a.timestamp for a in ann_sorted])

    for det in det_sorted:
        # Find the closest unmatched annotation
        time_diffs = np.abs(ann_times - det.timestamp)

        # Mask already-matched annotations
        for idx in range(len(ann_sorted)):
            if ann_matched[idx]:
                time_diffs[idx] = np.inf

        best_idx = int(np.argmin(time_diffs))
        best_diff = time_diffs[best_idx]

        if best_diff <= time_tolerance:
            ann = ann_sorted[best_idx]
            ann_matched[best_idx] = True

            match = MatchedEvent(
                detection=det,
                annotation=ann,
                time_error=det.timestamp - ann.timestamp,
            )

            detail = {
                "detection_time": det.timestamp,
                "annotation_time": ann.timestamp,
                "annotation_type": ann.event_type,
                "channel": det.channel_id,
                "is_target": ann.event_type == target_annotation_type,
                "time_error_ms": (det.timestamp - ann.timestamp) * 1000,
            }
            detail.update({
                k: v for k, v in det.metadata.items()
                if k != "raw_window"  # don't serialise large arrays
            })

            if ann.event_type == target_annotation_type:
                report.matched.append(match)
            else:
                # Detection matched to wrong type (e.g. detected SW but
                # ground truth says IED) — this is a false positive from
                # the perspective of SW detection.
                report.false_positives.append(det)
                detail["false_positive_reason"] = (
                    f"Matched to {ann.event_type} instead of {target_annotation_type}"
                )

            report.event_details.append(detail)
        else:
            # No matching annotation — false positive
            report.false_positives.append(det)
            report.event_details.append({
                "detection_time": det.timestamp,
                "channel": det.channel_id,
                "false_positive_reason": "No matching annotation",
                **{k: v for k, v in det.metadata.items() if k != "raw_window"},
            })

    # Unmatched target annotations are false negatives
    for idx, ann in enumerate(ann_sorted):
        if not ann_matched[idx] and ann.event_type == target_annotation_type:
            report.false_negatives.append(ann)

    # Count IED annotations that were NOT detected — these are true negatives
    # for specificity calculation
    ied_annotations = [a for a in ann_sorted if a.event_type != target_annotation_type]
    ied_detected = sum(
        1 for idx, a in enumerate(ann_sorted)
        if ann_matched[idx] and a.event_type != target_annotation_type
    )
    ied_not_detected = len(ied_annotations) - ied_detected

    report._compute_metrics()

    # Add specificity if we have IED data
    if ied_annotations:
        specificity = ied_not_detected / len(ied_annotations)
        report.metrics["specificity"] = specificity
        report.metrics["true_negatives"] = ied_not_detected
        report.metrics["ied_total"] = len(ied_annotations)
        report.metrics["ied_falsely_detected"] = ied_detected

    return report
