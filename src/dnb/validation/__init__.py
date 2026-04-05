"""Validation pipelines for DNB detection quality assessment.

- ground_truth: Match detections to expert annotations, compute metrics.
- synthetic: Generate test data with planted events at varying SNRs.
- compare: (stub) Rust vs Python parity checking.
"""

from dnb.validation.ground_truth import (
    Annotation,
    MatchedEvent,
    ValidationReport,
    load_annotations,
    validate,
)
from dnb.validation.synthetic import (
    generate_synthetic_recording,
    run_snr_sweep,
    save_debug_figures,
    save_synthetic,
)

__all__ = [
    "Annotation",
    "MatchedEvent",
    "ValidationReport",
    "generate_synthetic_recording",
    "load_annotations",
    "run_snr_sweep",
    "save_debug_figures",
    "save_synthetic",
    "validate",
]
