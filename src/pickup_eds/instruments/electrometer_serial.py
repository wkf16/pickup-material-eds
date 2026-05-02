"""Real Keithley 6514 SCPI bridge over RS-232 (USB-serial).

Scope (intentionally narrow)
----------------------------
This module is a *temporary* bridge that lets ONLY the WebUI's
"COM / SCPI 控制台" card talk to the physical instrument. Everything
else (live waveform, recording, derived state) still comes from
``SimulatedBenchService``.

The full real-hardware ``BenchService`` (DAQ + electrometer + state
sync) is planned but not implemented yet — see
``docs/dev-real-hardware.md`` for the migration path. Until then this
file is the smallest possible step that proves the link is alive
without touching the rest of the API surface.

Link parameters (from docs/webui-mvp-delivery.md §2)
----------------------------------------------------
- 9600 / 8N1
- XonXoff flow control
- ``\r`` line terminator on both directions
- Default device on the lab Manjaro box: ``/dev/ttyUSB0``
  (Prolific 067b:23a3 ATEN bridge bound to ``pl2303``)

Threading model
---------------
``pyserial`` is blocking. The FastAPI request loop is async. We bounce
each ``send()`` through ``asyncio.to_thread`` and serialize concurrent
callers with an ``asyncio.Lock`` — the 6514 is a single-talker device,
overlapping reads/writes will corrupt responses.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

try:
    import serial  # pyserial; optional dep, only present in lab venv
except ImportError:  # pragma: no cover - dev machines without pyserial
    serial = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class Real6514Serial:
    """Minimal blocking pyserial wrapper, async-friendly façade."""

    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        baudrate: int = 9600,
        timeout_s: float = 2.0,
        read_settle_s: float = 0.4,
    ) -> None:
        # Connection params; matches Keithley 6514 default RS-232 config.
        self._port = port
        self._baud = baudrate
        self._timeout = timeout_s
        # 6514 is slow on multi-byte responses (e.g. *IDN?). Wait this
        # long after writing before reading the input buffer, otherwise
        # we'll catch only the first chunk.
        self._read_settle_s = read_settle_s
        self._ser: Optional["serial.Serial"] = None
        # All I/O serialized; the instrument cannot interleave commands.
        self._lock = asyncio.Lock()

    @property
    def port(self) -> str:
        return self._port

    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    async def open(self) -> None:
        """Open the serial port. Raises on failure (caller decides fallback)."""
        if serial is None:
            raise RuntimeError("pyserial not installed in this venv")

        def _open() -> "serial.Serial":
            return serial.Serial(
                self._port,
                baudrate=self._baud,
                bytesize=8,
                parity="N",
                stopbits=1,
                xonxoff=True,  # docs §2 — Keithley default
                timeout=self._timeout,
            )

        self._ser = await asyncio.to_thread(_open)
        logger.info("opened real 6514 SCPI link on %s", self._port)

    async def close(self) -> None:
        if self._ser is not None and self._ser.is_open:
            await asyncio.to_thread(self._ser.close)
        self._ser = None

    async def send(self, command: str) -> str:
        """Write ``command\\r`` and return the decoded response (no trailing \\r)."""
        if not self.is_open():
            raise RuntimeError("serial link not open")
        ser = self._ser
        assert ser is not None  # for type checker; guarded by is_open above

        async with self._lock:
            def _io() -> str:
                ser.reset_input_buffer()
                # 6514 uses CR as terminator on both directions.
                ser.write(command.encode("ascii", errors="replace") + b"\r")
                ser.flush()
                return ""

            await asyncio.to_thread(_io)
            # Give the instrument time to compose its reply before reading.
            await asyncio.sleep(self._read_settle_s)

            def _read() -> bytes:
                # Drain whatever's in the input buffer; if nothing, fall
                # back to a blocking read up to the configured timeout.
                pending = ser.in_waiting
                if pending:
                    return ser.read(pending)
                return ser.read(256)

            raw = await asyncio.to_thread(_read)

        # 6514 terminates with CR; strip trailing whitespace for display.
        return raw.decode("ascii", errors="replace").rstrip("\r\n ")
