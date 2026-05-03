from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    host: str
    port: int
    sample_rate_hz: int
    buffer_seconds: int
    stream_points: int
    stream_window_s: float


def load_settings() -> Settings:
    sample_rate_hz = int(os.getenv("PICKUP_EDS_SAMPLE_RATE_HZ", "5000"))
    buffer_seconds = int(os.getenv("PICKUP_EDS_BUFFER_SECONDS", "120"))
    return Settings(
        data_dir=Path(os.getenv("PICKUP_EDS_DATA_DIR", "data")),
        host=os.getenv("PICKUP_EDS_HOST", "0.0.0.0"),
        port=int(os.getenv("PICKUP_EDS_PORT", "8000")),
        sample_rate_hz=sample_rate_hz,
        buffer_seconds=buffer_seconds,
        stream_points=int(os.getenv("PICKUP_EDS_STREAM_POINTS", "2000")),
        stream_window_s=float(os.getenv("PICKUP_EDS_STREAM_WINDOW_S", "8")),
    )

