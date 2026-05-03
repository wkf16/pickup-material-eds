from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from pickup_eds.instruments.base import BenchServiceProtocol

router = APIRouter(tags=["ws"])


def _service(websocket: WebSocket) -> BenchServiceProtocol:
    return websocket.app.state.service


@router.websocket("/ws/stream")
async def stream_waveform(websocket: WebSocket) -> None:
    await websocket.accept()
    service = _service(websocket)
    try:
        while True:
            await websocket.send_json(await service.stream_frame())
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        return


@router.websocket("/ws/state")
async def stream_state(websocket: WebSocket) -> None:
    await websocket.accept()
    service = _service(websocket)
    queue = service.add_state_watcher()
    await queue.put((await service.snapshot_state()).model_dump(mode="json"))
    try:
        while True:
            payload = await queue.get()
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        service.remove_state_watcher(queue)


@router.websocket("/ws/snapshot")
async def stream_snapshot(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        await websocket.send_json(
            {
                "available": False,
                "message": "Snapshot triggering is reserved for the real DAQ backend.",
            }
        )
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"available": False, "heartbeat": True})
    except WebSocketDisconnect:
        return

