"""Lightweight startup recovery for the daq daemon.

The PickupEdsFirstBoot scheduled task already kicks NI services + USB
on system boot. This module is a second-line check the daemon runs on
its own startup: probe nidaqmx for any device, and if none is visible,
ask Windows PnP to rescan once and try again.
"""
from __future__ import annotations

import logging
import subprocess
import time

logger = logging.getLogger(__name__)


def kick_pnpunum(timeout_s: float = 30.0) -> None:
    """Trigger ``pnputil /scan-devices`` on Windows; ignore failures."""
    try:
        subprocess.run(
            ["pnputil.exe", "/scan-devices"],
            capture_output=True,
            timeout=timeout_s,
        )
    except Exception as exc:
        logger.warning("pnputil /scan-devices failed: %s", exc)


def wait_for_nidaq(retries: int = 3, sleep_s: float = 4.0) -> bool:
    """Return True once nidaqmx sees at least one device."""
    try:
        import nidaqmx  # type: ignore[import-not-found]
    except Exception as exc:
        logger.error("nidaqmx import failed: %s", exc)
        return False

    for attempt in range(retries):
        names = list(nidaqmx.system.System.local().devices.device_names)
        logger.info("nidaqmx attempt %d/%d: %s", attempt + 1, retries, names)
        if names:
            return True
        if attempt + 1 < retries:
            kick_pnpunum()
            time.sleep(sleep_s)
    return False
