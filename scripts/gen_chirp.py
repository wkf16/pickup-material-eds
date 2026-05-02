"""Generate logarithmic sweep wav for bandwidth testing.

Run on the Mac (or any machine with audio output). Output wav can be played
through laptop speaker / phone / amplified speaker, while the lab box captures
the TENG response synchronously via USB-6002.

Usage:
    python scripts/gen_chirp.py
    afplay chirp_50_20k_10s.wav   # Mac
    # or open in Audacity / VLC
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import chirp


def make_chirp(
    f0: float = 50.0,
    f1: float = 20000.0,
    duration: float = 10.0,
    fs: int = 48000,
    fade_ms: float = 50.0,
    amplitude: float = 0.6,
) -> np.ndarray:
    t = np.linspace(0, duration, int(fs * duration), endpoint=False)
    y = chirp(t, f0=f0, f1=f1, t1=duration, method="logarithmic")
    fade = int(fade_ms * 1e-3 * fs)
    if fade > 0:
        y[:fade] *= np.linspace(0, 1, fade)
        y[-fade:] *= np.linspace(1, 0, fade)
    return (y * amplitude).astype(np.float32)


def main() -> int:
    out = Path("chirp_50_20k_10s.wav")
    y = make_chirp()
    # 16-bit PCM for max compatibility
    sf.write(out, y, 48000, subtype="PCM_16")
    print(f"Wrote {out} ({len(y)} samples @ 48000 Hz, 50→20000 Hz log sweep)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
