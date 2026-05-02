from __future__ import annotations

import logging
import os
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
from pickup_eds.instruments.electrometer_serial import Real6514Serial
from pickup_eds.instruments.simulator import SimulatedBenchService

logger = logging.getLogger(__name__)
SETTINGS = load_settings()
WEB_DIR = Path(__file__).resolve().parents[1] / "web"

# Env-var contract for the temporary real-SCPI bridge.
# - Unset / "auto" (default): try to open the serial port, fall back to
#   simulator if the device isn't there. Safe for both lab and laptop.
# - "1" / "on" / "true":     hard-require real SCPI; raise on failure.
# - "0" / "off" / "false":   never touch serial, force simulator.
_REAL_SCPI_MODE = os.environ.get("PICKUP_EDS_REAL_SCPI", "auto").lower()
_REAL_SCPI_PORT = os.environ.get("PICKUP_EDS_SCPI_PORT", "/dev/ttyUSB0")


async def _maybe_open_real_scpi() -> Real6514Serial | None:
    """Try to bring up the physical SCPI link; honor _REAL_SCPI_MODE."""
    if _REAL_SCPI_MODE in {"0", "off", "false", "no"}:
        return None
    bridge = Real6514Serial(port=_REAL_SCPI_PORT)
    try:
        await bridge.open()
        return bridge
    except Exception as exc:
        if _REAL_SCPI_MODE in {"1", "on", "true", "yes"}:
            # Caller asked for hard-required real mode; surface the error.
            raise
        logger.warning(
            "real SCPI link unavailable on %s (%s); falling back to simulator",
            _REAL_SCPI_PORT,
            exc,
        )
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    real_scpi = await _maybe_open_real_scpi()
    service = SimulatedBenchService(SETTINGS, real_scpi=real_scpi)
    await service.start()
    app.state.service = service
    try:
        yield
    finally:
        await service.stop()
        if real_scpi is not None:
            await real_scpi.close()


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


@app.get("/favicon.ico")
async def favicon() -> FileResponse:
    # Browsers request /favicon.ico unconditionally; serve the same PNG
    # that the HTML <link rel="icon"> points at to silence 404 noise.
    return FileResponse(WEB_DIR / "favicon.png")


@app.get("/api/health")
async def health(request: Request) -> dict[str, object]:
    service: SimulatedBenchService = request.app.state.service
    real = service._real_scpi  # noqa: SLF001 — thin diagnostic only
    return {
        "ok": True,
        "mode": "simulated-webui-mvp",
        "scpi_link": "real" if (real and real.is_open()) else "simulated",
        "scpi_port": real.port if real else None,
    }


@app.get("/api/state")
async def state(request: Request) -> dict[str, object]:
    service: SimulatedBenchService = request.app.state.service
    snapshot = await service.snapshot_state()
    return snapshot.model_dump(mode="json")
