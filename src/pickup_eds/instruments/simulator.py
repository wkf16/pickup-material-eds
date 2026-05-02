from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import math
from pathlib import Path

import numpy as np

from pickup_eds.config import Settings
from pickup_eds.core.ring_buffer import RingBuffer, decimate_pair
from pickup_eds.core.storage import StorageManager
from pickup_eds.schemas import AppState, ControlState, DaqState, DatasetSummary, RecordingState, ScpiLogEntry


class SimulatedBenchService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._storage = StorageManager(settings.data_dir)
        self._buffer = RingBuffer(settings.sample_rate_hz * settings.buffer_seconds)
        self._control = ControlState(
            function="VOLT",
            range=2.0,
            zero_check=False,
            zero_correct=False,
        )
        self._recording = RecordingState(active=False)
        self._datasets: list[DatasetSummary] = []
        self._scpi_port = "COM3 (simulated)"
        self._scpi_log: list[ScpiLogEntry] = [
            ScpiLogEntry(
                at=datetime.now(UTC),
                port=self._scpi_port,
                command="*IDN?",
                response="KEITHLEY INSTRUMENTS INC.,MODEL 6514,4691930,1.0-sim",
            )
        ]
        self._record_times: list[np.ndarray] = []
        self._record_values: list[np.ndarray] = []
        self._lock = asyncio.Lock()
        self._state_watchers: set[asyncio.Queue[dict[str, object]]] = set()
        self._stream_seq = 0
        self._run_task: asyncio.Task[None] | None = None
        self._stop_recording_task: asyncio.Task[None] | None = None
        self._sample_cursor = 0
        self._started_monotonic = 0.0
        self._last_rms = 0.0
        self._last_peak = 0.0
        self._last_state_push = 0.0

    @property
    def data_dir(self) -> Path:
        return self._settings.data_dir

    async def start(self) -> None:
        self._storage.initialize()
        self._datasets = self._storage.list_datasets()
        self._started_monotonic = asyncio.get_running_loop().time()
        self._run_task = asyncio.create_task(self._run(), name="pickup-eds-simulator")
        await self._broadcast_state()

    async def stop(self) -> None:
        if self._stop_recording_task:
            self._stop_recording_task.cancel()
            await asyncio.gather(self._stop_recording_task, return_exceptions=True)
        if self._run_task:
            self._run_task.cancel()
            await asyncio.gather(self._run_task, return_exceptions=True)

    async def snapshot_state(self) -> AppState:
        async with self._lock:
            return AppState(
                updated_at=datetime.now(UTC),
                control=self._control,
                daq=DaqState(
                    sample_rate_hz=self._settings.sample_rate_hz,
                    display_window_s=self._settings.stream_window_s,
                    live_rms=self._last_rms,
                    live_peak=self._last_peak,
                    display_points=self._settings.stream_points,
                ),
                recording=self._recording,
                datasets=self._datasets[:20],
                scpi_port=self._scpi_port,
                scpi_log=self._scpi_log[:12],
            )

    async def set_function(self, func: str) -> AppState:
        async with self._lock:
            self._control = self._control.model_copy(update={"function": func})
        await self._broadcast_state()
        return await self.snapshot_state()

    async def set_range(self, range_value: float) -> AppState:
        async with self._lock:
            self._control = self._control.model_copy(update={"range": range_value})
        await self._broadcast_state()
        return await self.snapshot_state()

    async def set_zero_check(self, on: bool) -> AppState:
        async with self._lock:
            self._control = self._control.model_copy(update={"zero_check": on})
        await self._broadcast_state()
        return await self.snapshot_state()

    async def set_zero_correct(self, on: bool) -> AppState:
        async with self._lock:
            self._control = self._control.model_copy(update={"zero_correct": on})
        await self._broadcast_state()
        return await self.snapshot_state()

    async def start_recording(self, label: str, duration_s: float | None) -> AppState:
        async with self._lock:
            if self._recording.active:
                raise RuntimeError("recording already active")
            self._record_times = []
            self._record_values = []
            self._recording = RecordingState(
                active=True,
                label=label,
                started_at=datetime.now(UTC),
                duration_s=duration_s,
                sample_count=0,
                last_dataset_id=self._recording.last_dataset_id,
            )
        if duration_s is not None:
            self._stop_recording_task = asyncio.create_task(
                self._stop_recording_after_delay(duration_s),
                name="pickup-eds-auto-stop",
            )
        await self._broadcast_state()
        return await self.snapshot_state()

    async def stop_recording(self) -> tuple[AppState, DatasetSummary | None]:
        async with self._lock:
            if not self._recording.active:
                last_dataset_id = self._recording.last_dataset_id
                inactive_state = AppState(
                    updated_at=datetime.now(UTC),
                    control=self._control,
                    daq=DaqState(
                        sample_rate_hz=self._settings.sample_rate_hz,
                        display_window_s=self._settings.stream_window_s,
                        live_rms=self._last_rms,
                        live_peak=self._last_peak,
                        display_points=self._settings.stream_points,
                    ),
                    recording=self._recording,
                    datasets=self._datasets[:20],
                    scpi_port=self._scpi_port,
                    scpi_log=self._scpi_log[:12],
                )
                return inactive_state, self._storage.get_dataset(last_dataset_id) if last_dataset_id else None
            if self._stop_recording_task:
                self._stop_recording_task.cancel()
                self._stop_recording_task = None
            times = np.concatenate(self._record_times) if self._record_times else np.array([], dtype=np.float64)
            values = np.concatenate(self._record_values) if self._record_values else np.array([], dtype=np.float64)
            label = self._recording.label or "untitled"
            self._recording = self._recording.model_copy(update={"active": False})
        summary = None
        if len(times) and len(values):
            summary = self._storage.save_recording(
                label=label,
                times=times,
                values=values,
                sample_rate_hz=self._settings.sample_rate_hz,
            )
            async with self._lock:
                self._datasets = [summary, *self._datasets][:20]
                self._recording = self._recording.model_copy(
                    update={
                        "label": None,
                        "started_at": None,
                        "duration_s": None,
                        "sample_count": 0,
                        "last_dataset_id": summary.id,
                    }
                )
        else:
            async with self._lock:
                self._recording = self._recording.model_copy(
                    update={
                        "label": None,
                        "started_at": None,
                        "duration_s": None,
                        "sample_count": 0,
                    }
                )
        await self._broadcast_state()
        return await self.snapshot_state(), summary

    async def datasets(self) -> list[DatasetSummary]:
        return self._storage.list_datasets()

    async def scpi_log(self) -> list[ScpiLogEntry]:
        async with self._lock:
            return self._scpi_log[:20]

    async def send_scpi(self, command: str) -> ScpiLogEntry:
        normalized = command.strip()
        response, updates = self._simulate_scpi(normalized)
        async with self._lock:
            if updates:
                self._control = self._control.model_copy(update=updates)
            entry = ScpiLogEntry(
                at=datetime.now(UTC),
                port=self._scpi_port,
                command=normalized,
                response=response,
                ok=not response.startswith("ERR:"),
            )
            self._scpi_log = [entry, *self._scpi_log][:20]
        await self._broadcast_state()
        return entry

    async def preview_dataset(self, dataset_id: str) -> dict[str, object] | None:
        return self._storage.load_preview(dataset_id)

    async def get_dataset(self, dataset_id: str) -> DatasetSummary | None:
        return self._storage.get_dataset(dataset_id)

    async def stream_frame(self) -> dict[str, object]:
        max_samples = int(self._settings.sample_rate_hz * self._settings.stream_window_s)
        times, values = self._buffer.tail(max_samples=max_samples)
        if len(times) == 0:
            return {
                "seq": self._stream_seq,
                "sample_rate_hz": self._settings.sample_rate_hz,
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
            "sample_rate_hz": self._settings.sample_rate_hz,
            "time_s": times.tolist(),
            "value": values.tolist(),
            "rms": round(self._last_rms, 6),
            "peak": round(self._last_peak, 6),
        }

    def add_state_watcher(self) -> asyncio.Queue[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=4)
        self._state_watchers.add(queue)
        return queue

    def remove_state_watcher(self, queue: asyncio.Queue[dict[str, object]]) -> None:
        self._state_watchers.discard(queue)

    async def _run(self) -> None:
        sample_rate = self._settings.sample_rate_hz
        block_size = max(64, sample_rate // 20)
        sleep_s = block_size / sample_rate
        loop = asyncio.get_running_loop()
        try:
            while True:
                async with self._lock:
                    control = self._control
                    recording_active = self._recording.active
                times = (np.arange(block_size, dtype=np.float64) + self._sample_cursor) / sample_rate
                values = self._generate_signal(times, control=control)
                self._sample_cursor += block_size
                self._last_rms = float(np.sqrt(np.mean(np.square(values))))
                self._last_peak = float(np.max(np.abs(values)))
                self._buffer.append_block(times, values)
                if recording_active:
                    async with self._lock:
                        self._record_times.append(times.copy())
                        self._record_values.append(values.copy())
                        self._recording = self._recording.model_copy(
                            update={
                                "sample_count": self._recording.sample_count + len(values),
                            }
                        )
                now = loop.time()
                if now - self._last_state_push >= 0.5:
                    self._last_state_push = now
                    await self._broadcast_state()
                await asyncio.sleep(sleep_s)
        except asyncio.CancelledError:
            raise

    def _generate_signal(self, times: np.ndarray, *, control: ControlState) -> np.ndarray:
        base_amplitude = min(max(control.range / 4.0, 0.15), 3.0)
        if control.function == "CURR":
            base_amplitude *= 0.35
        elif control.function == "RES":
            base_amplitude *= 0.5
        elif control.function == "CHARGE":
            base_amplitude *= 0.8

        heartbeat = np.sin(2 * math.pi * 0.18 * times)
        carrier = np.sin(2 * math.pi * (7.5 + 1.2 * heartbeat) * times)
        overtone = 0.27 * np.sin(2 * math.pi * 19.0 * times + 0.4)
        flutter = 0.11 * np.sin(2 * math.pi * 47.0 * times + 0.8)
        noise = np.random.normal(0.0, base_amplitude * 0.02, size=len(times))
        values = base_amplitude * carrier + base_amplitude * overtone + flutter + noise
        if control.zero_check:
            values = np.random.normal(0.0, 0.01, size=len(times))
        if control.zero_correct:
            values = values - values.mean()
        return values.astype(np.float64)

    async def _stop_recording_after_delay(self, delay_s: float) -> None:
        try:
            await asyncio.sleep(delay_s)
            await self.stop_recording()
        except asyncio.CancelledError:
            raise

    async def _broadcast_state(self) -> None:
        if not self._state_watchers:
            return
        payload = (await self.snapshot_state()).model_dump(mode="json")
        stale_queues: list[asyncio.Queue[dict[str, object]]] = []
        for queue in self._state_watchers:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    stale_queues.append(queue)
                    continue
            queue.put_nowait(payload)
        for queue in stale_queues:
            self._state_watchers.discard(queue)

    def _simulate_scpi(self, command: str) -> tuple[str, dict[str, object]]:
        upper = command.upper()
        updates: dict[str, object] = {}
        if upper == "*IDN?":
            return "KEITHLEY INSTRUMENTS INC.,MODEL 6514,4691930,1.0-sim", updates
        if upper == "FUNC?":
            return self._control.function, updates
        if upper == "RANG?":
            return f"{self._control.range}", updates
        if upper in {"SYST:ZCH?", "ZERO:CHECK?"}:
            return "1" if self._control.zero_check else "0", updates
        if upper in {"SYST:ZCOR?", "ZERO:CORRECT?"}:
            return "1" if self._control.zero_correct else "0", updates
        if upper.startswith("FUNC "):
            value = upper.split(" ", 1)[1].strip().replace('"', "")
            aliases = {"VOLT:DC": "VOLT", "CURRENT:DC": "CURR", "RESISTANCE": "RES", "CHAR": "CHARGE"}
            mapped = aliases.get(value, value)
            if mapped in {"VOLT", "CURR", "RES", "CHARGE"}:
                updates["function"] = mapped
                return "OK", updates
            return "ERR: unsupported function", updates
        if upper.startswith("RANG "):
            raw = upper.split(" ", 1)[1].strip()
            try:
                updates["range"] = float(raw)
                return "OK", updates
            except ValueError:
                return "ERR: invalid range", updates
        if upper in {"SYST:ZCH ON", "ZERO:CHECK ON"}:
            updates["zero_check"] = True
            return "OK", updates
        if upper in {"SYST:ZCH OFF", "ZERO:CHECK OFF"}:
            updates["zero_check"] = False
            return "OK", updates
        if upper in {"SYST:ZCOR ON", "ZERO:CORRECT ON"}:
            updates["zero_correct"] = True
            return "OK", updates
        if upper in {"SYST:ZCOR OFF", "ZERO:CORRECT OFF"}:
            updates["zero_correct"] = False
            return "OK", updates
        if upper == "READ?":
            return f"{self._last_rms:.6f}", updates
        return "ERR: unsupported command in simulated backend", updates
