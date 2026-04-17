"""direct-neural-biasing — closed-loop neural signal processing."""

from dnb.core.types import DataChunk, Event, EventType, PipelineConfig, WaveletResult
from dnb.engine.pipeline import Pipeline
from dnb.sources.file import FileSource

try:
    from importlib.metadata import version
    __version__ = version("direct-neural-biasing")
except Exception:
    __version__ = "0.0.0-dev"

__all__ = [
    "DataChunk", "Event", "EventType", "FileSource",
    "Pipeline", "PipelineConfig", "WaveletResult",
]