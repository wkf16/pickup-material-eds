"""USB-6002 + 6514 auto-discovery (Windows-only).

Both helpers are best-effort: they raise ``RuntimeError`` if no candidate
device responds. Callers are expected to catch and surface the failure
through the bridge state machine instead of crashing the daemon.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


def find_usb6002() -> str:
    """Return the nidaqmx device name (e.g. 'Dev1') of the first USB-6002.

    Lazy-imports nidaqmx so the daemon module remains importable on
    machines without the NI driver (handy for unit tests).
    """
    import nidaqmx  # type: ignore[import-not-found]

    sys_ = nidaqmx.system.System.local()
    for dev in sys_.devices:
        try:
            ptype = dev.product_type
        except Exception:  # device went phantom mid-iteration
            continue
        if ptype and "USB-6002" in ptype:
            return dev.name
    # Fall back to "any device" if product_type isn't introspectable
    names = list(sys_.devices.device_names)
    if names:
        logger.warning("USB-6002 product_type not matched; falling back to %s", names[0])
        return names[0]
    raise RuntimeError("no NI DAQ device found via nidaqmx")


def find_keithley_com(*, idn_timeout_s: float = 2.0) -> str:
    """Return the COM port name (e.g. 'COM3') the Keithley 6514 answers on.

    Strategy:
      1. Filter ports for VID=0x067B / PID=0x23A3 (Prolific bridge used by 6514).
      2. If none match, fall back to every COM port.
      3. Send ``*IDN?\\r\\n`` to each candidate; first one that returns
         a string containing ``MODEL 6514`` wins.
    """
    import serial  # type: ignore[import-not-found]
    import serial.tools.list_ports as list_ports  # type: ignore[import-not-found]

    ports = list(list_ports.comports())
    candidates = [
        p.device for p in ports
        if (p.vid or 0) == 0x067B and (p.pid or 0) == 0x23A3
    ]
    if not candidates:
        logger.info("no Prolific 0x067B:0x23A3 found; trying every COM port")
        candidates = [p.device for p in ports]

    last_err: Optional[Exception] = None
    for com in candidates:
        try:
            with serial.Serial(com, 9600, timeout=idn_timeout_s) as s:
                s.write(b"*IDN?\r\n")
                time.sleep(0.4)
                resp = s.read(s.in_waiting or 256).decode(errors="replace")
                if "KEITHLEY" in resp.upper() and "MODEL 6514" in resp.upper():
                    logger.info("found 6514 on %s (%s)", com, resp.strip())
                    return com
        except Exception as exc:
            last_err = exc
            logger.debug("probe %s failed: %s", com, exc)

    if last_err:
        raise RuntimeError(f"no 6514 found on any COM port (last err: {last_err})")
    raise RuntimeError("no 6514 found on any COM port")
