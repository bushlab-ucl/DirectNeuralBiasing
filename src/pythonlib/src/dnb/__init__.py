"""direct-neural-biasing — closed-loop neural signal processing.

Low-latency pipeline for real-time and offline neural signal processing
with Blackrock Cerebus devices. Uses wavelet-based convolution for
simultaneous amplitude and phase extraction across all frequency bands.

Quick start:

    from dnb import Pipeline, NPlaySource
    from dnb.modules import WaveletConvolution, EventDetector

    pipeline = Pipeline(
        source=NPlaySource(),
        modules=[
            WaveletConvolution(freq_min=1, freq_max=200, n_freqs=40),
            EventDetector(freq_range=(80, 250), threshold_std=3.0),
        ],
    )
    pipeline.on_event("ripple", lambda e: print(f"Ripple at {e.timestamp:.3f}s"))
    pipeline.run_live()
"""

from dnb.core.types import DataChunk, Event, EventType, PipelineConfig, WaveletResult
from dnb.engine.pipeline import Pipeline
from dnb.sources.cerebus import CerebusSource
from dnb.sources.file import FileSource
from dnb.sources.nplay import NPlaySource

__version__ = "0.1.0"

__all__ = [
    "CerebusSource",
    "DataChunk",
    "Event",
    "EventType",
    "FileSource",
    "NPlaySource",
    "Pipeline",
    "PipelineConfig",
    "WaveletResult",
]
