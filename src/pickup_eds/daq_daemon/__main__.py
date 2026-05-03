"""``python -m pickup_eds.daq_daemon`` entry point."""
from __future__ import annotations

import argparse
import logging
import os

import uvicorn


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("DAQ_DAEMON_HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("DAQ_DAEMON_PORT", "8765")))
    ap.add_argument("--log-level", default=os.environ.get("DAQ_DAEMON_LOG", "info"))
    args = ap.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    uvicorn.run(
        "pickup_eds.daq_daemon.app:app",
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
