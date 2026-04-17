"""Validate detected events against ground truth annotations."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from dnb.core.types import Event

logger = logging.getLogger(__name__)


@dataclass
class Annotation:
    timestamp: float
    duration: float = 0.0
    channel: int = 0
    event_type: str = "SW"
    annotator: str = ""


@dataclass
class MatchedEvent:
    detection: Event
    annotation: Annotation
    time_error: float


@dataclass
class ValidationReport:
    matched: list[MatchedEvent] = field(default_factory=list)
    false_positives: list[Event] = field(default_factory=list)
    false_negatives: list[Annotation] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    def _compute_metrics(self) -> None:
        tp = len(self.matched)
        fp = len(self.false_positives)
        fn = len(self.false_negatives)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        self.metrics = {
            "true_positives": tp, "false_positives": fp, "false_negatives": fn,
            "precision": precision, "recall": recall, "f1": f1,
        }
        if self.matched:
            errors = [m.time_error for m in self.matched]
            self.metrics["timing_error_mean_ms"] = float(np.mean(errors)) * 1000
            self.metrics["timing_error_std_ms"] = float(np.std(errors)) * 1000
            self.metrics["timing_error_abs_mean_ms"] = float(np.mean(np.abs(errors))) * 1000

    def summary(self) -> str:
        self._compute_metrics()
        m = self.metrics
        lines = [
            "=" * 50, "VALIDATION REPORT", "=" * 50,
            f"  TP: {m['true_positives']}  FP: {m['false_positives']}  FN: {m['false_negatives']}",
            f"  Precision: {m['precision']:.3f}",
            f"  Recall:    {m['recall']:.3f}",
            f"  F1:        {m['f1']:.3f}",
        ]
        if "timing_error_mean_ms" in m:
            lines.append(f"  Timing:    {m['timing_error_mean_ms']:.1f} ± {m['timing_error_std_ms']:.1f} ms")
        lines.append("=" * 50)
        return "\n".join(lines)


def validate(
    detections: list[Event],
    annotations: list[Annotation],
    time_tolerance: float = 0.5,
    target_type: str = "SW",
) -> ValidationReport:
    report = ValidationReport()

    if not detections or not annotations:
        if not detections:
            report.false_negatives = [a for a in annotations if a.event_type == target_type]
        report._compute_metrics()
        return report

    det_sorted = sorted(detections, key=lambda e: e.timestamp)
    ann_sorted = sorted(annotations, key=lambda a: a.timestamp)
    ann_matched = [False] * len(ann_sorted)
    ann_times = np.array([a.timestamp for a in ann_sorted])

    for det in det_sorted:
        diffs = np.abs(ann_times - det.timestamp)
        for idx in range(len(ann_sorted)):
            if ann_matched[idx]:
                diffs[idx] = np.inf
        best_idx = int(np.argmin(diffs))
        if diffs[best_idx] <= time_tolerance:
            ann = ann_sorted[best_idx]
            ann_matched[best_idx] = True
            if ann.event_type == target_type:
                report.matched.append(MatchedEvent(
                    detection=det, annotation=ann,
                    time_error=det.timestamp - ann.timestamp,
                ))
            else:
                report.false_positives.append(det)
        else:
            report.false_positives.append(det)

    for idx, ann in enumerate(ann_sorted):
        if not ann_matched[idx] and ann.event_type == target_type:
            report.false_negatives.append(ann)

    report._compute_metrics()
    return report