"""Tests for data sources and pipeline integration."""

import tempfile
from pathlib import Path

import numpy as np
import pytest

from dnb.core.types import EventType, PipelineConfig
from dnb.engine.event_bus import EventBus
from dnb.engine.pipeline import Pipeline
from dnb.modules.detector import EventDetector
from dnb.modules.power import PowerEstimator
from dnb.modules.wavelet import WaveletConvolution
from dnb.sources.file import FileSource


@pytest.fixture
def sample_npz(tmp_path: Path) -> Path:
    """Create a sample .npz file with synthetic data."""
    rng = np.random.default_rng(42)
    n_channels, n_samples = 4, 30000
    sample_rate = 30000.0

    # Pink-ish noise + a 120Hz burst on channel 0 around t=0.5s
    t = np.arange(n_samples) / sample_rate
    data = rng.standard_normal((n_channels, n_samples)) * 0.5

    burst_start = int(0.4 * sample_rate)
    burst_end = int(0.6 * sample_rate)
    data[0, burst_start:burst_end] += 10.0 * np.sin(
        2 * np.pi * 120 * t[burst_start:burst_end]
    )

    path = tmp_path / "test_data.npz"
    np.savez(str(path), continuous=data, sample_rate=sample_rate)
    return path


class TestFileSource:
    def test_connect_and_read(self, sample_npz: Path):
        config = PipelineConfig(sample_rate=30000, n_channels=4, chunk_duration=0.2)
        src = FileSource(sample_npz)
        src.connect(config)

        chunk = src.read_chunk()
        assert chunk is not None
        assert chunk.n_channels == 4
        assert chunk.n_samples == 6000  # 0.2s * 30kHz
        assert chunk.sample_rate == 30000.0

        src.close()

    def test_exhausts_file(self, sample_npz: Path):
        config = PipelineConfig(sample_rate=30000, n_channels=4, chunk_duration=0.5)
        src = FileSource(sample_npz)
        src.connect(config)

        chunks = []
        while True:
            chunk = src.read_chunk()
            if chunk is None:
                break
            chunks.append(chunk)

        total_samples = sum(c.n_samples for c in chunks)
        assert total_samples == 30000  # 1 second of data
        assert src.progress == 1.0

        src.close()

    def test_missing_file_raises(self, tmp_path: Path):
        src = FileSource(tmp_path / "nonexistent.npz")
        config = PipelineConfig()
        with pytest.raises(FileNotFoundError):
            src.connect(config)

    def test_progress(self, sample_npz: Path):
        config = PipelineConfig(sample_rate=30000, n_channels=4, chunk_duration=0.5)
        src = FileSource(sample_npz)
        src.connect(config)

        assert src.progress == 0.0
        src.read_chunk()
        assert 0.0 < src.progress < 1.0
        src.close()


class TestEventBus:
    def test_subscribe_and_publish(self):
        bus = EventBus()
        received = []
        bus.subscribe(lambda e: received.append(e), EventType.RIPPLE)

        from dnb.core.types import Event

        bus.publish(Event(EventType.RIPPLE, timestamp=1.0, channel_id=0))
        bus.publish(Event(EventType.SPINDLE, timestamp=2.0, channel_id=0))

        assert len(received) == 1
        assert received[0].event_type == EventType.RIPPLE

    def test_wildcard_subscriber(self):
        bus = EventBus()
        received = []
        bus.subscribe(lambda e: received.append(e))  # None = all events

        from dnb.core.types import Event

        bus.publish(Event(EventType.RIPPLE, timestamp=1.0, channel_id=0))
        bus.publish(Event(EventType.SPINDLE, timestamp=2.0, channel_id=0))

        assert len(received) == 2


class TestPipelineOffline:
    def test_full_pipeline(self, sample_npz: Path):
        """End-to-end: file → wavelet → power → detect → events."""
        config = PipelineConfig(
            sample_rate=30000,
            n_channels=4,
            chunk_duration=0.2,
        )

        pipeline = Pipeline(
            source=FileSource(sample_npz),
            modules=[
                WaveletConvolution(freq_min=10, freq_max=200, n_freqs=15),
                PowerEstimator(),
                EventDetector(
                    event_type=EventType.RIPPLE,
                    freq_range=(80, 200),
                    threshold_std=2.0,
                ),
            ],
            config=config,
        )

        progress_values = []
        events = pipeline.run_offline(
            progress_callback=lambda p: progress_values.append(p)
        )

        # Should have processed something
        assert len(progress_values) > 0
        # Should detect the planted burst
        assert len(events) > 0

    def test_pipeline_saves_output(self, sample_npz: Path, tmp_path: Path):
        config = PipelineConfig(sample_rate=30000, n_channels=4, chunk_duration=0.5)
        output_path = tmp_path / "results.npz"

        pipeline = Pipeline(
            source=FileSource(sample_npz),
            modules=[
                WaveletConvolution(freq_min=10, freq_max=200, n_freqs=10),
                EventDetector(
                    event_type=EventType.RIPPLE,
                    freq_range=(80, 200),
                    threshold_std=2.0,
                ),
            ],
            config=config,
        )

        events = pipeline.run_offline(output_path=output_path)

        if events:
            assert output_path.exists()
            saved = np.load(str(output_path))
            assert "timestamps" in saved
            assert "event_types" in saved
