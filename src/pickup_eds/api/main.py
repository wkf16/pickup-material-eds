from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from pickup_eds.api.control import router as control_router
from pickup_eds.api.data import router as data_router
from pickup_eds.api.recording import router as recording_router
from pickup_eds.api.ws import router as ws_router
from pickup_eds.config import load_settings
from pickup_eds.instruments.simulator import SimulatedBenchService

SETTINGS = load_settings()
WEB_DIR = Path(__file__).resolve().parents[1] / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    service = SimulatedBenchService(SETTINGS)
    await service.start()
    app.state.service = service
    try:
        yield
    finally:
        await service.stop()


app = FastAPI(
    title="pickup-material-eds webui",
    version="0.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
app.include_router(control_router)
app.include_router(recording_router)
app.include_router(data_router)
app.include_router(ws_router)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, object]:
    return {"ok": True, "mode": "simulated-webui-mvp"}


@app.get("/api/state")
async def state(request: Request) -> dict[str, object]:
    service: SimulatedBenchService = request.app.state.service
    snapshot = await service.snapshot_state()
    return snapshot.model_dump(mode="json")
