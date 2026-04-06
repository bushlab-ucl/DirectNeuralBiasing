"""direct-neural-biasing — closed-loop neural signal processing.

Pipeline architecture (mirrors the Rust implementation):

    Source → [Downsampler] → WaveletConvolution → Detectors → StimTrigger → [Audio]

Detectors:
    - TargetWaveDetector: activation — "phase is at target in this band"
    - AmplitudeMonitor: inhibition — "amplitude is too high in this band"

The StimTrigger reads both and decides whether to fire STIM1/STIM2.

Quick start:
    from dnb import Pipeline, FileSource, PipelineConfig
    from dnb.modules import WaveletConvolution, TargetWaveDetector, StimTrigger

    pipeline = Pipeline(
        source=FileSource("data.npz"),
        modules=[
            WaveletConvolution(freq_min=0.5, freq_max=30, n_freqs=10),
            TargetWaveDetector(freq_range=(0.5, 2.0), target_phase=3.14),
            StimTrigger(activation_detector_id="slow_wave"),
        ],
    )
    events = pipeline.run_offline()
"""

from dnb.core.types import DataChunk, Event, EventType, PipelineConfig, WaveletResult
from dnb.engine.pipeline import Pipeline
from dnb.sources.file import FileSource

__version__ = "3.0.0"

__all__ = [
    "DataChunk",
    "Event",
    "EventType",
    "FileSource",
    "Pipeline",
    "PipelineConfig",
    "WaveletResult",
]
