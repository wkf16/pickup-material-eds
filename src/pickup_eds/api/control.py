from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from pickup_eds.instruments.base import BenchServiceProtocol
from pickup_eds.schemas import FunctionRequest, RangeRequest, ScpiCommandRequest, ToggleRequest

router = APIRouter(prefix="/api/control", tags=["control"])


def _service(request: Request) -> BenchServiceProtocol:
    return request.app.state.service


@router.post("/function")
async def set_function(payload: FunctionRequest, request: Request) -> dict[str, object]:
    state = await _service(request).set_function(payload.func)
    return {"ok": True, "state": state.model_dump(mode="json")}


@router.post("/range")
async def set_range(payload: RangeRequest, request: Request) -> dict[str, object]:
    state = await _service(request).set_range(payload.range)
    return {"ok": True, "state": state.model_dump(mode="json")}


@router.post("/zero-check")
async def set_zero_check(payload: ToggleRequest, request: Request) -> dict[str, object]:
    state = await _service(request).set_zero_check(payload.on)
    return {"ok": True, "state": state.model_dump(mode="json")}


@router.post("/zero-correct")
async def set_zero_correct(payload: ToggleRequest, request: Request) -> dict[str, object]:
    state = await _service(request).set_zero_correct(payload.on)
    return {"ok": True, "state": state.model_dump(mode="json")}


@router.get("/scpi/log")
async def get_scpi_log(request: Request) -> dict[str, object]:
    service = _service(request)
    entries = await service.scpi_log()
    snapshot = await service.snapshot_state()
    return {
        "port": snapshot.scpi_port,
        "items": [entry.model_dump(mode="json") for entry in entries],
    }


@router.post("/scpi/send")
async def send_scpi(payload: ScpiCommandRequest, request: Request) -> dict[str, object]:
    service = _service(request)
    entry = await service.send_scpi(payload.command)
    state = await service.snapshot_state()
    return {
        "ok": entry.ok,
        "entry": entry.model_dump(mode="json"),
        "state": state.model_dump(mode="json"),
    }


# ─── Phase 2: DAQ task control ───────────────────────────────────────────

class DaqRunRequest(BaseModel):
    sample_rate_hz: int = Field(default=5000, gt=0, le=50000)
    channels: list[str] = Field(default_factory=lambda: ["ai0"])
    terminal: str = Field(default="RSE")
    range_v: float = Field(default=10.0, gt=0, le=10.0)


@router.post("/daq/run")
async def daq_run(payload: DaqRunRequest, request: Request) -> dict[str, object]:
    state = await _service(request).daq_run(payload.model_dump())
    return {"ok": True, "state": state.model_dump(mode="json")}


@router.post("/daq/pause")
async def daq_pause(request: Request) -> dict[str, object]:
    state = await _service(request).daq_pause()
    return {"ok": True, "state": state.model_dump(mode="json")}


@router.post("/daq/stop")
async def daq_stop(request: Request) -> dict[str, object]:
    state = await _service(request).daq_stop()
    return {"ok": True, "state": state.model_dump(mode="json")}


@router.post("/daq/single")
async def daq_single(payload: DaqRunRequest, request: Request) -> dict[str, object]:
    state = await _service(request).daq_single(payload.model_dump())
    return {"ok": True, "state": state.model_dump(mode="json")}


# ─── Phase 2: Analog output (free-run only; HW sync → Phase 2.5) ─────────

class AoStartRequest(BaseModel):
    mode: str = Field(default="DC")
    channel: str = Field(default="ao0")
    params: dict[str, Any] = Field(default_factory=dict)


@router.post("/ao/start")
async def ao_start(payload: AoStartRequest, request: Request) -> dict[str, object]:
    state = await _service(request).ao_start(payload.model_dump())
    return {"ok": True, "state": state.model_dump(mode="json")}


@router.post("/ao/stop")
async def ao_stop(request: Request) -> dict[str, object]:
    state = await _service(request).ao_stop()
    return {"ok": True, "state": state.model_dump(mode="json")}
