from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from pickup_eds.instruments.simulator import SimulatedBenchService
from pickup_eds.schemas import FunctionRequest, RangeRequest, ToggleRequest

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

