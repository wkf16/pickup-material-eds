from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from pickup_eds.instruments.base import BenchServiceProtocol
from pickup_eds.schemas import RecordingStartRequest

router = APIRouter(prefix="/api/recording", tags=["recording"])


def _service(request: Request) -> BenchServiceProtocol:
    return request.app.state.service


@router.post("/start")
async def start_recording(
    payload: RecordingStartRequest,
    request: Request,
) -> dict[str, object]:
    try:
        state = await _service(request).start_recording(payload.label, payload.duration_s)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "state": state.model_dump(mode="json")}


@router.post("/stop")
async def stop_recording(request: Request) -> dict[str, object]:
    state, dataset = await _service(request).stop_recording()
    return {
        "ok": True,
        "state": state.model_dump(mode="json"),
        "dataset": dataset.model_dump(mode="json") if dataset else None,
    }

