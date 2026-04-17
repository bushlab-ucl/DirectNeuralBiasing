"""Single-channel ring buffer — the one FIFO the whole pipeline shares.

TWave-style: one buffer at the analysis rate. The downsampler writes
into it, the wavelet reads the most recent N seconds from it.
No separate buffers per module.
"""

from __future__ import annotations

import threading
import numpy as np
from numpy.typing import NDArray


class RingBuffer:
    """1D circular buffer at the analysis rate.

    Thread-safe for live use (writer thread + reader thread).
    For offline, the lock is uncontended.
    """

    def __init__(self, capacity: int, dtype: type = np.float64) -> None:
        self._buf: NDArray = np.zeros(capacity, dtype=dtype)
        self._capacity = capacity
        self._write_pos = 0
        self._total_written = 0
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def available(self) -> int:
        """How many samples can be read (up to capacity)."""
        with self._lock:
            return min(self._total_written, self._capacity)

    def write(self, data: NDArray) -> None:
        """Append 1D data to the buffer."""
        n = data.shape[0]
        with self._lock:
            if n >= self._capacity:
                self._buf[:] = data[-self._capacity:]
                self._write_pos = 0
                self._total_written += n
                return

            end = self._write_pos + n
            if end <= self._capacity:
                self._buf[self._write_pos:end] = data
            else:
                first = self._capacity - self._write_pos
                self._buf[self._write_pos:] = data[:first]
                self._buf[:n - first] = data[first:]

            self._write_pos = end % self._capacity
            self._total_written += n

    def read_latest(self, n_samples: int) -> NDArray:
        """Read the most recent n_samples. Returns a contiguous copy."""
        with self._lock:
            avail = min(self._total_written, self._capacity)
            if n_samples > avail:
                raise ValueError(
                    f"Requested {n_samples} but only {avail} available"
                )
            start = (self._write_pos - n_samples) % self._capacity
            if start + n_samples <= self._capacity:
                return self._buf[start:start + n_samples].copy()
            else:
                first = self._capacity - start
                return np.concatenate(
                    [self._buf[start:], self._buf[:n_samples - first]]
                )

    def clear(self) -> None:
        with self._lock:
            self._buf[:] = 0
            self._write_pos = 0
            self._total_written = 0