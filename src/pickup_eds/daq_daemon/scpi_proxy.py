"""6514 SCPI proxy.

Single pyserial instance + asyncio queue: every command is serialized so
two HTTP callers can never collide on the COM port.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ScpiResult:
    response: str
    elapsed_ms: float
    ok: bool


class ScpiProxy:
    def __init__(self, com: str, baudrate: int = 9600, timeout_s: float = 2.0,
                 read_settle_s: float = 0.4) -> None:
        self._com = com
        self._baud = baudrate
        self._timeout = timeout_s
        self._settle = read_settle_s
        self._serial: Optional[object] = None  # pyserial Serial, lazy import
        self._lock = asyncio.Lock()
        self._idn: str = ""

    @property
    def com(self) -> str:
        return self._com

    @property
    def idn(self) -> str:
        return self._idn

    async def open(self) -> None:
        import serial  # type: ignore[import-not-found]
        loop = asyncio.get_running_loop()
        # Open in a worker thread; pyserial constructor blocks.
        self._serial = await loop.run_in_executor(
            None, lambda: serial.Serial(self._com, self._baud, timeout=self._timeout)
        )
        # Probe IDN once to populate metadata.
        result = await self.send("*IDN?")
        self._idn = result.response

    async def close(self) -> None:
        if self._serial is not None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._serial.close)
            self._serial = None

    async def send(self, command: str) -> ScpiResult:
        async with self._lock:
            return await self._send_locked(command)

    async def _send_locked(self, command: str) -> ScpiResult:
        if self._serial is None:
            return ScpiResult(response="ERR: serial not open", elapsed_ms=0.0, ok=False)
        loop = asyncio.get_running_loop()
        cmd = command.strip()

        def _io() -> str:
            assert self._serial is not None
            self._serial.reset_input_buffer()
            self._serial.write((cmd + "\r\n").encode("ascii", errors="replace"))
            time.sleep(self._settle)
            n = self._serial.in_waiting
            data = self._serial.read(n) if n else b""
            return data.decode(errors="replace").strip()

        t0 = time.perf_counter()
        try:
            resp = await loop.run_in_executor(None, _io)
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.exception("scpi send failed")
            return ScpiResult(response=f"ERR: serial: {exc}", elapsed_ms=elapsed, ok=False)
        elapsed = (time.perf_counter() - t0) * 1000

        is_query = "?" in cmd
        if resp.upper().startswith("ERR"):
            ok = False
        elif is_query:
            ok = bool(resp)
        else:
            ok = True
        return ScpiResult(response=resp, elapsed_ms=elapsed, ok=ok)
