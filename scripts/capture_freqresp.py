"""Capture USB-6002 AI0 with Keithley 6514 configured as front-end.

Runs on the lab Windows VM (or any Windows host with NI-DAQmx installed).
Configures the 6514 over RS-232 (default
/dev/ttyUSB0, 9600 8N1, XonXoff, CR terminator), then starts a continuous
50 kS/s capture on the USB-6002 differential AI0. Saves an .npy dict.

Usage:
    python scripts/capture_freqresp.py --duration 12 --out data/exp01/02_speaker_chirp.npy
    # then on Mac: afplay chirp_50_20k_10s.wav  # within ~2 s

Dependencies: pyserial, nidaqmx, numpy
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import serial


# ---- 6514 helpers ---------------------------------------------------------

def open_6514(port: str = "/dev/ttyUSB0") -> serial.Serial:
    s = serial.Serial(port, 9600, bytesize=8, parity="N", stopbits=1,
                      timeout=2, xonxoff=True)
    s.reset_input_buffer()
    return s


def cmd(s: serial.Serial, line: str, sleep: float = 0.05) -> None:
    s.write((line + "\r").encode())
    s.flush()
    time.sleep(sleep)


def query(s: serial.Serial, line: str) -> str:
    s.reset_input_buffer()
    cmd(s, line, sleep=0.2)
    return s.read(200).decode(errors="replace").strip()


def configure_6514_for_capture(s: serial.Serial, range_v: float) -> dict[str, Any]:
    """Lock 6514 into a stable, fast V-mode config suitable for streaming the
    2V ANALOG OUTPUT to a downstream digitizer."""
    cmd(s, "*RST"); cmd(s, "*CLS")
    cmd(s, "SYST:ZCH ON")            # zero-check ON during configuration
    cmd(s, 'FUNC "VOLT"')
    cmd(s, f"VOLT:RANG {range_v}")
    cmd(s, "VOLT:RANG:AUTO OFF")
    cmd(s, "SYST:AZER OFF")
    cmd(s, "AVER:STAT OFF")
    cmd(s, "MEDN:STAT OFF")
    cmd(s, "DISP:ENAB OFF")
    cmd(s, "SYST:ZCOR ON", sleep=0.5)  # zero-correct (takes a moment)
    cmd(s, "SYST:ZCH OFF")            # release zero-check, signal flows
    return {
        "idn": query(s, "*IDN?"),
        "func": query(s, "FUNC?"),
        "range": query(s, "VOLT:RANG?"),
        "zch": query(s, "SYST:ZCH?"),
        "zcor": query(s, "SYST:ZCOR?"),
        "azer": query(s, "SYST:AZER?"),
    }


# ---- USB-6002 capture -----------------------------------------------------

def capture(duration: float, fs: int, channel: str, terminal: str) -> np.ndarray:
    import nidaqmx
    from nidaqmx.constants import AcquisitionType, TerminalConfiguration

    term = {
        "DIFF": TerminalConfiguration.DIFF,
        "RSE": TerminalConfiguration.RSE,
        "NRSE": TerminalConfiguration.NRSE,
    }[terminal]

    n_total = int(duration * fs)
    chunk = max(1024, fs // 5)  # 200 ms chunks

    with nidaqmx.Task() as task:
        task.ai_channels.add_ai_voltage_chan(
            channel,
            terminal_config=term,
            min_val=-10.0, max_val=10.0,
        )
        task.timing.cfg_samp_clk_timing(
            fs, sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=chunk * 2,
        )
        task.in_stream.input_buf_size = max(fs * 2, chunk * 4)
        task.start()
        chunks: list[np.ndarray] = []
        remaining = n_total
        t0 = time.time()
        print(f"Capturing {duration:.1f} s @ {fs} S/s on {channel} ({terminal})")
        while remaining > 0:
            n = min(chunk, remaining)
            data = task.read(n, timeout=5.0)
            chunks.append(np.asarray(data, dtype=np.float32))
            remaining -= n
        dt = time.time() - t0
    out = np.concatenate(chunks)
    print(f"Done: {len(out)} samples in {dt:.2f} s "
          f"(mean={out.mean()*1000:.2f} mV, std={out.std()*1000:.2f} mV)")
    return out


# ---- Main -----------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB0", help="6514 serial port")
    ap.add_argument("--range", dest="range_v", type=float, default=2.0,
                    help="6514 V range, e.g. 2 / 20 / 200")
    ap.add_argument("--channel", default="Dev1/ai0", help="DAQmx physical channel")
    ap.add_argument("--terminal", default="DIFF", choices=["DIFF", "RSE", "NRSE"])
    ap.add_argument("--fs", type=int, default=50_000, help="sample rate")
    ap.add_argument("--duration", type=float, default=12.0)
    ap.add_argument("--out", type=Path, default=Path("capture.npy"))
    ap.add_argument("--skip-6514", action="store_true",
                    help="don't touch the 6514 (assume preconfigured)")
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)

    meta: dict[str, Any] = {"fs": args.fs, "range": args.range_v,
                            "channel": args.channel, "terminal": args.terminal}

    if not args.skip_6514:
        s = open_6514(args.port)
        cfg = configure_6514_for_capture(s, args.range_v)
        meta["6514"] = cfg
        print("6514 configured:", json.dumps(cfg, ensure_ascii=False, indent=2))
        s.close()
        # Give it a beat to settle before sampling
        time.sleep(2.0)

    print("\n>>> Start the stimulus NOW (e.g. play chirp_50_20k_10s.wav) <<<\n")
    data = capture(args.duration, args.fs, args.channel, args.terminal)

    np.save(args.out, {"fs": args.fs, "range": args.range_v,
                       "data": data, "meta": meta}, allow_pickle=True)
    print(f"Saved {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
