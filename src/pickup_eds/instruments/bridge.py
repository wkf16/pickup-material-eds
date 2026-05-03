"""Linux-side bridge to the Windows VM DAQ daemon.

Two classes:

  * ``BridgeClient`` — owns the WS data connection + REST control plane.
    State machine: disconnected → reconnecting → connected_idle →
    running ↔ paused → error. Exponential backoff on reconnect.

  * ``RealBenchService`` — implements ``BenchServiceProtocol`` by feeding
    samples from BridgeClient into a local ring buffer; ``stream_frame``,
    recording, and SCPI passthrough all sit on top.
"""
from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np

import websockets
from websockets.exceptions import ConnectionClosed

from pickup_eds.config import Settings
from pickup_eds.core.ring_buffer import RingBuffer, decimate_pair
from pickup_eds.core.storage import StorageManager
from pickup_eds.daq_daemon import FRAME_HEADER_FMT
from pickup_eds.schemas import (
    AoState,
    AppState,
    BridgeState,
    ControlState,
    DaqState,
    DatasetSummary,
    RecordingState,
    ScpiLogEntry,
)

logger = logging.getLogger(__name__)


# ─── BridgeClient ─────────────────────────────────────────────────────

class BridgeClient:
    """WebSocket + REST client for the VM daq daemon."""

    def __init__(self, ws_url: str, *, sample_rate_hz: int) -> None:
        self._ws_url = ws_url
        # Derive REST base by swapping ws→http and stripping path.
        u = urlparse(ws_url)
        scheme = "http" if u.scheme == "ws" else "https"
        self._http_base = f"{scheme}://{u.netloc}"
        self._sample_rate_hz = sample_rate_hz
        self.state: str = "disconnected"
        self.last_error: str | None = None
        self.last_seq: int = 0
        self.rtt_ms: float | None = None
        self._ws_task: asyncio.Task[None] | None = None
        self._stop_flag = False
        self._frame_queue: asyncio.Queue[tuple[int, float, int, np.ndarray]] = asyncio.Queue(maxsize=64)
        self._state_callback = None  # type: ignore[var-annotated]
        self._http_session = None  # type: ignore[var-annotated]

    @property
    def daemon_addr(self) -> str:
        return self._ws_url

    def on_state_change(self, callback) -> None:  # type: ignore[no-untyped-def]
        self._state_callback = callback

    async def _set_state(self, new: str, err: str | None = None) -> None:
        if self.state == new and self.last_error == err:
            return
        logger.info("bridge state %s -> %s%s", self.state, new, f" (err={err})" if err else "")
        self.state = new
        self.last_error = err
        if self._state_callback is not None:
            try:
                await self._state_callback()
            except Exception:
                logger.exception("state callback failed")

    async def start(self) -> None:
        import httpx
        self._http_session = httpx.AsyncClient(timeout=10.0)
        self._stop_flag = False
        self._ws_task = asyncio.create_task(self._ws_loop(), name="bridge-ws")

    async def stop(self) -> None:
        self._stop_flag = True
        if self._ws_task is not None:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._http_session is not None:
            await self._http_session.aclose()
            self._http_session = None
        await self._set_state("disconnected")

    async def frames(self):
        """Async iterator yielding (seq, sample_rate_hz, channel_count, samples) tuples."""
        while not self._stop_flag:
            try:
                yield await asyncio.wait_for(self._frame_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

    async def _ws_loop(self) -> None:
        backoff = 1.0
        max_backoff = 8.0
        retry_n = 0
        while not self._stop_flag:
            await self._set_state("reconnecting" if retry_n else "reconnecting")
            try:
                async with websockets.connect(self._ws_url, max_size=4 * 1024 * 1024) as ws:
                    retry_n = 0
                    backoff = 1.0
                    await self._set_state("running")
                    async for raw in ws:
                        if not isinstance(raw, (bytes, bytearray)):
                            continue
                        if len(raw) < struct.calcsize(FRAME_HEADER_FMT):
                            continue
                        seq, n, sr, c = struct.unpack(FRAME_HEADER_FMT, raw[:struct.calcsize(FRAME_HEADER_FMT)])
                        body = raw[struct.calcsize(FRAME_HEADER_FMT):]
                        samples = np.frombuffer(body, dtype=np.float32)
                        # Drop oldest frame if buffer full.
                        if self._frame_queue.full():
                            try:
                                self._frame_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                        try:
                            self._frame_queue.put_nowait((seq, float(sr), int(c), samples))
                            self.last_seq = seq
                        except asyncio.QueueFull:
                            pass
            except (OSError, ConnectionClosed) as exc:
                retry_n += 1
                logger.warning("bridge ws disconnected (retry %d): %s", retry_n, exc)
                if retry_n >= 5:
                    await self._set_state("error", err=str(exc))
                else:
                    await self._set_state("reconnecting", err=str(exc))
                await asyncio.sleep(min(backoff, max_backoff))
                backoff = min(backoff * 2, max_backoff)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("bridge ws unexpected error")
                await self._set_state("error", err=str(exc))
                await asyncio.sleep(min(backoff, max_backoff))
                backoff = min(backoff * 2, max_backoff)

    # ─── REST ───────────────────────────────────────────────────────

    async def daq_start(self, cfg: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/api/daq/start", cfg)

    async def daq_stop(self) -> dict[str, Any]:
        return await self._post("/api/daq/stop", {})

    async def daq_status(self) -> dict[str, Any]:
        return await self._get("/api/daq/status")

    async def send_scpi(self, cmd: str) -> dict[str, Any]:
        return await self._post("/api/scpi/send", {"cmd": cmd})

    async def scpi_state(self) -> dict[str, Any]:
        return await self._get("/api/scpi/state")

    async def health(self) -> dict[str, Any]:
        return await self._get("/api/health")

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if self._http_session is None:
            raise RuntimeError("BridgeClient not started")
        t0 = time.perf_counter()
        r = await self._http_session.post(self._http_base + path, json=body)
        self.rtt_ms = (time.perf_counter() - t0) * 1000
        r.raise_for_status()
        return r.json()

    async def _get(self, path: str) -> dict[str, Any]:
        if self._http_session is None:
            raise RuntimeError("BridgeClient not started")
        t0 = time.perf_counter()
        r = await self._http_session.get(self._http_base + path)
        self.rtt_ms = (time.perf_counter() - t0) * 1000
        r.raise_for_status()
        return r.json()


# ─── RealBenchService ─────────────────────────────────────────────────

class RealBenchService:
    """Bench service backed by a Windows-VM DAQ daemon (via BridgeClient).

    Mirrors SimulatedBenchService's public surface so api/* don't care
    which backend is wired up.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        bridge_url: str,
    ) -> None:
        self._settings = settings
        self._storage = StorageManager(settings.data_dir)
        self._buffer = RingBuffer(settings.sample_rate_hz * settings.buffer_seconds)
        self._control = ControlState(function="VOLT", range=2.0, zero_check=False, zero_correct=False)
        self._recording = RecordingState(active=False)
        self._datasets: list[DatasetSummary] = []
        self._scpi_log: list[ScpiLogEntry] = []
        self._scpi_port: str = "(not connected)"
        self._record_times: list[np.ndarray] = []
        self._record_values: list[np.ndarray] = []
        self._record_format: str = "npz"
        self._lock = asyncio.Lock()
        self._state_watchers: set[asyncio.Queue[dict[str, object]]] = set()
        self._stream_seq = 0
        self._sample_cursor = 0
        self._last_rms = 0.0
        self._last_peak = 0.0
        self._daq_state: str = "idle"
        self._daq_channels: list[str] = ["ai0"]
        self._daq_terminal: str = "RSE"
        self._daq_range_v: float = 10.0
        self._daq_samples_emitted: int = 0
        self._daq_overruns: int = 0
        self._sample_rate_hz: int = settings.sample_rate_hz
        self._ao = AoState()
        self._consume_task: asyncio.Task[None] | None = None
        self._auto_stop_task: asyncio.Task[None] | None = None
        self.bridge = BridgeClient(bridge_url, sample_rate_hz=settings.sample_rate_hz)

    @property
    def data_dir(self) -> Path:
        return self._settings.data_dir

    # ─── Lifecycle ──────────────────────────────────────────────

    async def start(self) -> None:
        self._storage.initialize()
        self._datasets = self._storage.list_datasets()
        self.bridge.on_state_change(self._broadcast_state)
        await self.bridge.start()
        # Probe scpi_state once (best-effort) to populate scpi_port.
        try:
            ss = await self.bridge.scpi_state()
            if ss.get("available"):
                self._scpi_port = f"{ss.get('com')} (real)"
        except Exception as exc:
            logger.warning("initial scpi_state fetch failed: %s", exc)
        self._consume_task = asyncio.create_task(self._consume_frames(), name="real-bench-consume")
        await self._broadcast_state()

    async def stop(self) -> None:
        if self._auto_stop_task is not None:
            self._auto_stop_task.cancel()
            try:
                await self._auto_stop_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._consume_task is not None:
            self._consume_task.cancel()
            try:
                await self._consume_task
            except (asyncio.CancelledError, Exception):
                pass
        await self.bridge.stop()

    # ─── State ──────────────────────────────────────────────────

    def _bridge_snapshot(self) -> BridgeState:
        return BridgeState(
            state=self.bridge.state,  # type: ignore[arg-type]
            daemon_addr=self.bridge.daemon_addr,
            rtt_ms=self.bridge.rtt_ms,
            last_seq=self.bridge.last_seq,
            last_error=self.bridge.last_error,
        )

    def _daq_snapshot(self) -> DaqState:
        return DaqState(
            sample_rate_hz=self._sample_rate_hz,
            display_window_s=self._settings.stream_window_s,
            live_rms=self._last_rms,
            live_peak=self._last_peak,
            display_points=self._settings.stream_points,
            state=self._daq_state,  # type: ignore[arg-type]
            channels=list(self._daq_channels),
            terminal=self._daq_terminal,  # type: ignore[arg-type]
            range_v=self._daq_range_v,
            samples_emitted=self._daq_samples_emitted,
            overruns=self._daq_overruns,
        )

    async def snapshot_state(self) -> AppState:
        async with self._lock:
            return AppState(
                updated_at=datetime.now(UTC),
                control=self._control,
                daq=self._daq_snapshot(),
                recording=self._recording,
                datasets=self._datasets[:20],
                scpi_port=self._scpi_port,
                scpi_log=self._scpi_log[:12],
                ao=self._ao,
                bridge=self._bridge_snapshot(),
            )

    def add_state_watcher(self) -> asyncio.Queue[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=4)
        self._state_watchers.add(queue)
        return queue

    def remove_state_watcher(self, queue: asyncio.Queue[dict[str, object]]) -> None:
        self._state_watchers.discard(queue)

    async def _broadcast_state(self) -> None:
        if not self._state_watchers:
            return
        payload = (await self.snapshot_state()).model_dump(mode="json")
        stale: list[asyncio.Queue[dict[str, object]]] = []
        for q in self._state_watchers:
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    stale.append(q)
                    continue
            q.put_nowait(payload)
        for q in stale:
            self._state_watchers.discard(q)

    # ─── 6514 control toggles (route to SCPI) ──────────────────

    async def set_function(self, func: str) -> AppState:
        # Standard SCPI for 6514 function: ":FUNC 'VOLT:DC'" etc.
        # Simpler form "FUNC <name>" works on this firmware.
        scpi_alias = {"VOLT": "VOLT:DC", "CURR": "CURR:DC", "RES": "RES", "CHARGE": "CHAR"}.get(func, func)
        await self._send_scpi_internal(f'FUNC "{scpi_alias}"')
        async with self._lock:
            self._control = self._control.model_copy(update={"function": func})
        await self._broadcast_state()
        return await self.snapshot_state()

    async def set_range(self, range_value: float) -> AppState:
        await self._send_scpi_internal(f"RANG {range_value}")
        async with self._lock:
            self._control = self._control.model_copy(update={"range": range_value})
        await self._broadcast_state()
        return await self.snapshot_state()

    async def set_zero_check(self, on: bool) -> AppState:
        await self._send_scpi_internal(f"SYST:ZCH {'ON' if on else 'OFF'}")
        async with self._lock:
            self._control = self._control.model_copy(update={"zero_check": on})
        await self._broadcast_state()
        return await self.snapshot_state()

    async def set_zero_correct(self, on: bool) -> AppState:
        await self._send_scpi_internal(f"SYST:ZCOR {'ON' if on else 'OFF'}")
        async with self._lock:
            self._control = self._control.model_copy(update={"zero_correct": on})
        await self._broadcast_state()
        return await self.snapshot_state()

    # ─── SCPI ──────────────────────────────────────────────────

    async def scpi_log(self) -> list[ScpiLogEntry]:
        async with self._lock:
            return self._scpi_log[:20]

    async def send_scpi(self, command: str) -> ScpiLogEntry:
        return await self._send_scpi_internal(command.strip())

    async def _send_scpi_internal(self, cmd: str) -> ScpiLogEntry:
        try:
            r = await self.bridge.send_scpi(cmd)
            response = str(r.get("resp", ""))
            ok = bool(r.get("ok"))
        except Exception as exc:
            response = f"ERR: bridge: {exc}"
            ok = False
        entry = ScpiLogEntry(
            at=datetime.now(UTC),
            port=self._scpi_port,
            command=cmd,
            response=response,
            ok=ok,
        )
        async with self._lock:
            self._scpi_log = [entry, *self._scpi_log][:20]
        await self._broadcast_state()
        return entry

    # ─── Recording ─────────────────────────────────────────────

    async def start_recording(self, label: str, duration_s: float | None, format: str = "npz") -> AppState:
        async with self._lock:
            if self._recording.active:
                raise RuntimeError("recording already active")
            self._record_times = []
            self._record_values = []
            self._record_format = format
            self._recording = RecordingState(
                active=True,
                label=label,
                started_at=datetime.now(UTC),
                duration_s=duration_s,
                sample_count=0,
                last_dataset_id=self._recording.last_dataset_id,
            )
        if duration_s is not None:
            self._auto_stop_task = asyncio.create_task(
                self._stop_recording_after(duration_s),
                name="real-bench-auto-stop",
            )
        await self._broadcast_state()
        return await self.snapshot_state()

    async def stop_recording(self) -> tuple[AppState, DatasetSummary | None]:
        async with self._lock:
            if not self._recording.active:
                last_id = self._recording.last_dataset_id
                inactive = AppState(
                    updated_at=datetime.now(UTC),
                    control=self._control,
                    daq=self._daq_snapshot(),
                    recording=self._recording,
                    datasets=self._datasets[:20],
                    scpi_port=self._scpi_port,
                    scpi_log=self._scpi_log[:12],
                    ao=self._ao,
                    bridge=self._bridge_snapshot(),
                )
                return inactive, self._storage.get_dataset(last_id) if last_id else None
            if self._auto_stop_task is not None:
                cur = asyncio.current_task()
                if self._auto_stop_task is not cur:
                    self._auto_stop_task.cancel()
                self._auto_stop_task = None
            times = np.concatenate(self._record_times) if self._record_times else np.array([], dtype=np.float64)
            values = np.concatenate(self._record_values) if self._record_values else np.array([], dtype=np.float64)
            label = self._recording.label or "untitled"
            self._recording = self._recording.model_copy(update={"active": False})

        summary = None
        if len(times) and len(values):
            summary = self._storage.save_recording(
                label=label, times=times, values=values,
                sample_rate_hz=self._sample_rate_hz,
                format=self._record_format,
            )
            async with self._lock:
                self._datasets = [summary, *self._datasets][:20]
                self._recording = self._recording.model_copy(
                    update={
                        "label": None, "started_at": None, "duration_s": None,
                        "sample_count": 0, "last_dataset_id": summary.id,
                    }
                )
        else:
            async with self._lock:
                self._recording = self._recording.model_copy(
                    update={"label": None, "started_at": None, "duration_s": None, "sample_count": 0}
                )

        await self._broadcast_state()
        return await self.snapshot_state(), summary

    async def _stop_recording_after(self, delay_s: float) -> None:
        try:
            await asyncio.sleep(delay_s)
            await self.stop_recording()
        except asyncio.CancelledError:
            raise

    async def datasets(self) -> list[DatasetSummary]:
        return self._storage.list_datasets()

    async def preview_dataset(self, dataset_id: str) -> dict[str, object] | None:
        return self._storage.load_preview(dataset_id)

    async def get_dataset(self, dataset_id: str) -> DatasetSummary | None:
        return self._storage.get_dataset(dataset_id)

    # ─── DAQ task control (route to bridge) ─────────────────────

    async def daq_run(self, config: dict[str, Any]) -> AppState:
        sr = int(config.get("sample_rate_hz", self._sample_rate_hz))
        cfg = {
            "sample_rate_hz": sr,
            "channels": list(config.get("channels", ["ai0"])),
            "terminal": str(config.get("terminal", "RSE")).upper(),
            "range_v": float(config.get("range_v", 10.0)),
        }
        await self.bridge.daq_start(cfg)
        async with self._lock:
            self._sample_rate_hz = sr
            self._daq_channels = cfg["channels"]
            self._daq_terminal = cfg["terminal"]
            self._daq_range_v = cfg["range_v"]
            self._daq_state = "running"
            # Reset buffer when sample rate changes (capacity may differ).
            self._buffer = RingBuffer(sr * self._settings.buffer_seconds)
            self._sample_cursor = 0
        await self._broadcast_state()
        return await self.snapshot_state()

    async def daq_pause(self) -> AppState:
        # Pause = freeze display only; daemon keeps running.
        async with self._lock:
            self._daq_state = "paused"
        await self._broadcast_state()
        return await self.snapshot_state()

    async def daq_stop(self) -> AppState:
        try:
            await self.bridge.daq_stop()
        except Exception as exc:
            logger.warning("daq_stop on bridge failed: %s", exc)
        async with self._lock:
            self._daq_state = "idle"
        await self._broadcast_state()
        return await self.snapshot_state()

    async def daq_single(self, config: dict[str, Any]) -> AppState:
        # Phase 2: implement as "run for ~1 window" — start, mark single,
        # the consume loop will flip back to idle after one window of data.
        await self.daq_run(config)
        async with self._lock:
            self._daq_state = "single"
        await self._broadcast_state()
        return await self.snapshot_state()

    # ─── AO ─────────────────────────────────────────────────────

    async def ao_start(self, config: dict[str, Any]) -> AppState:
        # Phase 2 stub: log it; daemon-side AO not implemented yet.
        async with self._lock:
            self._ao = AoState(
                state="running",
                mode=config.get("mode", "DC"),
                channel=config.get("channel", "ao0"),
                params=config.get("params", {}),
            )
        await self._broadcast_state()
        return await self.snapshot_state()

    async def ao_stop(self) -> AppState:
        async with self._lock:
            self._ao = AoState(state="idle", channel=self._ao.channel)
        await self._broadcast_state()
        return await self.snapshot_state()

    # ─── Stream frame for /ws/stream (browser-facing) ───────────

    async def stream_frame(self) -> dict[str, object]:
        max_samples = int(self._sample_rate_hz * self._settings.stream_window_s)
        times, values = self._buffer.tail(max_samples=max_samples)
        if len(times) == 0:
            return {
                "seq": self._stream_seq,
                "sample_rate_hz": self._sample_rate_hz,
                "time_s": [],
                "value": [],
                "rms": 0.0,
                "peak": 0.0,
            }
        times = times - times[0]
        times, values = decimate_pair(times, values, max_points=self._settings.stream_points)
        self._stream_seq += 1
        return {
            "seq": self._stream_seq,
            "sample_rate_hz": self._sample_rate_hz,
            "time_s": times.tolist(),
            "value": values.tolist(),
            "rms": round(self._last_rms, 6),
            "peak": round(self._last_peak, 6),
        }

    # ─── Frame consumer ─────────────────────────────────────────

    async def _consume_frames(self) -> None:
        last_state_push = 0.0
        loop = asyncio.get_running_loop()
        try:
            async for seq, sr, n_ch, samples in self.bridge.frames():
                if len(samples) == 0:
                    continue
                # Pull just channel 0 for the live display ring buffer.
                # (Multi-channel display is Phase 3 territory.)
                if n_ch > 1:
                    ch0 = samples.reshape(-1, n_ch)[:, 0].astype(np.float64, copy=False)
                else:
                    ch0 = samples.astype(np.float64, copy=False)
                n = len(ch0)
                times = (np.arange(n, dtype=np.float64) + self._sample_cursor) / max(sr, 1.0)
                self._sample_cursor += n
                # Update local state under lock.
                async with self._lock:
                    self._buffer.append_block(times, ch0)
                    self._last_rms = float(np.sqrt(np.mean(np.square(ch0))))
                    self._last_peak = float(np.max(np.abs(ch0)))
                    self._daq_samples_emitted += n
                    self._sample_rate_hz = int(round(sr))
                    if self._recording.active:
                        self._record_times.append(times.copy())
                        self._record_values.append(ch0.copy())
                        self._recording = self._recording.model_copy(
                            update={"sample_count": self._recording.sample_count + n}
                        )
                now = loop.time()
                if now - last_state_push >= 0.5:
                    last_state_push = now
                    await self._broadcast_state()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("consume_frames aborted")
