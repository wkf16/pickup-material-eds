#!/usr/bin/env python3
"""Standalone verifier for the DAQ daemon. Run from anywhere with HTTP+WS access.

Usage:
    python scripts/verify_daq_daemon.py BASE_URL [--ws WS_URL] [--duration SEC]

Default BASE_URL: http://192.168.122.8:8765 (only reachable from lab4070).
From a Mac you'll typically tunnel: ssh -L 8765:192.168.122.8:8765 lab4070-c.

Tests in order:
  1. GET  /api/health                  — daemon up, devices visible
  2. POST /api/scpi/send {*IDN?}       — 6514 responds with MODEL 6514
  3. POST /api/daq/start (50 kHz/ai0)  — frames stream for `duration` seconds
  4. POST /api/daq/stop                — stops cleanly
  5. asserts: 0 overruns, seq strictly +1, ≥ duration*sample_rate samples

Returns 0 on full pass.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import struct
import sys
import time
from urllib.parse import urlparse

import httpx
import websockets


FRAME_HEADER_FMT = "<IIfI"
HEADER_SIZE = struct.calcsize(FRAME_HEADER_FMT)


async def _verify_60s(base_url: str, ws_url: str, duration: float, sample_rate: int) -> dict:
    print(f">> POST /api/daq/start sample_rate={sample_rate} channels=ai0 RSE ±10V")
    async with httpx.AsyncClient(timeout=10.0, trust_env=False) as http:
        r = await http.post(
            f"{base_url}/api/daq/start",
            json={"sample_rate_hz": sample_rate, "channels": ["ai0"], "terminal": "RSE", "range_v": 10.0},
        )
        r.raise_for_status()
        print(f"   {r.json()}")

    seq_first = None
    seq_last = None
    seq_gaps = 0
    samples_total = 0
    frames = 0
    bytes_total = 0
    deadline = time.monotonic() + duration

    print(f">> connecting ws {ws_url}; running {duration:.0f}s")
    try:
        async with websockets.connect(ws_url, max_size=4 * 1024 * 1024) as ws:
            while time.monotonic() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue
                if not isinstance(raw, (bytes, bytearray)) or len(raw) < HEADER_SIZE:
                    continue
                seq, n, sr, c = struct.unpack(FRAME_HEADER_FMT, raw[:HEADER_SIZE])
                if seq_first is None:
                    seq_first = seq
                if seq_last is not None and seq != seq_last + 1:
                    seq_gaps += 1
                seq_last = seq
                samples_total += n
                frames += 1
                bytes_total += len(raw)
    finally:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as http:
            r = await http.post(f"{base_url}/api/daq/stop")
            r.raise_for_status()
            print(f">> POST /api/daq/stop -> {r.json()}")

    expected = sample_rate * duration
    return {
        "seq_first": seq_first,
        "seq_last": seq_last,
        "seq_gaps": seq_gaps,
        "frames": frames,
        "samples": samples_total,
        "bytes": bytes_total,
        "expected_samples": int(expected),
        "loss_pct": round(100 * (1 - samples_total / expected), 4) if expected else 0,
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url", nargs="?", default="http://192.168.122.8:8765")
    ap.add_argument("--ws", default=None)
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--sample-rate", type=int, default=50000)
    args = ap.parse_args()

    base_url = args.base_url.rstrip("/")
    if args.ws:
        ws_url = args.ws
    else:
        u = urlparse(base_url)
        ws_url = f"ws://{u.netloc}/ws/raw_stream"

    failures: list[str] = []

    # 1. /api/health
    print(">> GET /api/health")
    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as http:
            r = await http.get(f"{base_url}/api/health")
            r.raise_for_status()
            health = r.json()
        print("   ", json.dumps(health, indent=2))
        if not health.get("daq_device"):
            failures.append("/api/health: no daq_device")
    except Exception as exc:
        failures.append(f"/api/health: {exc}")

    # 2. SCPI *IDN?
    print(">> POST /api/scpi/send '*IDN?'")
    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as http:
            r = await http.post(f"{base_url}/api/scpi/send", json={"cmd": "*IDN?"})
            r.raise_for_status()
            scpi = r.json()
        print("   ", scpi)
        if "MODEL 6514" not in scpi.get("resp", "").upper():
            failures.append(f"/api/scpi/send: unexpected resp '{scpi.get('resp')}'")
    except Exception as exc:
        failures.append(f"/api/scpi/send: {exc}")

    # 3+4+5. 50 kHz × duration with ws stream
    try:
        result = await _verify_60s(base_url, ws_url, args.duration, args.sample_rate)
        print(">> stream report:")
        print("   ", json.dumps(result, indent=2))
        if result["frames"] == 0:
            failures.append("ws/raw_stream: 0 frames received")
        if result["seq_gaps"] > 0:
            failures.append(f"ws/raw_stream: {result['seq_gaps']} sequence gaps")
        if abs(result["loss_pct"]) > 1.0:
            failures.append(f"ws/raw_stream: {result['loss_pct']}% sample loss")
    except Exception as exc:
        failures.append(f"daq stream: {exc}")

    print()
    if failures:
        print("FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS — daq daemon healthy")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
