"""Pipeline orchestrator — single channel, single ring buffer.

Key invariant: the pipeline is the ONLY thing that writes to the
ring buffer. Modules transform chunks but never write to the buffer.
This eliminates double-write bugs.

Flow per chunk:
    1. Source produces raw chunk
    2. Downsampler transforms chunk (if present)
    3. Pipeline writes (transformed) samples into ring buffer
    4. Wavelet reads from ring buffer
    5. Detectors read wavelet output
    6. Trigger schedules stims
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
        self._ds_module_idx: int | None = None  # index of downsampler in module list

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

        # Configure all modules, find downsampler
        from dnb.modules.downsampler import Downsampler
        analysis_rate = self._config.sample_rate
        self._ds_module_idx = None

        for i, module in enumerate(self._modules):
            module.configure(self._config)
            if isinstance(module, Downsampler):
                self._ds_module_idx = i
                analysis_rate = module.actual_rate

        # Single ring buffer at the analysis rate
        buf_capacity = int(self._config.buffer_duration * analysis_rate)
        self._buffer = RingBuffer(capacity=buf_capacity)

        self._chunk_count = 0
        self._total_events = 0
        logger.info(
            "Pipeline: %d modules, buffer=%.1fs (%d samples @ %.0f Hz), chunk=%.3fs",
            len(self._modules), self._config.buffer_duration,
            buf_capacity, analysis_rate, self._config.chunk_duration,
        )

    def _process_chunk(self, chunk: DataChunk) -> ProcessResult:
        result = ProcessResult(chunk=chunk, ring_buffer=self._buffer)

        # Run downsampler first (if present) to transform the chunk
        if self._ds_module_idx is not None:
            result = self._modules[self._ds_module_idx].process(result)

        # Write the (possibly decimated) chunk into the ring buffer.
        # This is the ONLY write point.
        self._buffer.write(result.chunk.samples)

        # Run remaining modules (wavelet, detectors, trigger)
        for i, module in enumerate(self._modules):
            if i == self._ds_module_idx:
                continue  # already ran
            result = module.process(result)

        for event in result.events:
            self._event_bus.publish(event)

        self._chunk_count += 1
        self._total_events += len(result.events)
        return result

    def run_online(self) -> None:
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
            elapsed = time.perf_counter() - t_start
            signal.signal(signal.SIGINT, original_handler)
            self._teardown()
            logger.info("Stopped after %.1fs: %d chunks, %d events",
                        elapsed, self._chunk_count, self._total_events)

    def run_offline(
        self,
        output_path: str | Path | None = None,
        progress_callback: Callable[[float], None] | None = None,
    ) -> list[Event]:
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
        finally:
            elapsed = time.perf_counter() - t_start
            self._teardown()
            logger.info("Offline complete in %.1fs: %d chunks, %d events",
                        elapsed, self._chunk_count, len(all_events))

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
        )
        logger.info("Saved %d events to %s", len(events), path)