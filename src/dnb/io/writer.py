"""Output writer for pipeline results.

Handles saving events, continuous data, and wavelet decompositions
to disk in .npz format compatible with the FileSource for reloading.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from dnb.core.types import DataChunk, Event

logger = logging.getLogger(__name__)


class ResultWriter:
    """Accumulates pipeline output and saves to disk.

    Can be used as an event callback or fed chunks directly.

    Args:
        output_dir: Directory to write output files.
        prefix: Filename prefix for output files.
    """

    def __init__(self, output_dir: str | Path, prefix: str = "dnb") -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._prefix = prefix
        self._events: list[Event] = []
        self._chunks: list[DataChunk] = []

    def on_event(self, event: Event) -> None:
        """Event callback — accumulates events for later saving."""
        self._events.append(event)

    def add_chunk(self, chunk: DataChunk) -> None:
        """Store a processed chunk."""
        self._chunks.append(chunk)

    def save_events(self, filename: str | None = None) -> Path:
        """Save accumulated events to .npz.

        If events contain 'raw_window' metadata (captured by
        SlowWaveDetector with event_window_s > 0), the windows are
        saved as separate arrays keyed by event index.
        """
        fname = filename or f"{self._prefix}_events.npz"
        path = self._output_dir / fname

        if not self._events:
            logger.warning("No events to save.")
            return path

        save_dict: dict[str, NDArray] = {
            "event_types": np.array([e.event_type.name for e in self._events]),
            "timestamps": np.array([e.timestamp for e in self._events]),
            "channel_ids": np.array([e.channel_id for e in self._events]),
            "durations": np.array([e.duration for e in self._events]),
        }

        # Save phases and amplitudes if available
        phases = []
        amplitudes = []
        for e in self._events:
            phases.append(e.metadata.get("phase", float("nan")))
            amplitudes.append(e.metadata.get("amplitude", float("nan")))
        save_dict["phases"] = np.array(phases)
        save_dict["amplitudes"] = np.array(amplitudes)

        # Save raw signal windows around events
        window_count = 0
        for i, e in enumerate(self._events):
            raw_win = e.metadata.get("raw_window")
            if raw_win is not None:
                save_dict[f"window_{i:04d}"] = np.asarray(raw_win)
                window_count += 1

        # Save the window sample rate if any windows were captured
        if window_count > 0:
            # Use the first event's window sample rate
            for e in self._events:
                sr = e.metadata.get("raw_window_sr")
                if sr is not None:
                    save_dict["window_sample_rate"] = np.array(sr)
                    break

        np.savez(str(path), **save_dict)
        logger.info(
            "Saved %d events to %s (%d with raw windows)",
            len(self._events), path, window_count,
        )
        return path

    def save_continuous(self, filename: str | None = None) -> Path:
        """Concatenate stored chunks and save as continuous .npz.

        The output is compatible with FileSource for reloading.
        """
        fname = filename or f"{self._prefix}_continuous.npz"
        path = self._output_dir / fname

        if not self._chunks:
            logger.warning("No continuous data to save.")
            return path

        all_samples = np.concatenate([c.samples for c in self._chunks], axis=1)
        all_timestamps = np.concatenate([c.timestamps for c in self._chunks])

        np.savez(
            str(path),
            continuous=all_samples,
            timestamps=all_timestamps,
            sample_rate=self._chunks[0].sample_rate,
            channel_ids=self._chunks[0].channel_ids,
        )
        logger.info(
            "Saved continuous data to %s: shape %s, %.1fs",
            path,
            all_samples.shape,
            len(all_timestamps) / self._chunks[0].sample_rate,
        )
        return path

    def clear(self) -> None:
        """Reset accumulated data."""
        self._events.clear()
        self._chunks.clear()
