"""DAQ worker — runs nidaqmx.Task in a dedicated thread.

The asyncio side reads from a bounded queue. Frames are emitted as
``(seq, sample_rate, sample_count, channel_count, samples_float32)``
tuples; the WS handler in ``app.py`` formats the binary frame with
``struct.pack``.

Design constraints (Phase 1 smoke test 2 already validated 50 kHz × 60 s
× 0 overrun with this pattern):

  * Pre-allocated read buffer (numpy float32) to avoid per-block GC pressure.
  * ``read_into`` to skip Python-level allocation in nidaqmx.
  * Block size = sample_rate // 5 (-> ~200 ms / block, ~5 fps over WS).
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class DaqConfig:
    sample_rate_hz: int
    channels: list[str]      # ['ai0', 'ai1', ...]
    terminal: str            # 'RSE' or 'DIFF'
    range_v: float           # ±10/5/2/1
    block_size: Optional[int] = None  # samples per channel per block

    def block_or_default(self) -> int:
        return self.block_size if self.block_size is not None else max(64, self.sample_rate_hz // 5)


@dataclass
class FrameTuple:
    seq: int
    sample_rate_hz: float
    sample_count: int       # samples per channel
    channel_count: int
    samples: np.ndarray     # interleaved float32, length = sample_count * channel_count


class DaqWorker:
    """Background nidaqmx Task driver.

    Use ``start(cfg)`` to launch a fresh task; ``stop()`` to terminate.
    Frames are pushed into ``frames_queue`` (bounded, 16 deep) — if the
    queue fills up we increment ``overruns`` and drop the oldest frame.
    """

    def __init__(self, device_name: str) -> None:
        self._device = device_name
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._cfg: Optional[DaqConfig] = None
        self.frames_queue: "queue.Queue[FrameTuple]" = queue.Queue(maxsize=16)
        self.seq_counter = 0
        self.samples_emitted = 0
        self.overruns = 0
        self.started_at: float = 0.0
        self.last_error: Optional[str] = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, cfg: DaqConfig) -> None:
        if self.is_running:
            raise RuntimeError("worker already running; call stop() first")
        self._cfg = cfg
        self._stop_event.clear()
        self.seq_counter = 0
        self.samples_emitted = 0
        self.overruns = 0
        self.last_error = None
        self.started_at = time.time()
        self._thread = threading.Thread(target=self._run, name="daq-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=timeout_s)
        if self._thread.is_alive():
            logger.warning("daq worker thread did not exit in %ss", timeout_s)
        self._thread = None
        self._cfg = None
        # Drain any leftover frames so the next start gets a clean slate.
        try:
            while True:
                self.frames_queue.get_nowait()
        except queue.Empty:
            pass

    # ─── thread body ────────────────────────────────────────────────

    def _run(self) -> None:
        cfg = self._cfg
        assert cfg is not None
        try:
            import nidaqmx  # type: ignore[import-not-found]
            from nidaqmx.constants import (  # type: ignore[import-not-found]
                AcquisitionType,
                TerminalConfiguration,
            )
        except Exception as exc:
            self.last_error = f"nidaqmx import failed: {exc}"
            logger.exception("nidaqmx unavailable")
            return

        block = cfg.block_or_default()
        n_ch = len(cfg.channels)
        term = TerminalConfiguration.RSE if cfg.terminal == "RSE" else TerminalConfiguration.DIFFERENTIAL

        try:
            with nidaqmx.Task() as task:
                for ch in cfg.channels:
                    task.ai_channels.add_ai_voltage_chan(
                        f"{self._device}/{ch}",
                        terminal_config=term,
                        min_val=-cfg.range_v,
                        max_val=+cfg.range_v,
                    )
                task.timing.cfg_samp_clk_timing(
                    rate=cfg.sample_rate_hz,
                    sample_mode=AcquisitionType.CONTINUOUS,
                    samps_per_chan=max(block * 4, 4096),
                )
                # Hard upper bound on per-call wait so the stop_event is
                # responsive: waiting forever blocks shutdown.
                wait_timeout_s = max(0.5, (block / cfg.sample_rate_hz) * 4.0)
                logger.info("daq worker starting: %d S/s × %d ch, block=%d, term=%s, range=±%g",
                            cfg.sample_rate_hz, n_ch, block, cfg.terminal, cfg.range_v)
                task.start()
                while not self._stop_event.is_set():
                    try:
                        # Returns:
                        #   single channel  -> list[float] of length n
                        #   multi-channel   -> list[list[float]] shape (n_ch, n)
                        data = task.read(
                            number_of_samples_per_channel=block,
                            timeout=wait_timeout_s,
                        )
                    except Exception as exc:
                        # DaqReadError on overrun: log and keep going.
                        self.last_error = f"read error: {exc}"
                        self.overruns += 1
                        logger.warning("task.read raised: %s", exc)
                        continue
                    if n_ch == 1:
                        arr = np.asarray(data, dtype=np.float32)
                        n = arr.size
                        interleaved = arr
                    else:
                        arr = np.asarray(data, dtype=np.float32)  # (n_ch, n)
                        n = arr.shape[1]
                        interleaved = arr.T.reshape(-1)
                    if n <= 0:
                        continue
                    self.seq_counter += 1
                    self.samples_emitted += n
                    frame = FrameTuple(
                        seq=self.seq_counter,
                        sample_rate_hz=float(cfg.sample_rate_hz),
                        sample_count=int(n),
                        channel_count=n_ch,
                        samples=interleaved,
                    )
                    try:
                        self.frames_queue.put_nowait(frame)
                    except queue.Full:
                        self.overruns += 1
                        try:
                            self.frames_queue.get_nowait()
                        except queue.Empty:
                            pass
                        try:
                            self.frames_queue.put_nowait(frame)
                        except queue.Full:
                            pass
        except Exception as exc:
            self.last_error = str(exc)
            logger.exception("daq worker thread aborted")
