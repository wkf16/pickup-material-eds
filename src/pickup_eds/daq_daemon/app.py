"""DAQ daemon FastAPI surface — runs on the Windows VM at :8765.

Endpoints (matching docs/phase2-design.md §6):

  GET  /api/health          → daemon status, daq_device, scpi_com, idn
  POST /api/daq/start       → body {sample_rate_hz, channels, terminal, range_v}
  POST /api/daq/stop
  GET  /api/daq/status
  POST /api/scpi/send       body {cmd}
  GET  /api/scpi/state
  WS   /ws/raw_stream       binary frames (header + interleaved float32)
"""
from __future__ import annotations

import asyncio
import logging
import os
import struct
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from pickup_eds.daq_daemon import FRAME_HEADER_FMT
from pickup_eds.daq_daemon.daq_worker import DaqConfig, DaqWorker, FrameTuple
from pickup_eds.daq_daemon.recovery import wait_for_nidaq

logger = logging.getLogger(__name__)


# ─── State ─────────────────────────────────────────────────────────────

class DaemonState:
    def __init__(self) -> None:
        self.started_at = time.time()
        self.daq_device: Optional[str] = None
        self.scpi_com: Optional[str] = None
        self.scpi_idn: str = ""
        self.worker: Optional[DaqWorker] = None
        self.scpi: object | None = None  # ScpiProxy, kept loose-typed
        self.subscribers: set[asyncio.Queue[FrameTuple]] = set()
        self.last_error: Optional[str] = None


STATE = DaemonState()


# ─── Lifespan ──────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("daq daemon starting up")
    # 1. NI-DAQmx sanity (with a single PnP rescan if nothing visible).
    if wait_for_nidaq(retries=3):
        from pickup_eds.daq_daemon.discovery import find_usb6002
        try:
            STATE.daq_device = find_usb6002()
            logger.info("DAQ device: %s", STATE.daq_device)
            STATE.worker = DaqWorker(STATE.daq_device)
        except Exception as exc:
            STATE.last_error = f"DAQ discovery failed: {exc}"
            logger.error(STATE.last_error)
    else:
        STATE.last_error = "no NI DAQ device visible after PnP rescan"
        logger.error(STATE.last_error)

    # 2. 6514 SCPI.
    from pickup_eds.daq_daemon.discovery import find_keithley_com
    from pickup_eds.daq_daemon.scpi_proxy import ScpiProxy
    try:
        com = find_keithley_com()
        proxy = ScpiProxy(com)
        await proxy.open()
        STATE.scpi_com = com
        STATE.scpi = proxy
        STATE.scpi_idn = proxy.idn
        logger.info("6514 on %s: %s", com, proxy.idn)
    except Exception as exc:
        STATE.last_error = (STATE.last_error or "") + f" | SCPI discovery failed: {exc}"
        logger.warning("6514 discovery failed: %s", exc)

    # 3. Frame fan-out task: pull from worker queue (blocking thread queue,
    #    polled with a small sleep) and broadcast to subscriber asyncio
    #    queues.
    fanout_task = asyncio.create_task(_fanout_loop(), name="daq-fanout")

    try:
        yield
    finally:
        logger.info("daq daemon shutting down")
        fanout_task.cancel()
        try:
            await fanout_task
        except (asyncio.CancelledError, Exception):
            pass
        if STATE.worker is not None:
            STATE.worker.stop()
        if STATE.scpi is not None:
            try:
                await STATE.scpi.close()  # type: ignore[attr-defined]
            except Exception:
                pass


async def _fanout_loop() -> None:
    """Poll the worker's threading.Queue and broadcast frames to WS subscribers."""
    while True:
        try:
            if STATE.worker is None or not STATE.subscribers:
                await asyncio.sleep(0.05)
                continue
            try:
                frame = STATE.worker.frames_queue.get_nowait()
            except Exception:
                await asyncio.sleep(0.01)
                continue
            for q in list(STATE.subscribers):
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                try:
                    q.put_nowait(frame)
                except asyncio.QueueFull:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("fanout loop error; continuing")
            await asyncio.sleep(0.1)


# ─── App ───────────────────────────────────────────────────────────────

app = FastAPI(title="pickup-eds daq daemon", version="0.1.0", lifespan=lifespan)


# ─── Health ────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health() -> dict[str, object]:
    w = STATE.worker
    return {
        "ok": STATE.daq_device is not None,
        "uptime_s": round(time.time() - STATE.started_at, 1),
        "daq_device": STATE.daq_device,
        "scpi_com": STATE.scpi_com,
        "scpi_idn": STATE.scpi_idn,
        "daq_state": "running" if (w and w.is_running) else "idle",
        "samples_emitted": (w.samples_emitted if w else 0),
        "overruns": (w.overruns if w else 0),
        "last_error": STATE.last_error,
    }


# ─── DAQ task control ──────────────────────────────────────────────────

class DaqStartRequest(BaseModel):
    sample_rate_hz: int = Field(gt=0, le=50000)
    channels: list[str] = Field(default_factory=lambda: ["ai0"])
    terminal: str = Field(default="RSE")
    range_v: float = Field(default=10.0, gt=0, le=10.0)


@app.post("/api/daq/start")
async def daq_start(payload: DaqStartRequest) -> dict[str, object]:
    if STATE.worker is None:
        raise HTTPException(status_code=503, detail="DAQ device not initialized")
    if STATE.worker.is_running:
        STATE.worker.stop()
    cfg = DaqConfig(
        sample_rate_hz=payload.sample_rate_hz,
        channels=list(payload.channels),
        terminal=payload.terminal.upper(),
        range_v=payload.range_v,
    )
    STATE.worker.start(cfg)
    return {"ok": True, "started_at": STATE.worker.started_at, "device": STATE.daq_device}


@app.post("/api/daq/stop")
async def daq_stop() -> dict[str, object]:
    if STATE.worker is None:
        raise HTTPException(status_code=503, detail="DAQ device not initialized")
    STATE.worker.stop()
    return {"ok": True, "samples_emitted": STATE.worker.samples_emitted, "overruns": STATE.worker.overruns}


@app.get("/api/daq/status")
async def daq_status() -> dict[str, object]:
    w = STATE.worker
    if w is None:
        return {"state": "uninitialized"}
    return {
        "state": "running" if w.is_running else "idle",
        "samples_emitted": w.samples_emitted,
        "overruns": w.overruns,
        "seq_counter": w.seq_counter,
        "last_error": w.last_error,
    }


# ─── SCPI passthrough ──────────────────────────────────────────────────

class ScpiSendRequest(BaseModel):
    cmd: str = Field(min_length=1, max_length=256)


@app.post("/api/scpi/send")
async def scpi_send(payload: ScpiSendRequest) -> dict[str, object]:
    if STATE.scpi is None:
        raise HTTPException(status_code=503, detail="SCPI link not initialized")
    result = await STATE.scpi.send(payload.cmd)  # type: ignore[attr-defined]
    return {
        "ok": result.ok,
        "resp": result.response,
        "elapsed_ms": round(result.elapsed_ms, 2),
    }


@app.get("/api/scpi/state")
async def scpi_state() -> dict[str, object]:
    if STATE.scpi is None:
        return {"available": False}
    return {
        "available": True,
        "com": STATE.scpi_com,
        "idn": STATE.scpi_idn,
    }


# ─── Raw waveform stream ───────────────────────────────────────────────

@app.websocket("/ws/raw_stream")
async def raw_stream(ws: WebSocket) -> None:
    await ws.accept()
    queue: asyncio.Queue[FrameTuple] = asyncio.Queue(maxsize=8)
    STATE.subscribers.add(queue)
    try:
        while True:
            frame = await queue.get()
            header = struct.pack(
                FRAME_HEADER_FMT,
                frame.seq,
                frame.sample_count,
                frame.sample_rate_hz,
                frame.channel_count,
            )
            await ws.send_bytes(header + frame.samples.tobytes())
    except WebSocketDisconnect:
        pass
    finally:
        STATE.subscribers.discard(queue)
