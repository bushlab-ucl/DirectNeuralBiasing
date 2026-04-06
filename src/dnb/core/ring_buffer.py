"""Thread-safe circular buffer for continuous neural data."""

from __future__ import annotations

import threading

import numpy as np
from numpy.typing import NDArray


class RingBuffer:
    """Pre-allocated numpy circular buffer with thread-safe read/write.

    Args:
        n_channels: Number of channels.
        capacity: Total samples the buffer can hold.
        dtype: Numpy dtype for the buffer.
    """

    def __init__(self, n_channels: int, capacity: int, dtype: type = np.float64) -> None:
        self._buf: NDArray = np.zeros((n_channels, capacity), dtype=dtype)
        self._capacity = capacity
        self._write_pos = 0
        self._total_written = 0
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def available(self) -> int:
        with self._lock:
            return min(self._total_written, self._capacity)

    def write(self, data: NDArray) -> None:
        n_samples = data.shape[1]
        with self._lock:
            if n_samples >= self._capacity:
                self._buf[:] = data[:, -self._capacity:]
                self._write_pos = 0
                self._total_written += n_samples
                return

            end = self._write_pos + n_samples
            if end <= self._capacity:
                self._buf[:, self._write_pos:end] = data
            else:
                first = self._capacity - self._write_pos
                self._buf[:, self._write_pos:] = data[:, :first]
                self._buf[:, :n_samples - first] = data[:, first:]

            self._write_pos = end % self._capacity
            self._total_written += n_samples

    def read(self, n_samples: int) -> NDArray:
        with self._lock:
            avail = min(self._total_written, self._capacity)
            if n_samples > avail:
                raise ValueError(
                    f"Requested {n_samples} samples but only {avail} available"
                )
            start = (self._write_pos - n_samples) % self._capacity
            if start + n_samples <= self._capacity:
                return self._buf[:, start:start + n_samples].copy()
            else:
                first = self._capacity - start
                return np.concatenate(
                    [self._buf[:, start:], self._buf[:, :n_samples - first]], axis=1,
                )

    def clear(self) -> None:
        with self._lock:
            self._buf[:] = 0
            self._write_pos = 0
            self._total_written = 0
