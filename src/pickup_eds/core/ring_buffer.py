from __future__ import annotations

from typing import Iterable

import numpy as np


class RingBuffer:
    """Pre-allocated numpy ring buffer.

    Memory is fixed at ``capacity × 16 bytes`` (two float64 arrays). No
    per-sample Python objects, no per-block allocation in ``append_block``,
    and ``tail`` allocates only what it returns. At 50 kS/s × 120 s this
    is ~96 MB total instead of ~670 MB the old deque-of-Python-floats
    version used, with zero GC pressure on the streaming path.
    """

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._capacity = capacity
        self._times = np.zeros(capacity, dtype=np.float64)
        self._values = np.zeros(capacity, dtype=np.float64)
        # Write index inside the ring; _filled grows up to capacity then
        # stays — total samples observed is tracked separately by
        # callers that care (samples_emitted on the bench service).
        self._write = 0
        self._filled = 0

    def __len__(self) -> int:
        return self._filled

    @property
    def capacity(self) -> int:
        return self._capacity

    def append_block(self, times: Iterable[float], values: Iterable[float]) -> None:
        # Convert to ndarray once (zero-copy if already ndarray with the
        # right dtype). We avoid Python-level per-element conversion that
        # the old deque version did with ``float(item) for item in ...``.
        t = np.asarray(times, dtype=np.float64)
        v = np.asarray(values, dtype=np.float64)
        n = t.size
        if n == 0:
            return
        if v.size != n:
            raise ValueError(f"times/values length mismatch: {n} vs {v.size}")

        if n >= self._capacity:
            # Block bigger than the buffer — keep only the last `capacity` samples.
            self._times[:] = t[-self._capacity:]
            self._values[:] = v[-self._capacity:]
            self._write = 0
            self._filled = self._capacity
            return

        end = self._write + n
        if end <= self._capacity:
            self._times[self._write:end] = t
            self._values[self._write:end] = v
        else:
            first = self._capacity - self._write
            self._times[self._write:] = t[:first]
            self._values[self._write:] = v[:first]
            rest = n - first
            self._times[:rest] = t[first:]
            self._values[:rest] = v[first:]

        self._write = (self._write + n) % self._capacity
        if self._filled < self._capacity:
            self._filled = min(self._filled + n, self._capacity)

    def tail(self, max_samples: int | None = None) -> tuple[np.ndarray, np.ndarray]:
        n = self._filled
        if max_samples is not None and 0 <= max_samples < n:
            n = max_samples
        if n == 0:
            return (np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64))

        # Where do the last `n` samples start in the ring?
        start = (self._write - n) % self._capacity
        if start + n <= self._capacity:
            # Contiguous slice — copy so caller can mutate freely without
            # racing the writer thread.
            return self._times[start:start + n].copy(), self._values[start:start + n].copy()

        # Wraps around the boundary — concatenate two slices.
        first = self._capacity - start
        rest = n - first
        t = np.concatenate([self._times[start:], self._times[:rest]])
        v = np.concatenate([self._values[start:], self._values[:rest]])
        return t, v

    def reset(self) -> None:
        """Drop all samples (write index back to 0). Doesn't free memory."""
        self._write = 0
        self._filled = 0


def decimate_pair(
    times: np.ndarray,
    values: np.ndarray,
    max_points: int,
) -> tuple[np.ndarray, np.ndarray]:
    if len(times) <= max_points:
        return times, values
    indices = np.linspace(0, len(times) - 1, max_points, dtype=int)
    return times[indices], values[indices]
