#!/usr/bin/env python3
"""End-to-end Phase 2 acceptance verifier.

Hits the Linux WebUI (assumed running with PICKUP_EDS_BRIDGE_URL set) and
exercises the bridge → daq daemon path. Reports pass/fail per the
acceptance criteria in docs/phase2-design.md §2.5.

Usage:
    python scripts/verify_phase2.py [WEBUI_URL]

Default WEBUI_URL: http://lab4070-c

Output: a JSON report to data/phase2_acceptance/<timestamp>.json plus
human-readable summary on stdout.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
import websockets


REPO_ROOT = Path(__file__).resolve().parents[1]
ACCEPT_DIR = REPO_ROOT / "data" / "phase2_acceptance"


async def check(name: str, coro) -> dict:
    t0 = time.monotonic()
    try:
        result = await coro
        return {"name": name, "ok": True, "elapsed_s": round(time.monotonic() - t0, 2), **(result or {})}
    except Exception as exc:
        return {"name": name, "ok": False, "elapsed_s": round(time.monotonic() - t0, 2), "error": str(exc)}


async def c1_health(http: httpx.AsyncClient, webui: str) -> dict:
    r = await http.get(f"{webui}/api/health")
    r.raise_for_status()
    h = r.json()
    if h.get("mode") != "bridge":
        raise RuntimeError(f"webui mode != bridge: {h}")
    if h.get("bridge_state") not in {"running", "connected_idle"}:
        raise RuntimeError(f"bridge_state not healthy: {h.get('bridge_state')}")
    return {"health": h}


async def c2_scpi_idn(http: httpx.AsyncClient, webui: str) -> dict:
    r = await http.post(f"{webui}/api/control/scpi/send", json={"command": "*IDN?"})
    r.raise_for_status()
    body = r.json()
    resp = body.get("entry", {}).get("response", "")
    if "MODEL 6514" not in resp.upper():
        raise RuntimeError(f"unexpected SCPI resp: {resp!r}")
    return {"idn": resp}


async def c3_daq_run_pause_stop(http: httpx.AsyncClient, webui: str) -> dict:
    seq = []
    for path, body in [
        ("daq/run", {"sample_rate_hz": 5000, "channels": ["ai0"], "terminal": "RSE", "range_v": 10.0}),
        ("daq/pause", {}),
        ("daq/stop", {}),
    ]:
        r = await http.post(f"{webui}/api/control/{path}", json=body)
        r.raise_for_status()
        s = r.json()["state"]["daq"]["state"]
        seq.append((path, s))
    expected = [("daq/run", "running"), ("daq/pause", "paused"), ("daq/stop", "idle")]
    if seq != expected:
        raise RuntimeError(f"state machine mismatch: {seq}")
    return {"seq": seq}


async def c4_recording(http: httpx.AsyncClient, webui: str, ws_browser: str) -> dict:
    # Start DAQ first so frames flow into the ring buffer
    await http.post(f"{webui}/api/control/daq/run", json={
        "sample_rate_hz": 5000, "channels": ["ai0"], "terminal": "RSE", "range_v": 10.0,
    })
    # Record 5 s
    r = await http.post(f"{webui}/api/recording/start", json={"label": "phase2_smoke", "duration_s": 5})
    r.raise_for_status()
    await asyncio.sleep(7)
    # Stop daq
    await http.post(f"{webui}/api/control/daq/stop")

    r = await http.get(f"{webui}/api/data/list")
    r.raise_for_status()
    items = r.json()["items"]
    latest = next((it for it in items if it["label"] == "phase2_smoke"), None)
    if latest is None:
        raise RuntimeError(f"recording not found in /api/data/list (items={[i['label'] for i in items]})")
    if latest["sample_count"] < 1000:
        raise RuntimeError(f"sample_count too low: {latest['sample_count']}")
    return {"dataset_id": latest["id"], "sample_count": latest["sample_count"]}


async def c5_50khz_60s(http: httpx.AsyncClient, webui: str, duration: float = 60.0) -> dict:
    sr = 50000
    await http.post(f"{webui}/api/control/daq/run", json={
        "sample_rate_hz": sr, "channels": ["ai0"], "terminal": "RSE", "range_v": 10.0,
    })
    # Subscribe to /ws/stream (browser-facing, decimated frames)
    u = urlparse(webui)
    ws_url = f"ws://{u.netloc}/ws/stream"
    seq_count = 0
    seq_last = None
    seq_gaps = 0
    deadline = time.monotonic() + duration
    try:
        async with websockets.connect(ws_url, max_size=4 * 1024 * 1024) as ws:
            while time.monotonic() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
                except asyncio.TimeoutError:
                    continue
                payload = json.loads(msg)
                seq = int(payload.get("seq", 0))
                if seq_last is not None and seq != seq_last + 1:
                    seq_gaps += 1
                seq_last = seq
                seq_count += 1
    finally:
        await http.post(f"{webui}/api/control/daq/stop")

    if seq_count < int(duration * 5):
        # browser stream is ~10 fps; expect ≥5 fps of useful frames
        raise RuntimeError(f"too few /ws/stream frames in {duration}s: {seq_count}")
    return {"seq_count": seq_count, "seq_gaps": seq_gaps, "duration_s": duration}


async def c6_bridge_status(http: httpx.AsyncClient, webui: str) -> dict:
    r = await http.get(f"{webui}/api/state")
    r.raise_for_status()
    bridge = r.json().get("bridge")
    if not bridge or bridge.get("state") not in {"running", "connected_idle"}:
        raise RuntimeError(f"bridge not running in /api/state: {bridge}")
    return {"bridge": bridge}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("webui", nargs="?", default="http://lab4070-c")
    ap.add_argument("--no-50khz", action="store_true", help="skip the 60-s 50 kHz test")
    ap.add_argument("--duration", type=float, default=60.0)
    args = ap.parse_args()
    webui = args.webui.rstrip("/")

    started_at = datetime.now(UTC)
    print(f">> verifying {webui}")
    results = []
    async with httpx.AsyncClient(timeout=30.0, trust_env=False) as http:
        results.append(await check("health+bridge_running",  c1_health(http, webui)))
        results.append(await check("scpi *IDN?",              c2_scpi_idn(http, webui)))
        results.append(await check("daq run/pause/stop",     c3_daq_run_pause_stop(http, webui)))
        results.append(await check("recording 5s baseline",  c4_recording(http, webui, "")))
        results.append(await check("bridge in /api/state",   c6_bridge_status(http, webui)))
        if not args.no_50khz:
            results.append(await check(f"50 kHz × {args.duration}s", c5_50khz_60s(http, webui, args.duration)))

    n_pass = sum(1 for r in results if r["ok"])
    n_fail = len(results) - n_pass
    print()
    for r in results:
        mark = "PASS" if r["ok"] else "FAIL"
        print(f"  [{mark}] {r['name']:<32} {r['elapsed_s']}s  {r.get('error', '')}")
    print()
    print(f"=> {n_pass}/{len(results)} passed")

    ACCEPT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "started_at": started_at.isoformat(),
        "webui": webui,
        "results": results,
        "passed": n_pass,
        "total": len(results),
    }
    fname = ACCEPT_DIR / f"{started_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    fname.write_text(json.dumps(report, indent=2))
    print(f">> report -> {fname}")

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
