"""Pipeline orchestrator.

Wires together a DataSource, module chain, and EventBus into a
runnable pipeline. Supports both run_online() and run_offline().

The pipeline is intentionally simple — it writes each chunk to the ring
buffer and runs it through the module chain. Any delay needed for
symmetric overlap-save is managed internally by WaveletConvolution,
which stashes one chunk and outputs results for the previous chunk.
This keeps the pipeline independent of module implementation details
and works correctly regardless of whether a Downsampler is present.

At end-of-stream, the pipeline calls flush() on the wavelet to process
its final stashed chunk, then runs downstream modules on the result.
"""

from __future__ import annotations

import logging
import signal
import time
from pathlib import Path
from typing import Callable

import numpy as np

from dnb.core.ring_buffer import RingBuffer
from dnb.core.types import DataChunk, Event, EventType, PipelineConfig
from dnb.engine.event_bus import EventBus, EventCallback
from dnb.modules.base import Module, ProcessResult
from dnb.sources.base import DataSource

logger = logging.getLogger(__name__)


class Pipeline:
    """Central DNB pipeline.

    Usage:
        pipeline = Pipeline(
            source=FileSource("data.npz"),
            modules=[WaveletConvolution(), TargetWaveDetector(), StimTrigger()],
        )
        events = pipeline.run_offline()

    Args:
        source: Data source (live or file).
        modules: Ordered list of processing modules.
        config: Pipeline configuration.
    """

    def __init__(
        self,
        source: DataSource,
        modules: list[Module] | None = None,
        config: PipelineConfig | None = None,
    ) -> None:
        self._source = source
        self._modules = modules or []
        self._config = config or PipelineConfig()
        self._event_bus = EventBus()
        self._buffer: RingBuffer | None = None
        self._running = False
        self._chunk_count = 0
        self._total_events = 0

    @property
    def config(self) -> PipelineConfig:
        return self._config

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    def on_event(self, event_type: EventType | str | None, callback: EventCallback) -> None:
        if isinstance(event_type, str):
            event_type = EventType[event_type.upper()]
        self._event_bus.subscribe(callback, event_type)

    def _setup(self) -> None:
        self._source.connect(self._config)

        resolved = getattr(self._source, "resolved_config", None)
        if resolved is not None:
            self._config = resolved

        self._buffer = RingBuffer(
            n_channels=self._config.n_channels,
            capacity=self._config.buffer_samples,
        )

        for module in self._modules:
            module.configure(self._config)

        self._chunk_count = 0
        self._total_events = 0
        logger.info(
            "Pipeline: %d modules, buffer=%.1fs, chunk=%.3fs",
            len(self._modules), self._config.buffer_duration, self._config.chunk_duration,
        )

    def _process_chunk(self, chunk: DataChunk) -> ProcessResult:
        self._buffer.write(chunk.samples)
        result = ProcessResult(chunk=chunk, ring_buffer=self._buffer)

        for module in self._modules:
            result = module.process(result)

        for event in result.events:
            self._event_bus.publish(event)

        self._chunk_count += 1
        self._total_events += len(result.events)
        return result

    def _flush(self) -> ProcessResult | None:
        """Flush any internally-buffered data from modules at end-of-stream.

        Currently only the WaveletConvolution has a flush() method (for its
        internal one-chunk delay). We call it, then run the remaining
        downstream modules on the result.
        """
        from dnb.modules.wavelet import WaveletConvolution

        wavelet_idx = None
        for i, module in enumerate(self._modules):
            if isinstance(module, WaveletConvolution):
                wavelet_idx = i
                break

        if wavelet_idx is None:
            return None

        # Create a result with the last ring buffer state
        # (chunk will be replaced by wavelet.flush)
        result = ProcessResult(chunk=None, ring_buffer=self._buffer)
        result = self._modules[wavelet_idx].flush(result)

        if result.chunk is None:
            return None  # wavelet had nothing stashed

        # Run downstream modules (everything after wavelet)
        for module in self._modules[wavelet_idx + 1:]:
            result = module.process(result)

        for event in result.events:
            self._event_bus.publish(event)

        self._chunk_count += 1
        self._total_events += len(result.events)
        return result

    def run_online(self) -> None:
        """Run in real-time closed-loop mode until Ctrl+C or stop()."""
        self._setup()
        self._running = True

        original_handler = signal.getsignal(signal.SIGINT)
        def _shutdown(signum, frame):
            logger.info("SIGINT — stopping pipeline...")
            self._running = False
        signal.signal(signal.SIGINT, _shutdown)

        logger.info("Pipeline running live. Ctrl+C to stop.")
        t_start = time.perf_counter()

        try:
            while self._running:
                chunk = self._source.read_chunk()
                if chunk is None:
                    time.sleep(0.001)
                    continue
                self._process_chunk(chunk)
        finally:
            self._flush()
            elapsed = time.perf_counter() - t_start
            signal.signal(signal.SIGINT, original_handler)
            self._teardown()
            logger.info("Stopped after %.1fs: %d chunks, %d events", elapsed, self._chunk_count, self._total_events)

    def run_offline(
        self,
        output_path: str | Path | None = None,
        progress_callback: Callable[[float], None] | None = None,
    ) -> list[Event]:
        """Run on a file source in batch mode. Returns all detected events."""
        self._setup()
        self._running = True
        all_events: list[Event] = []

        logger.info("Pipeline running offline...")
        t_start = time.perf_counter()

        try:
            while self._running:
                chunk = self._source.read_chunk()
                if chunk is None:
                    break
                result = self._process_chunk(chunk)
                all_events.extend(result.events)

                if progress_callback is not None:
                    prog = getattr(self._source, "progress", 0.0)
                    progress_callback(prog)

            # Flush the wavelet's internal buffer
            flush_result = self._flush()
            if flush_result is not None:
                all_events.extend(flush_result.events)

        finally:
            elapsed = time.perf_counter() - t_start
            self._teardown()
            logger.info("Offline complete in %.1fs: %d chunks, %d events", elapsed, self._chunk_count, len(all_events))

        if output_path is not None:
            self._save_results(Path(output_path), all_events)

        return all_events

    def stop(self) -> None:
        self._running = False

    def _teardown(self) -> None:
        self._source.close()
        for module in self._modules:
            module.reset()
        self._running = False

    @staticmethod
    def _save_results(path: Path, events: list[Event]) -> None:
        if not events:
            return
        np.savez(
            str(path),
            event_types=np.array([e.event_type.name for e in events]),
            timestamps=np.array([e.timestamp for e in events]),
            channel_ids=np.array([e.channel_id for e in events]),
            durations=np.array([e.duration for e in events]),
        )
        logger.info("Saved %d events to %s", len(events), path)