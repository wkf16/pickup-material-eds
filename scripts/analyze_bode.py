"""Analyze a USB-6002 capture: time domain, FFT, 1/3-octave energy.

If a reference mic recording (wav) is supplied via --ref, also compute the
TENG/REF transfer function (Bode-style).

Usage:
    python scripts/analyze_bode.py data/exp01/02_speaker_chirp.npy
    python scripts/analyze_bode.py capture.npy --ref reference_phone.wav --plot
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import welch


def load_capture(p: Path) -> tuple[np.ndarray, float, float]:
    obj = np.load(p, allow_pickle=True).item()
    fs = float(obj["fs"])
    rng = float(obj["range"])
    data = np.asarray(obj["data"], dtype=np.float64)
    # Restore actual input voltage from 2V analog output scaling
    data_real = data * (rng / 2.0)
    return data_real, fs, rng


def third_octave_energy(f: np.ndarray, p: np.ndarray, f_low: float = 20.0,
                        f_high: float = 20000.0) -> tuple[np.ndarray, np.ndarray]:
    """Sum PSD into 1/3-octave bins. Useful for stability against FFT bin noise."""
    centers = []
    powers = []
    fc = f_low
    while fc <= f_high:
        f_lo = fc / 2 ** (1 / 6)
        f_hi = fc * 2 ** (1 / 6)
        mask = (f >= f_lo) & (f < f_hi)
        if mask.any():
            centers.append(fc)
            powers.append(p[mask].sum())
        fc *= 2 ** (1 / 3)
    return np.asarray(centers), np.asarray(powers)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("npy", type=Path)
    ap.add_argument("--ref", type=Path, default=None,
                    help="reference recording wav (e.g. phone mic of same chirp)")
    ap.add_argument("--plot", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("bode.png"))
    ap.add_argument("--nperseg", type=int, default=8192)
    args = ap.parse_args()

    teng, fs_t, rng = load_capture(args.npy)
    print(f"TENG: {len(teng)} samples @ {fs_t} Hz, 6514 range {rng} V")
    print(f"  mean={teng.mean()*1000:.3f} mV  std={teng.std()*1000:.3f} mV  "
          f"p2p={teng.ptp()*1000:.3f} mV")

    f_t, P_t = welch(teng, fs_t, nperseg=args.nperseg, noverlap=args.nperseg // 2)

    fig, axs = plt.subplots(3, 1, figsize=(11, 10))
    t = np.arange(len(teng)) / fs_t
    axs[0].plot(t, teng * 1000, lw=0.4)
    axs[0].set(xlabel="t (s)", ylabel="mV", title=f"Time domain — {args.npy.name}")
    axs[0].grid(True, alpha=0.3)

    axs[1].semilogx(f_t, 10 * np.log10(P_t + 1e-30))
    axs[1].set(xlabel="Hz", ylabel="dB (V²/Hz)",
               title="PSD (TENG, after 6514 range scaling back to real volts)",
               xlim=(10, fs_t / 2))
    axs[1].grid(True, which="both", alpha=0.3)
    # mark 50 Hz harmonics for reference
    for h in [50, 100, 150, 200, 250]:
        axs[1].axvline(h, color="r", lw=0.5, alpha=0.4)

    fc, pc = third_octave_energy(f_t, P_t, 20, fs_t / 2)
    axs[2].semilogx(fc, 10 * np.log10(pc + 1e-30), "o-")
    axs[2].set(xlabel="Hz (1/3-octave centers)", ylabel="dB",
               title="Energy in 1/3-octave bands",
               xlim=(10, fs_t / 2))
    axs[2].grid(True, which="both", alpha=0.3)

    if args.ref is not None:
        import soundfile as sf
        ref, fs_r = sf.read(args.ref)
        if ref.ndim > 1:
            ref = ref[:, 0]
        f_r, P_r = welch(ref, fs_r, nperseg=args.nperseg, noverlap=args.nperseg // 2)
        # Resample TENG PSD to ref grid
        common = np.logspace(np.log10(50), np.log10(min(fs_r, fs_t) / 2 * 0.95), 256)
        teng_db = np.interp(common, f_t, 10 * np.log10(P_t + 1e-30))
        ref_db = np.interp(common, f_r, 10 * np.log10(P_r + 1e-30))
        bode = teng_db - ref_db
        bode -= bode[(common > 100) & (common < 200)].mean()  # normalize at 100-200 Hz
        # overlay on PSD plot
        axs[1].plot(common, ref_db, color="orange", lw=0.7, alpha=0.6,
                    label=f"REF ({args.ref.name})")
        axs[1].legend(loc="upper right")
        # add a 4th panel for Bode
        fig.set_size_inches(11, 13)
        ax4 = fig.add_subplot(4, 1, 4)
        ax4.semilogx(common, bode)
        ax4.set(xlabel="Hz", ylabel="dB",
                title="Bode: TENG / REF (normalized at 100-200 Hz)",
                xlim=(50, common[-1]))
        ax4.axhline(-3, color="r", lw=0.5, alpha=0.5)
        ax4.axhline(-10, color="r", lw=0.5, alpha=0.5)
        ax4.grid(True, which="both", alpha=0.3)

    plt.tight_layout()
    plt.savefig(args.out, dpi=120)
    print(f"Saved {args.out}")
    if args.plot:
        plt.show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
