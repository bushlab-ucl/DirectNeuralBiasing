"""Validate detected events against expert-annotated ground truth.

Computes standard detection metrics (precision, recall, F1) by matching
pipeline-detected events to manually annotated events from real recordings.
"""

from __future__ import annotations

# TODO: Implement ground truth validation
#
# Plan:
#   - load_annotations(path) -> list[Event]
#       Load expert annotations from CSV/JSON format
#       Expected columns: timestamp, duration, channel, event_type, annotator
#
#   - match_events(detected, ground_truth, time_tolerance=0.05)
#       Hungarian matching between detected and ground truth events
#       Returns: matched_pairs, false_positives, false_negatives
#
#   - compute_metrics(matched, fp, fn) -> dict
#       precision = len(matched) / (len(matched) + len(fp))
#       recall = len(matched) / (len(matched) + len(fn))
#       f1 = 2 * precision * recall / (precision + recall)
#       timing_error_mean, timing_error_std
#
#   - validation_report(detected_path, annotation_path, config) -> dict
#       Full validation report per event type and per channel
