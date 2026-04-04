"""Tests for data sources and pipeline integration."""

import logging
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
    """Create a sample .npz file with synthetic data.

    The file contains 2 seconds of data so there are enough chunks
    for the EventDetector's warmup period to elapse before the burst.
    The burst is placed in the second half of the recording.
    """
    rng = np.random.default_rng(42)
    n_channels = 4
    sample_rate = 30000.0
    duration = 2.0  # seconds
    n_samples = int(duration * sample_rate)

    t = np.arange(n_samples) / sample_rate
    data = rng.standard_normal((n_channels, n_samples)) * 0.5

    # Plant a loud 120 Hz burst on channel 0 from 1.4s to 1.6s
    # (well after the warmup period at chunk_duration=0.2 → warmup = 5*0.2 = 1.0s)
    burst_start = int(1.4 * sample_rate)
    burst_end = int(1.6 * sample_rate)
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

    def test_resolved_config(self, sample_npz: Path):
        """FileSource should expose a resolved_config matching the file."""
        config = PipelineConfig(sample_rate=1000, n_channels=1, chunk_duration=0.5)
        src = FileSource(sample_npz)
        src.connect(config)

        rc = src.resolved_config
        assert rc is not None
        # Should reflect the file's actual parameters, not the input config
        assert rc.sample_rate == 30000.0
        assert rc.n_channels == 4
        # But should preserve the user's timing preferences
        assert rc.chunk_duration == 0.5

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
        assert total_samples == 60000  # 2 seconds of data
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
                    warmup_chunks=3,
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
        # Should detect the planted burst (placed after warmup window)
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
                    warmup_chunks=1,
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

    def test_pipeline_adopts_file_config(self, tmp_path: Path):
        """Pipeline should use the file's actual sample_rate and n_channels."""
        # Create a file with different params than the pipeline config
        rng = np.random.default_rng(7)
        file_sr = 10000.0
        file_ch = 2
        n_samples = 20000  # 2 seconds

        data = rng.standard_normal((file_ch, n_samples))
        path = tmp_path / "odd_params.npz"
        np.savez(str(path), continuous=data, sample_rate=file_sr)

        # Pipeline config says 83 channels at 30 kHz — totally wrong for this file
        config = PipelineConfig(sample_rate=30000, n_channels=83, chunk_duration=0.5)

        pipeline = Pipeline(
            source=FileSource(path),
            modules=[
                WaveletConvolution(freq_min=10, freq_max=200, n_freqs=5),
            ],
            config=config,
        )

        # run_offline should succeed — pipeline adopts the file's config
        events = pipeline.run_offline()

        # After setup, pipeline config should reflect the file
        assert pipeline.config.sample_rate == file_sr
        assert pipeline.config.n_channels == file_ch

    def test_module_order_warning(self, sample_npz: Path, caplog):
        """Placing EventDetector before WaveletConvolution should warn."""
        config = PipelineConfig(sample_rate=30000, n_channels=4, chunk_duration=0.5)

        pipeline = Pipeline(
            source=FileSource(sample_npz),
            modules=[
                EventDetector(freq_range=(80, 200)),  # before wavelet!
                WaveletConvolution(freq_min=10, freq_max=200, n_freqs=5),
            ],
            config=config,
        )

        with caplog.at_level(logging.WARNING):
            pipeline.run_offline()

        assert any(
            "EventDetector" in record.getMessage()
            and "before WaveletConvolution" in record.getMessage()
            for record in caplog.records
        ), "Expected a warning about module ordering"