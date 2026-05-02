from __future__ import annotations

from fastapi import APIRouter, Request

from pickup_eds.instruments.simulator import SimulatedBenchService
from pickup_eds.schemas import FunctionRequest, RangeRequest, ScpiCommandRequest, ToggleRequest

router = APIRouter(prefix="/api/control", tags=["control"])


def _service(request: Request) -> SimulatedBenchService:
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
