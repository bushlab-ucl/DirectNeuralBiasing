"""Pipeline orchestrator.

Wires together a DataSource, a module chain, and an EventBus into
a runnable pipeline. Provides run_online() for real-time closed-loop
operation and run_offline() for batch processing from file.
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

    Connects a data source to a chain of processing modules, with an
    event bus for inter-module communication and external callbacks.

    Usage:
        pipeline = Pipeline(
            source=NPlaySource(),
            modules=[WaveletConvolution(), EventDetector()],
        )
        pipeline.on_event("ripple", callback)
        pipeline.run_online()

    Args:
        source: Data source (live or file).
        modules: Ordered list of processing modules.
        config: Pipeline configuration. If None, uses defaults.
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

    def on_event(
        self,
        event_type: EventType | str | None,
        callback: EventCallback,
    ) -> None:
        """Register a callback for pipeline events.

        Args:
            event_type: EventType enum, string name (e.g. "ripple"), or None for all.
            callback: Function called with each matching Event.
        """
        if isinstance(event_type, str):
            event_type = EventType[event_type.upper()]
        self._event_bus.subscribe(callback, event_type)

    def _setup(self) -> None:
        """Initialise buffer, connect source, configure modules."""
        # Connect source first — it may resolve config from file contents.
        self._source.connect(self._config)

        # If the source provides a resolved config (e.g. FileSource with
        # actual sample_rate / n_channels from the file), adopt it so that
        # the ring buffer and all modules use the correct parameters.
        resolved = getattr(self._source, "resolved_config", None)
        if resolved is not None:
            self._config = resolved

        self._buffer = RingBuffer(
            n_channels=self._config.n_channels,
            capacity=self._config.buffer_samples,
        )

        # Validate module ordering
        self._validate_module_order()

        for module in self._modules:
            module.configure(self._config)

        self._chunk_count = 0
        self._total_events = 0
        logger.info(
            "Pipeline setup: %d modules, buffer=%.1fs, chunk=%.3fs",
            len(self._modules),
            self._config.buffer_duration,
            self._config.chunk_duration,
        )

    def _validate_module_order(self) -> None:
        """Validate that modules are in a sensible order.

        Checks:
        - Modules that consume wavelet data should come after the wavelet
          producer.
        - Downsampler should come before WaveletConvolution (so the wavelet
          processes at the reduced rate).
        - SlowWaveDetector should come after WaveletConvolution.
        """
        from dnb.modules.detector import EventDetector
        from dnb.modules.downsampler import Downsampler
        from dnb.modules.power import PowerEstimator
        from dnb.modules.slow_wave import SlowWaveDetector
        from dnb.modules.wavelet import WaveletConvolution

        wavelet_consumers = (EventDetector, PowerEstimator, SlowWaveDetector)
        seen_wavelet_producer = False
        seen_downsampler = False

        for module in self._modules:
            if isinstance(module, Downsampler):
                if seen_wavelet_producer:
                    logger.warning(
                        "Downsampler is placed AFTER WaveletConvolution. "
                        "The wavelet will process at the original (high) sample "
                        "rate, which may be too slow for real-time. Consider "
                        "placing Downsampler before WaveletConvolution."
                    )
                seen_downsampler = True

            elif isinstance(module, WaveletConvolution):
                seen_wavelet_producer = True

            elif isinstance(module, wavelet_consumers) and not seen_wavelet_producer:
                logger.warning(
                    "%s is placed before WaveletConvolution in the module chain. "
                    "It will receive no wavelet data and silently skip processing.",
                    type(module).__name__,
                )

    def _process_chunk(self, chunk: DataChunk) -> ProcessResult:
        """Run a single chunk through the module chain."""
        self._buffer.write(chunk.samples)

        result = ProcessResult(chunk=chunk, ring_buffer=self._buffer)

        for module in self._modules:
            result = module.process(result)

        # Dispatch all detected events
        for event in result.events:
            self._event_bus.publish(event)

        self._chunk_count += 1
        self._total_events += len(result.events)
        return result

    def run_online(self) -> None:
        """Run the pipeline in real-time closed-loop mode.

        Continuously reads from the source and processes chunks until
        interrupted with Ctrl+C or stop() is called.
        """
        self._setup()
        self._running = True

        # Graceful shutdown on SIGINT
        original_handler = signal.getsignal(signal.SIGINT)

        def _shutdown(signum, frame):
            logger.info("Received SIGINT — stopping pipeline...")
            self._running = False

        signal.signal(signal.SIGINT, _shutdown)

        logger.info("Pipeline running live. Press Ctrl+C to stop.")
        t_start = time.perf_counter()

        try:
            while self._running:
                chunk = self._source.read_chunk()
                if chunk is None:
                    time.sleep(0.001)
                    continue
                self._process_chunk(chunk)
        finally:
            elapsed = time.perf_counter() - t_start
            signal.signal(signal.SIGINT, original_handler)
            self._teardown()
            logger.info(
                "Pipeline stopped after %.1fs: %d chunks, %d events",
                elapsed,
                self._chunk_count,
                self._total_events,
            )

    def run_offline(
        self,
        output_path: str | Path | None = None,
        progress_callback: Callable[[float], None] | None = None,
    ) -> list[Event]:
        """Run the pipeline on a file source in batch mode.

        Reads the entire source, processes all chunks through the same
        module chain as run_online(), and returns all detected events.

        Args:
            output_path: If provided, save events and results to this .npz file.
            progress_callback: Called with progress fraction (0.0 to 1.0).

        Returns:
            List of all events detected across the full recording.
        """
        self._setup()
        self._running = True

        all_events: list[Event] = []
        all_results: list[ProcessResult] = []

        logger.info("Pipeline running offline...")
        t_start = time.perf_counter()

        try:
            while self._running:
                chunk = self._source.read_chunk()
                if chunk is None:
                    break

                result = self._process_chunk(chunk)
                all_events.extend(result.events)
                all_results.append(result)

                if progress_callback is not None:
                    # FileSource has a .progress property
                    prog = getattr(self._source, "progress", 0.0)
                    progress_callback(prog)
        finally:
            elapsed = time.perf_counter() - t_start
            self._teardown()
            logger.info(
                "Offline run complete in %.1fs: %d chunks, %d events",
                elapsed,
                self._chunk_count,
                len(all_events),
            )

        if output_path is not None:
            self._save_results(Path(output_path), all_events)

        return all_events

    def stop(self) -> None:
        """Signal the pipeline to stop after the current chunk."""
        self._running = False

    def _teardown(self) -> None:
        """Clean up source and reset modules."""
        self._source.close()
        for module in self._modules:
            module.reset()
        self._running = False

    @staticmethod
    def _save_results(path: Path, events: list[Event]) -> None:
        """Save detected events to a .npz file."""
        if not events:
            logger.warning("No events to save.")
            return

        np.savez(
            str(path),
            event_types=np.array([e.event_type.name for e in events]),
            timestamps=np.array([e.timestamp for e in events]),
            channel_ids=np.array([e.channel_id for e in events]),
            durations=np.array([e.duration for e in events]),
        )
        logger.info("Saved %d events to %s", len(events), path)
