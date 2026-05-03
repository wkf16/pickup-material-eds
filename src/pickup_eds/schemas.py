from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


InstrumentFunction = Literal["VOLT", "CURR", "RES", "CHARGE"]


class FunctionRequest(BaseModel):
    func: InstrumentFunction


class RangeRequest(BaseModel):
    range: float = Field(gt=0)


class ToggleRequest(BaseModel):
    on: bool


class ScpiCommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=256)


RecordingFormat = Literal["npz", "csv"]


class RecordingStartRequest(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    duration_s: float | None = Field(default=5.0, gt=0, le=3600)
    format: RecordingFormat = "npz"


class DatasetSummary(BaseModel):
    id: str
    label: str
    created_at: datetime
    duration_s: float
    sample_rate_hz: int
    sample_count: int
    file_path: str
    file_size_bytes: int
    min_value: float
    max_value: float


class ControlState(BaseModel):
    function: InstrumentFunction
    range: float
    zero_check: bool
    zero_correct: bool


DaqRunState = Literal["idle", "running", "paused", "single"]
AoRunState = Literal["idle", "running"]
BridgeStateName = Literal[
    "disconnected",
    "reconnecting",
    "connected_idle",
    "running",
    "paused",
    "error",
]


class DaqState(BaseModel):
    sample_rate_hz: int
    display_window_s: float
    live_rms: float
    live_peak: float
    display_points: int
    state: DaqRunState = "idle"
    channels: list[str] = ["ai0"]
    terminal: Literal["RSE", "DIFF"] = "RSE"
    range_v: float = 10.0
    samples_emitted: int = 0
    overruns: int = 0


class AoState(BaseModel):
    state: AoRunState = "idle"
    mode: Literal["DC", "Sine", "Sweep-lin", "Sweep-log", "Chirp", "File replay"] | None = None
    channel: str = "ao0"
    params: dict[str, float] = {}


class BridgeState(BaseModel):
    state: BridgeStateName
    daemon_addr: str
    rtt_ms: float | None = None
    last_seq: int = 0
    last_error: str | None = None


class RecordingState(BaseModel):
    active: bool
    label: str | None = None
    started_at: datetime | None = None
    duration_s: float | None = None
    sample_count: int = 0
    last_dataset_id: str | None = None


class ScpiLogEntry(BaseModel):
    at: datetime
    port: str
    command: str
    response: str
    ok: bool = True


class AppState(BaseModel):
    updated_at: datetime
    control: ControlState
    daq: DaqState
    recording: RecordingState
    datasets: list[DatasetSummary]
    scpi_port: str
    scpi_log: list[ScpiLogEntry] = []
    ao: AoState = AoState()
    bridge: BridgeState | None = None
