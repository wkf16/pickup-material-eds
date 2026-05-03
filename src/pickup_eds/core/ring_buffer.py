from __future__ import annotations

from collections import deque
from typing import Iterable

import numpy as np


class RingBuffer:
    def __init__(self, capacity: int) -> None:
        self._times: deque[float] = deque(maxlen=capacity)
        self._values: deque[float] = deque(maxlen=capacity)

    def append_block(self, times: Iterable[float], values: Iterable[float]) -> None:
        self._times.extend(float(item) for item in times)
        self._values.extend(float(item) for item in values)

    def tail(self, max_samples: int | None = None) -> tuple[np.ndarray, np.ndarray]:
        times = np.fromiter(self._times, dtype=np.float64)
        values = np.fromiter(self._values, dtype=np.float64)
        if max_samples is None or len(times) <= max_samples:
            return times, values
        return times[-max_samples:], values[-max_samples:]


def decimate_pair(
    times: np.ndarray,
    values: np.ndarray,
    max_points: int,
) -> tuple[np.ndarray, np.ndarray]:
    if len(times) <= max_points:
        return times, values
    indices = np.linspace(0, len(times) - 1, max_points, dtype=int)
    return times[indices], values[indices]

