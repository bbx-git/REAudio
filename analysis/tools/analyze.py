#!/usr/bin/env python3
"""Measurements on rendered WAVs. Prints a short summary, saves full JSON
(and PNG plots with --plot) to analysis/out/.

    .venv/bin/python analysis/tools/analyze.py info    FILE.wav
    .venv/bin/python analysis/tools/analyze.py ir      FILE.wav [--plot]
    .venv/bin/python analysis/tools/analyze.py peaks   FILE.wav [--end-ms 120] [--n 25]
    .venv/bin/python analysis/tools/analyze.py mod     FILE.wav [--freq 1000] [--plot]
    .venv/bin/python analysis/tools/analyze.py compare A.wav B.wav [--plot]
    .venv/bin/python analysis/tools/analyze.py spectrogram FILE.wav

t0 (the time the test signal starts) is read from the sidecar FILE.json written
by render.py ("signal.impulse_index", or preroll). Override with --t0 SECONDS.
All times are reported relative to t0, in ms AND in samples at the file's rate.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import OUT_DIR, check_interpreter, rel, write_json  # noqa: E402

check_interpreter()

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
from scipy import signal as sps  # noqa: E402

OCTAVES = [63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def load(path, t0_override=None):
    x, sr = sf.read(path, dtype="float64", always_2d=True)
    side_path = os.path.splitext(path)[0] + ".json"
    side = json.load(open(side_path)) if os.path.exists(side_path) else None
    if t0_override is not None:
        t0 = int(round(t0_override * sr))
    elif side and side.get("signal", {}).get("impulse_index") is not None:
        t0 = int(side["signal"]["impulse_index"])
    elif side:
        t0 = int(round(side.get("signal", {}).get("preroll_s", 0.0) * sr))
    else:
        t0 = 0
    return x.T, sr, t0, side


def out_base(path):
    return os.path.join(OUT_DIR, os.path.splitext(os.path.basename(path))[0])


def db(v, floor=-300.0):
    v = np.asarray(v, dtype=np.float64)
    with np.errstate(divide="ignore"):
        return np.maximum(10 * np.log10(np.maximum(v, 1e-300)), floor)


def chname(i, n):
    return ["L", "R"][i] if n == 2 else "ch%d" % i


def fmt(v, spec="%.3f"):
    return "-" if v is None else spec % v


# --------------------------------------------------------------------------
# Impulse-response metrics
# --------------------------------------------------------------------------
def band(x, sr, fc):
    lo, hi = fc / np.sqrt(2), fc * np.sqrt(2)
    if hi >= 0.45 * sr:
        return None
    sos = sps.butter(4, [lo, hi], btype="band", fs=sr, output="sos")
    return sps.sosfiltfilt(sos, x)


def edc_db(h, sr):
    """Schroeder backward integral in dB, truncated where the signal meets
    its noise floor (estimated from the last 5% of the file)."""
    e = h ** 2
    n = e.size
    tail = e[int(n * 0.95):]
    floor = tail.mean() if tail.size else 0.0
    end = n
    if floor > 0:
        blk = max(1, int(0.01 * sr))
        m = e[: n - n % blk].reshape(-1, blk).mean(axis=1)
        above = np.nonzero(m > floor * 10)[0]
        if above.size:
            end = min(n, (above[-1] + 1) * blk)
    e = e[:end]
    c = np.cumsum(e[::-1])[::-1]
    if c.size == 0 or c[0] <= 0:
        return None, floor
    return db(c / c[0]), floor


def decay_time(edc, sr, hi, lo):
    """Fit a line to the EDC between hi and lo dB; return the time for 60 dB."""
    if edc is None:
        return None
    idx = np.nonzero((edc <= hi) & (edc >= lo))[0]
    if idx.size < 10 or edc.min() > lo:
        return None
    t = idx / sr
    slope, _ = np.polyfit(t, edc[idx], 1)
    return None if slope >= 0 else -60.0 / slope


def echo_density(h, sr, win_s=0.02, hop_s=0.001):
    """Abel & Huang normalised echo density. 1.0 = Gaussian-like (fully mixed)."""
    w = np.hanning(int(win_s * sr) | 1)
    w /= w.sum()
    hop = max(1, int(hop_s * sr))
    k = 1.0 / 0.3173105078629141  # 1/erfc(1/sqrt(2))
    t, ned = [], []
    for s in range(0, h.size - w.size, hop):
        seg = h[s:s + w.size]
        sd = np.sqrt(np.sum(w * seg ** 2))
        ned.append(k * np.sum(w * (np.abs(seg) > sd)) if sd > 0 else 0.0)
        t.append((s + w.size // 2) / sr)
    return np.array(t), np.array(ned)


def ir_metrics(x, sr, t0, onset_db=-40.0):
    res = {"sample_rate": sr, "t0_sample": t0, "channels": {}}
    y = x[:, t0:]
    for ci in range(y.shape[0]):
        h = y[ci]
        name = chname(ci, y.shape[0])
        peak = np.max(np.abs(h)) if h.size else 0.0
        if peak == 0:
            res["channels"][name] = {"silent": True}
            continue
        ipk = int(np.argmax(np.abs(h)))
        thr = peak * 10 ** (onset_db / 20)
        first = int(np.argmax(np.abs(h) > thr))
        edc, floor = edc_db(h, sr)
        c = {
            "peak_dbfs": 20 * np.log10(peak),
            "peak_ms": ipk / sr * 1e3, "peak_samples": ipk,
            "first_arrival_ms": first / sr * 1e3, "first_arrival_samples": first,
            "first_arrival_threshold_db_re_peak": onset_db,
            "energy_db": float(db(np.sum(h ** 2))),
            "noise_floor_dbfs": float(db(floor)) if floor > 0 else None,
            "EDT_s": decay_time(edc, sr, 0, -10),
            "T20_s": decay_time(edc, sr, -5, -25),
            "T30_s": decay_time(edc, sr, -5, -35),
            "bands": {},
        }
        for fc in OCTAVES:
            hb = band(h, sr, fc)
            if hb is None:
                continue
            eb, _ = edc_db(hb, sr)
            c["bands"][str(fc)] = {
                "level_db": float(db(np.sum(hb ** 2))),
                "EDT_s": decay_time(eb, sr, 0, -10),
                "T20_s": decay_time(eb, sr, -5, -25),
                "T30_s": decay_time(eb, sr, -5, -35),
            }
        t, ned = echo_density(h[: int(min(h.size, 1.0 * sr))], sr)
        sm = np.convolve(ned, np.ones(5) / 5, mode="same") if ned.size > 5 else ned
        hit = lambda v: (float(t[np.argmax(sm >= v)] * 1e3) if np.any(sm >= v) else None)  # noqa: E731
        c["echo_density"] = {"ms_to_0.5": hit(0.5), "ms_to_0.9": hit(0.9), "ms_to_1.0": hit(1.0),
                             "curve_t_ms": (t * 1e3).round(2).tolist(), "curve": ned.round(3).tolist()}
        res["channels"][name] = c
    if y.shape[0] == 2 and np.any(y[0]) and np.any(y[1]):
        a, b = y[0][: int(2 * sr)], y[1][: int(2 * sr)]
        xc = sps.correlate(a, b, mode="full", method="fft")
        mid = b.size - 1
        lag = int(0.001 * sr)
        seg = xc[mid - lag: mid + lag + 1]
        norm = np.sqrt(np.sum(a ** 2) * np.sum(b ** 2))
        res["lr_correlation"] = {
            "at_lag0": float(xc[mid] / norm),
            "max_abs_within_1ms": float(np.max(np.abs(seg)) / norm),
            "note": "first 2 s after t0; 1.0 = identical channels, ~0 = decorrelated",
        }
    return res


def cmd_ir(a):
    x, sr, t0, side = load(a.file, a.t0)
    r = ir_metrics(x, sr, t0, a.onset_db)
    r["file"] = rel(a.file)
    if side:
        r["changed_from_default"] = side.get("changed_from_default")
    out = out_base(a.file) + ".ir.json"
    write_json(out, r)
    print("%s  sr=%d  t0=%d" % (rel(a.file), sr, t0))
    for ch, c in r["channels"].items():
        if c.get("silent"):
            print("  %s: SILENT" % ch)
            continue
        print("  %s: peak %.1f dBFS @ %.2f ms | first arrival %.2f ms (%d smp) | EDT %s T20 %s T30 %s s"
              % (ch, c["peak_dbfs"], c["peak_ms"], c["first_arrival_ms"], c["first_arrival_samples"],
                 fmt(c["EDT_s"], "%.2f"), fmt(c["T20_s"], "%.2f"), fmt(c["T30_s"], "%.2f")))
        print("      band  " + " ".join("%7s" % b for b in c["bands"]))
        print("      T30 s " + " ".join("%7s" % fmt(v["T30_s"], "%.2f") for v in c["bands"].values()))
        print("      lvl dB" + " ".join("%7.1f" % v["level_db"] for v in c["bands"].values()))
        e = c["echo_density"]
        print("      echo density reaches 0.5/0.9/1.0 at %s / %s / %s ms"
              % (fmt(e["ms_to_0.5"], "%.1f"), fmt(e["ms_to_0.9"], "%.1f"), fmt(e["ms_to_1.0"], "%.1f")))
    if "lr_correlation" in r:
        print("  L/R correlation: %.3f at lag 0, max |%.3f| within 1 ms"
              % (r["lr_correlation"]["at_lag0"], r["lr_correlation"]["max_abs_within_1ms"]))
    print("  saved %s" % rel(out))
    if a.plot:
        plot_ir(x, sr, t0, out_base(a.file) + ".ir.png")


def plot_ir(x, sr, t0, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    h = x[0, t0:]
    fig, ax = plt.subplots(3, 1, figsize=(11, 10))
    tt = np.arange(h.size) / sr
    ax[0].plot(tt[: int(0.2 * sr)] * 1e3, h[: int(0.2 * sr)], lw=0.6)
    ax[0].set(title="first 200 ms (ch0)", xlabel="ms")
    for fc in OCTAVES:
        hb = band(h, sr, fc)
        if hb is None:
            continue
        e, _ = edc_db(hb, sr)
        if e is not None:
            ax[1].plot(np.arange(e.size) / sr, e, lw=0.8, label="%d Hz" % fc)
    ax[1].set(title="energy decay curve per octave (ch0)", xlabel="s", ylabel="dB", ylim=(-80, 2))
    ax[1].legend(fontsize=7, ncol=5)
    f, t, S = sps.spectrogram(h, sr, nperseg=2048, noverlap=1536)
    ax[2].pcolormesh(t, f, 10 * np.log10(S + 1e-20), shading="auto", vmin=-160)
    ax[2].set(title="spectrogram (ch0)", xlabel="s", ylabel="Hz", yscale="symlog", ylim=(20, sr / 2))
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    print("  plot %s" % rel(path))


# --------------------------------------------------------------------------
# Discrete early arrivals (delay-line taps)
# --------------------------------------------------------------------------
def cmd_peaks(a):
    x, sr, t0, _ = load(a.file, a.t0)
    s0, s1 = t0 + int(a.start_ms * sr / 1e3), t0 + int(a.end_ms * sr / 1e3)
    out = {"file": rel(a.file), "sample_rate": sr, "t0_sample": t0, "window_ms": [a.start_ms, a.end_ms],
           "channels": {}}
    print("%s  sr=%d  window %.1f-%.1f ms after t0" % (rel(a.file), sr, a.start_ms, a.end_ms))
    for ci in range(x.shape[0]):
        h = x[ci, s0:s1]
        if not np.any(h):
            continue
        ref = np.max(np.abs(x[ci, t0:]))
        idx, _ = sps.find_peaks(np.abs(h), distance=max(1, int(a.min_gap_ms * sr / 1e3)))
        idx = idx[np.argsort(-np.abs(h[idx]))][: a.n]
        idx.sort()
        rows = [{"ms": (i + s0 - t0) / sr * 1e3, "samples": int(i + s0 - t0),
                 "db_re_peak": float(20 * np.log10(abs(h[i]) / ref)), "sign": int(np.sign(h[i]))} for i in idx]
        out["channels"][chname(ci, x.shape[0])] = rows
        print("  %s: %s" % (chname(ci, x.shape[0]), "  ".join(
            "%.2fms/%d(%+.0fdB%s)" % (r["ms"], r["samples"], r["db_re_peak"], "-" if r["sign"] < 0 else "")
            for r in rows)))
    p = out_base(a.file) + ".peaks.json"
    write_json(p, out)
    print("  format: time_ms/samples(level re overall peak, '-' = negative polarity)\n  saved %s" % rel(p))


# --------------------------------------------------------------------------
# Modulation (render a long sine first: render.py render --signal sine --dur 10)
# --------------------------------------------------------------------------
def cmd_mod(a):
    x, sr, t0, side = load(a.file, a.t0)
    f0 = a.freq or (side or {}).get("signal", {}).get("freq_hz")
    if not f0:
        sys.exit("ERROR: give --freq (no sine frequency in sidecar)")
    dur = (side or {}).get("signal", {}).get("dur_s") or (x.shape[1] - t0) / sr
    s0, s1 = t0 + int(0.5 * sr), t0 + int((dur - 0.05) * sr)
    if s1 - s0 < sr:
        sys.exit("ERROR: need at least 1.5 s of steady sine; render with --dur 10")
    nper = int(2 ** np.round(np.log2(sr * 0.1)))
    hop = nper // 8
    res = {"file": rel(a.file), "f0_hz": f0, "analysed_s": [(s0 - t0) / sr, (s1 - t0) / sr], "channels": {}}
    print("%s  f0=%.1f Hz, steady part %.2f-%.2f s" % (rel(a.file), f0, *res["analysed_s"]))
    for ci in range(x.shape[0]):
        y = x[ci, s0:s1]
        if not np.any(y):
            continue
        f, t, Z = sps.stft(y, sr, window="hann", nperseg=nper, noverlap=nper - hop, boundary=None)
        mag = np.abs(Z)
        lo, hi = np.searchsorted(f, f0 * 0.9 - 20), np.searchsorted(f, f0 * 1.1 + 20)
        track, amp = [], []
        for k in range(mag.shape[1]):
            m = mag[lo:hi, k]
            i = int(np.argmax(m))
            if 0 < i < m.size - 1:  # parabolic interpolation in dB
                al, be, ga = np.log(m[i - 1:i + 2] + 1e-30)
                d = 0.5 * (al - ga) / (al - 2 * be + ga)
            else:
                d = 0.0
            track.append(f[lo + i] + d * (f[1] - f[0]))
            amp.append(m[i])
        track, amp = np.array(track), np.array(amp)
        dev = track - np.mean(track)
        fr = sr / hop
        spec = np.abs(np.fft.rfft(sps.detrend(track) * np.hanning(track.size)))
        rf = np.fft.rfftfreq(track.size, 1 / fr)
        ok = (rf >= 0.05) & (rf <= 20)
        rate = float(rf[ok][np.argmax(spec[ok])]) if np.any(ok) else None
        aspec = np.abs(np.fft.rfft(sps.detrend(20 * np.log10(amp + 1e-30)) * np.hanning(amp.size)))
        arate = float(rf[ok][np.argmax(aspec[ok])]) if np.any(ok) else None
        fw, pw = sps.welch(y, sr, nperseg=min(y.size, 1 << 16))
        pk = int(np.argmax(pw))
        above = np.nonzero(pw > pw[pk] * 0.01)[0]  # -20 dB
        near = above[np.abs(fw[above] - fw[pk]) < f0 * 0.2]
        c = {
            "mean_freq_hz": float(np.mean(track)),
            "freq_dev_std_hz": float(np.std(dev)), "freq_dev_peak_hz": float(np.max(np.abs(dev))),
            "freq_dev_std_cents": float(1200 * np.log2(1 + np.std(dev) / f0)),
            "dominant_fm_rate_hz": rate,
            "amp_dev_std_db": float(np.std(20 * np.log10(amp + 1e-30))),
            "dominant_am_rate_hz": arate,
            "bandwidth_-20db_hz": float(fw[near.max()] - fw[near.min()]) if near.size else None,
            "welch_resolution_hz": float(fw[1] - fw[0]),
            "track_frame_rate_hz": fr,
        }
        res["channels"][chname(ci, x.shape[0])] = c
        print("  %s: mean %.2f Hz | FM dev std %.3f Hz (%.2f cents), peak %.3f Hz, rate %s Hz | "
              "AM std %.2f dB, rate %s Hz | -20 dB bandwidth %s Hz"
              % (chname(ci, x.shape[0]), c["mean_freq_hz"], c["freq_dev_std_hz"], c["freq_dev_std_cents"],
                 c["freq_dev_peak_hz"], fmt(rate, "%.3f"), c["amp_dev_std_db"], fmt(arate, "%.3f"),
                 fmt(c["bandwidth_-20db_hz"], "%.2f")))
        if a.plot and ci == 0:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(2, 1, figsize=(11, 6))
            ax[0].plot(t, track)
            ax[0].set(title="tracked frequency near %.0f Hz (ch0)" % f0, xlabel="s", ylabel="Hz")
            ax[1].plot(t, 20 * np.log10(amp + 1e-30))
            ax[1].set(title="amplitude at tracked peak", xlabel="s", ylabel="dB")
            fig.tight_layout()
            fig.savefig(out_base(a.file) + ".mod.png", dpi=110)
            print("  plot %s" % rel(out_base(a.file) + ".mod.png"))
    print("  note: the output is a sum of many delayed, modulated copies, so these are\n"
          "  aggregate figures. Compare settings (e.g. depth) rather than reading them as absolutes.")
    p = out_base(a.file) + ".mod.json"
    write_json(p, res)
    print("  saved %s" % rel(p))


# --------------------------------------------------------------------------
# Compare two renders (plugin vs plugin, or plugin vs your implementation)
# --------------------------------------------------------------------------
def cmd_compare(a):
    xa, sra, ta, _ = load(a.a, a.t0)
    xb, srb, tb, _ = load(a.b, a.t0)
    if sra != srb:
        sys.exit("ERROR: sample rates differ (%d vs %d)" % (sra, srb))
    sr = sra
    nch = min(xa.shape[0], xb.shape[0])
    ya, yb = xa[:nch, ta:], xb[:nch, tb:]
    n = min(ya.shape[1], yb.shape[1])
    ya, yb = ya[:, :n], yb[:, :n]
    m = min(n, int(2 * sr))
    xc = sps.correlate(ya[0, :m], yb[0, :m], mode="full", method="fft")
    lag = int(np.argmax(np.abs(xc))) - (m - 1)  # >0: A is later than B
    if lag > 0:
        ya, yb = ya[:, lag:], yb[:, : n - lag]
    elif lag < 0:
        ya, yb = ya[:, : n + lag], yb[:, -lag:]
    ea, eb = np.sum(ya ** 2), np.sum(yb ** 2)
    g = np.sum(ya * yb) / eb if eb > 0 else 0.0
    res = {
        "a": rel(a.a), "b": rel(a.b), "sample_rate": sr,
        "identical": bool(np.array_equal(xa, xb)),
        "lag_samples_a_minus_b": lag, "lag_ms": lag / sr * 1e3,
        "level_diff_db_a_minus_b": float(db(ea) - db(eb)),
        "null_db": float(db(np.sum((ya - yb) ** 2)) - db(ea)) if ea > 0 else None,
        "null_db_gain_matched": float(db(np.sum((ya - g * yb) ** 2)) - db(ea)) if ea > 0 else None,
        "correlation": float(np.sum(ya * yb) / np.sqrt(ea * eb)) if ea > 0 and eb > 0 else None,
    }
    print("A %s\nB %s" % (rel(a.a), rel(a.b)))
    print("  identical files: %s | lag A-B %d smp (%.2f ms) | level A-B %.2f dB | correlation %s"
          % (res["identical"], lag, res["lag_ms"], res["level_diff_db_a_minus_b"], fmt(res["correlation"], "%.4f")))
    print("  null (residual re A) %s dB, gain-matched %s dB   (< -60 dB: practically identical)"
          % (fmt(res["null_db"], "%.1f"), fmt(res["null_db_gain_matched"], "%.1f")))
    ra, rb = ir_metrics(xa[:nch], sr, ta), ir_metrics(xb[:nch], sr, tb)
    res["bands"] = {}
    for ch in ra["channels"]:
        A, B = ra["channels"][ch], rb["channels"].get(ch, {})
        if A.get("silent") or not B or B.get("silent"):
            continue
        print("  %s  first arrival A %.2f ms / B %.2f ms | T30 A %s / B %s s"
              % (ch, A["first_arrival_ms"], B["first_arrival_ms"], fmt(A["T30_s"], "%.2f"), fmt(B["T30_s"], "%.2f")))
        print("      band      " + " ".join("%7s" % b for b in A["bands"]))
        rows = {"T30 A": [], "T30 B": [], "T30 diff%": [], "lvl A-B dB": []}
        for bnd, va in A["bands"].items():
            vb = B["bands"].get(bnd, {})
            ta_, tb_ = va.get("T30_s"), vb.get("T30_s")
            rows["T30 A"].append(fmt(ta_, "%.2f"))
            rows["T30 B"].append(fmt(tb_, "%.2f"))
            rows["T30 diff%"].append(fmt(100 * (ta_ - tb_) / tb_ if ta_ and tb_ else None, "%+.1f"))
            rows["lvl A-B dB"].append(fmt(va["level_db"] - vb["level_db"] if vb else None, "%+.1f"))
        for k, v in rows.items():
            print("      %-10s" % k + " ".join("%7s" % s for s in v))
        res["bands"][ch] = rows
    p = os.path.join(OUT_DIR, "compare__%s__vs__%s.json" % (
        os.path.splitext(os.path.basename(a.a))[0][:60], os.path.splitext(os.path.basename(a.b))[0][:60]))
    write_json(p, res)
    print("  (measured from each file's own t0, so a predelay difference doesn't affect the band table)")
    print("  saved %s" % rel(p))


def cmd_info(a):
    x, sr, t0, side = load(a.file, a.t0)
    pk = np.max(np.abs(x), axis=1)
    rms = np.sqrt(np.mean(x ** 2, axis=1))
    print("%s  sr=%d  ch=%d  %.3f s  t0=%d" % (rel(a.file), sr, x.shape[0], x.shape[1] / sr, t0))
    for i in range(x.shape[0]):
        print("  %s peak %s dBFS  rms %s dBFS" % (chname(i, x.shape[0]),
              fmt(20 * np.log10(pk[i]) if pk[i] > 0 else None, "%.1f"),
              fmt(20 * np.log10(rms[i]) if rms[i] > 0 else None, "%.1f")))
    if side:
        print("  signal %s" % side.get("signal"))
        print("  changed from default %s" % side.get("changed_from_default"))


def cmd_spectrogram(a):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x, sr, t0, _ = load(a.file, a.t0)
    fig, axs = plt.subplots(x.shape[0], 1, figsize=(11, 4 * x.shape[0]), squeeze=False)
    for ci in range(x.shape[0]):
        f, t, S = sps.spectrogram(x[ci], sr, nperseg=a.nfft, noverlap=a.nfft * 3 // 4)
        axs[ci, 0].pcolormesh(t, f, 10 * np.log10(S + 1e-20), shading="auto", vmin=-160)
        axs[ci, 0].set(title=chname(ci, x.shape[0]), xlabel="s", ylabel="Hz", yscale="symlog", ylim=(20, sr / 2))
    fig.tight_layout()
    p = out_base(a.file) + ".spec.png"
    fig.savefig(p, dpi=110)
    print("plot %s" % rel(p))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def p_(name, func, helptext, two=False):
        p = sub.add_parser(name, help=helptext)
        if two:
            p.add_argument("a")
            p.add_argument("b")
        else:
            p.add_argument("file")
        p.add_argument("--t0", type=float, help="signal start in seconds (default: from sidecar)")
        p.set_defaults(func=func)
        return p

    p_("info", cmd_info, "length, peak, RMS, sidecar summary")
    p = p_("ir", cmd_ir, "impulse response: arrival, EDT/T20/T30 per octave, echo density, L/R correlation")
    p.add_argument("--onset-db", type=float, default=-40.0, help="first-arrival threshold re peak (default -40)")
    p.add_argument("--plot", action="store_true")
    p = p_("peaks", cmd_peaks, "strongest discrete arrivals in a time window (delay taps)")
    p.add_argument("--start-ms", type=float, default=0.0)
    p.add_argument("--end-ms", type=float, default=120.0)
    p.add_argument("--n", type=int, default=25)
    p.add_argument("--min-gap-ms", type=float, default=0.1)
    p = p_("mod", cmd_mod, "frequency/amplitude modulation of a rendered sine")
    p.add_argument("--freq", type=float)
    p.add_argument("--plot", action="store_true")
    p_("compare", cmd_compare, "align two renders; null test, level, per-band T30", two=True)
    p = p_("spectrogram", cmd_spectrogram, "save a spectrogram PNG")
    p.add_argument("--nfft", type=int, default=4096)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
