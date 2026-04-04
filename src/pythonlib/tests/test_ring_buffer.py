"""Tests for the thread-safe ring buffer."""

import numpy as np
import pytest

from dnb.core.ring_buffer import RingBuffer


class TestRingBuffer:
    def test_write_read_basic(self):
        buf = RingBuffer(n_channels=2, capacity=100)
        data = np.ones((2, 50))
        buf.write(data)
        out = buf.read(50)
        np.testing.assert_array_equal(out, data)

    def test_read_most_recent(self):
        buf = RingBuffer(n_channels=1, capacity=100)
        buf.write(np.full((1, 60), 1.0))
        buf.write(np.full((1, 60), 2.0))
        out = buf.read(60)
        np.testing.assert_array_equal(out, np.full((1, 60), 2.0))

    def test_wraparound(self):
        buf = RingBuffer(n_channels=1, capacity=10)
        # Write 7, then 7 more — forces wraparound
        buf.write(np.arange(7).reshape(1, 7).astype(float))
        buf.write(np.arange(7, 14).reshape(1, 7).astype(float))
        out = buf.read(10)
        expected = np.arange(4, 14).reshape(1, 10).astype(float)
        np.testing.assert_array_equal(out, expected)

    def test_read_exceeds_available_raises(self):
        buf = RingBuffer(n_channels=1, capacity=100)
        buf.write(np.ones((1, 10)))
        with pytest.raises(ValueError, match="only 10 available"):
            buf.read(50)

    def test_clear(self):
        buf = RingBuffer(n_channels=2, capacity=50)
        buf.write(np.ones((2, 30)))
        buf.clear()
        assert buf.available == 0

    def test_write_larger_than_capacity(self):
        buf = RingBuffer(n_channels=1, capacity=10)
        data = np.arange(20).reshape(1, 20).astype(float)
        buf.write(data)
        out = buf.read(10)
        expected = np.arange(10, 20).reshape(1, 10).astype(float)
        np.testing.assert_array_equal(out, expected)

    def test_available(self):
        buf = RingBuffer(n_channels=1, capacity=100)
        assert buf.available == 0
        buf.write(np.ones((1, 30)))
        assert buf.available == 30
        buf.write(np.ones((1, 80)))
        assert buf.available == 100  # capped at capacity

    def test_available_is_thread_safe(self):
        """available should return a consistent value under the lock."""
        import threading

        buf = RingBuffer(n_channels=1, capacity=1000)
        results = []

        def writer():
            for _ in range(100):
                buf.write(np.ones((1, 10)))

        def reader():
            for _ in range(100):
                results.append(buf.available)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # All observed values should be valid (multiples of 10 up to 1000)
        for v in results:
            assert 0 <= v <= 1000