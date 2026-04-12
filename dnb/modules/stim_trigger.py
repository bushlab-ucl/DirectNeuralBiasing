"""Stimulation trigger — combines detectors to decide when to fire.

This is the direct equivalent of the Rust PulseTrigger. It reads from
an activation detector (e.g. TargetWaveDetector) and an optional
inhibition detector (e.g. AmplitudeMonitor), applies cooldowns, and
emits STIM1/STIM2 events.

The separation is key: detectors say "I see something", the trigger
decides "should we act on it?"

Logic (mirrors the Rust version):
    1. If inhibition detector is active → reset cooldown, do not fire
    2. If activation detector has candidates AND pulse cooldown elapsed
       → fire STIM1, start pulse cooldown, schedule STIM2 window
    3. STIM2 fires when next activation candidate appears within the
       STIM2 acceptance window
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from dnb.core.types import Event, EventType, PipelineConfig
from dnb.modules.base import Module, ProcessResult

logger = logging.getLogger(__name__)


class StimTrigger(Module):
    """Pulse trigger combining activation and inhibition detectors.

    Args:
        activation_detector_id: ID of the detector providing candidates.
        inhibition_detector_id: ID of the inhibition detector (or None).
        backoff_s: Minimum seconds between STIM1 events (pulse cooldown).
        inhibition_cooldown_s: Seconds to wait after inhibition before allowing stim.
        stim2_delay_s: Delay after STIM1 before STIM2 window opens.
        stim2_window_s: Duration of the STIM2 acceptance window.
        event_window_s: ±seconds of raw signal to capture around events.
    """

    def __init__(
        self,
        activation_detector_id: str = "slow_wave",
        inhibition_detector_id: str | None = "ied_monitor",
        backoff_s: float = 5.0,
        inhibition_cooldown_s: float = 5.0,
        stim2_delay_s: float = 0.6,
        stim2_window_s: float = 2.0,
        event_window_s: float = 1.0,
    ) -> None:
        self._act_id = activation_detector_id
        self._inh_id = inhibition_detector_id
        self._backoff_s = backoff_s
        self._inhibition_cooldown_s = inhibition_cooldown_s
        self._stim2_delay_s = stim2_delay_s
        self._stim2_window_s = stim2_window_s
        self._event_window_s = event_window_s

        # Per-channel state
        self._last_stim1_time: dict[int, float] = {}
        self._last_inhibition_time: dict[int, float] = {}
        self._awaiting_stim2: dict[int, float] = {}  # ch_id → stim1 time

    def configure(self, config: PipelineConfig) -> None:
        logger.info(
            "StimTrigger: activation='%s', inhibition='%s', backoff=%.1fs",
            self._act_id, self._inh_id or "none", self._backoff_s,
        )

    def _extract_window(
        self, result: ProcessResult, event_time: float, channel_id: int,
    ) -> NDArray | None:
        """Extract ±event_window_s of raw signal around the event."""
        if self._event_window_s <= 0 or result.ring_buffer is None:
            return None

        sr = result.chunk.sample_rate
        half_win = int(self._event_window_s * sr)
        total_win = 2 * half_win + 1
        avail = result.ring_buffer.available

        if avail < total_win:
            return None

        try:
            chunk_end_time = result.chunk.timestamps[-1]
            samples_after_event = max(0, int((chunk_end_time - event_time) * sr))
            read_len = max(samples_after_event + half_win + 1, total_win)
            read_len = min(read_len, avail)

            if read_len < total_win:
                return None

            window_data = result.ring_buffer.read(read_len)
            ch_indices = np.where(result.chunk.channel_ids == channel_id)[0]
            ch_idx = ch_indices[0] if len(ch_indices) > 0 else 0

            event_pos = read_len - samples_after_event - 1
            start = max(0, event_pos - half_win)
            end = min(window_data.shape[1], event_pos + half_win + 1)

            if end - start < half_win or ch_idx >= window_data.shape[0]:
                return None
            return window_data[ch_idx, start:end].copy()
        except (ValueError, IndexError):
            return None

    def process(self, result: ProcessResult) -> ProcessResult:
        activation = result.detections.get(self._act_id, {})
        inhibition = result.detections.get(self._inh_id, {}) if self._inh_id else {}

        inhibition_active = inhibition.get("active", False)
        candidates = activation.get("candidates", [])

        if not candidates and not inhibition_active:
            # Nothing happening — check for stim2 window expiry
            self._expire_stim2(result.chunk.timestamps[-1] if result.chunk.n_samples > 0 else 0)
            return result

        events: list[Event] = []

        # Group candidates by channel
        by_channel: dict[int, list[dict]] = {}
        for c in candidates:
            by_channel.setdefault(c["channel_id"], []).append(c)

        for ch_id, ch_candidates in by_channel.items():
            # --- Inhibition check ---
            if inhibition_active:
                self._last_inhibition_time[ch_id] = ch_candidates[0]["timestamp"]
                # Clear any pending STIM2
                self._awaiting_stim2.pop(ch_id, None)
                continue

            # Check inhibition cooldown
            last_inh = self._last_inhibition_time.get(ch_id, -np.inf)
            if ch_candidates and ch_candidates[0]["timestamp"] - last_inh < self._inhibition_cooldown_s:
                continue
            
            # --- STIM2 check ---
            stim2_fired = False
            if ch_id in self._awaiting_stim2:
                stim1_t = self._awaiting_stim2[ch_id]
                for c in ch_candidates:
                    t = c["timestamp"]
                    dt = t - stim1_t
                    if dt < self._stim2_delay_s: continue
                    if dt > self._stim2_delay_s + self._stim2_window_s:
                        del self._awaiting_stim2[ch_id]
                        break

                    meta = {**c, "stim1_time": stim1_t, "delay": dt}
                    raw_win = self._extract_window(result, t, ch_id)
                    if raw_win is not None:
                        meta["raw_window"] = raw_win
                        meta["raw_window_sr"] = result.chunk.sample_rate

                    events.append(Event(
                        event_type=EventType.STIM2, timestamp=t,
                        channel_id=ch_id, metadata=meta,
                    ))
                    del self._awaiting_stim2[ch_id]
                    logger.info("STIM2 ch=%d t=%.3fs delay=%.3fs", ch_id, t, dt)
                    stim2_fired = True
                    break

            if stim2_fired:
                continue

            # --- STIM1 check ---
            last_stim = self._last_stim1_time.get(ch_id, -np.inf)

            for c in ch_candidates:
                t = c["timestamp"]
                if t - last_stim < self._backoff_s:
                    continue

                meta = dict(c)
                raw_win = self._extract_window(result, t, ch_id)
                if raw_win is not None:
                    meta["raw_window"] = raw_win
                    meta["raw_window_sr"] = result.chunk.sample_rate

                events.append(Event(
                    event_type=EventType.STIM1, timestamp=t,
                    channel_id=ch_id, metadata=meta,
                ))
                self._last_stim1_time[ch_id] = t
                self._awaiting_stim2[ch_id] = t
                logger.info(
                    "STIM1 ch=%d t=%.3fs phase=%.2f amp=%.1f",
                    ch_id, t, c.get("phase", 0), c.get("amplitude", 0),
                )
                break  # One STIM1 per chunk per channel

        result.events.extend(events)
        return result

    def _expire_stim2(self, current_time: float) -> None:
        """Remove expired STIM2 windows."""
        expired = [
            ch for ch, t in self._awaiting_stim2.items()
            if current_time - t > self._stim2_delay_s + self._stim2_window_s
        ]
        for ch in expired:
            del self._awaiting_stim2[ch]

    def reset(self) -> None:
        self._last_stim1_time.clear()
        self._last_inhibition_time.clear()
        self._awaiting_stim2.clear()
