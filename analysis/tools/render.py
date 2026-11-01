#!/usr/bin/env python3
"""Headless offline renderer for VST3 / AU plugins (via Spotify pedalboard).

Run with the project venv (never /usr/bin/python3, see _common.py):

    .venv/bin/python analysis/tools/render.py params
    .venv/bin/python analysis/tools/render.py render --signal impulse --set mix=100
    .venv/bin/python analysis/tools/render.py render --signal impulse --sr 44100,48000,96000
    .venv/bin/python analysis/tools/render.py render --signal impulse --vary program=all
    .venv/bin/python analysis/tools/render.py signal --signal sine --freq 440 --out x.wav

Every render writes:
    analysis/audio/renders/<name>.wav   float32 WAV (no clipping in the file)
    analysis/audio/renders/<name>.json  sidecar: plugin + hash, sample rate, signal,
                                        impulse index, requested and APPLIED settings
A fresh plugin instance is created for every render, so renders don't affect each other.
"""
import argparse
import contextlib
import itertools
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (  # noqa: E402
    DEFAULT_PLUGIN, OUT_DIR, PROJECT, RENDER_DIR, check_interpreter,
    plugin_executable, rel, sha256, slug, write_json,
)

check_interpreter()

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

PLUGIN_LOG = os.path.join(PROJECT, "analysis", "out", "plugin_stdout.log")
HIDDEN_PREFIXES = ("midi_cc_",)


# --------------------------------------------------------------------------
# Plugin loading (with the plugin's own console spam redirected to a log)
# --------------------------------------------------------------------------
@contextlib.contextmanager
def quiet_fds():
    """Send C-level stdout/stderr (the plugin's logging) to PLUGIN_LOG."""
    os.makedirs(os.path.dirname(PLUGIN_LOG), exist_ok=True)
    sys.stdout.flush()
    sys.stderr.flush()
    log = open(PLUGIN_LOG, "a")
    saved = os.dup(1), os.dup(2)
    os.dup2(log.fileno(), 1)
    os.dup2(log.fileno(), 2)
    try:
        yield
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(saved[0], 1)
        os.dup2(saved[1], 2)
        os.close(saved[0])
        os.close(saved[1])
        log.close()


def load(plugin_path, plugin_name=None):
    import pedalboard

    if not os.path.exists(plugin_path):
        sys.exit("ERROR: plugin not found: %s" % plugin_path)
    with quiet_fds():
        if plugin_name:
            return pedalboard.load_plugin(plugin_path, plugin_name=plugin_name)
        return pedalboard.load_plugin(plugin_path)


def visible_params(plugin):
    return {k: v for k, v in plugin.parameters.items()
            if not k.startswith(HIDDEN_PREFIXES)}


def param_state(plugin):
    """name -> displayed string value (what the plugin reports after changes)."""
    return {k: v.string_value.strip() for k, v in visible_params(plugin).items()}


# --------------------------------------------------------------------------
# Parameter value parsing
# --------------------------------------------------------------------------
_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _num(s):
    s = str(s).strip().lower()
    if s.startswith("-oo") or s in ("-inf", "-∞"):
        return float("-inf")
    m = _NUM.search(s)
    if not m:
        return None
    v = float(m.group())
    if "khz" in s:
        v *= 1000.0
    return v


def set_param(plugin, name, value):
    """Set one parameter. Returns a short description of what was applied.

    value forms:
      raw:0.25     normalised 0..1 host value
      on/off       for boolean parameters (also true/false/1/0)
      Room A       an exact display value (case-insensitive)
      540 / 3.0s / 6.6kHz   nearest valid value by number (units stripped;
                   kHz is converted to Hz)
    """
    params = plugin.parameters
    if name not in params:
        close = [k for k in visible_params(plugin) if name.lower() in k.lower()]
        sys.exit("ERROR: unknown parameter %r. Similar: %s. Run `render.py params`."
                 % (name, ", ".join(close) or "none"))
    p = params[name]
    v = str(value).strip()

    if v.lower().startswith("raw:"):
        p.raw_value = float(v[4:])
        return p.string_value.strip()

    valid = list(p.valid_values or [])
    if valid and all(isinstance(x, bool) for x in valid):
        b = v.lower() in ("on", "true", "1", "yes")
        if v.lower() not in ("on", "off", "true", "false", "1", "0", "yes", "no"):
            sys.exit("ERROR: %s is on/off, got %r" % (name, value))
        setattr(plugin, name, b)
        return p.string_value.strip()

    if valid:
        for x in valid:  # exact display-string match
            if str(x).strip().lower() == v.lower():
                setattr(plugin, name, x)
                return p.string_value.strip()
        target = _num(v)
        if target is None:
            sys.exit("ERROR: %r is not a valid value for %s. Valid: %s"
                     % (value, name, ", ".join(str(x).strip() for x in valid[:20])))
        nums = [(_num(x) if not isinstance(x, (int, float)) else float(x)) for x in valid]
        best = min((i for i, n in enumerate(nums) if n is not None),
                   key=lambda i: abs(nums[i] - target) if np.isfinite(nums[i]) else 1e300)
        setattr(plugin, name, valid[best])
        return p.string_value.strip()

    setattr(plugin, name, float(_num(v)))
    return p.string_value.strip()


# --------------------------------------------------------------------------
# Test signals
# --------------------------------------------------------------------------
def make_signal(a, sr):
    """Return (audio[channels, n], info dict). Tail zeros are appended later."""
    kind = a.signal
    pre = int(round(a.preroll * sr))
    amp = 10 ** (a.level / 20.0)
    info = {"kind": kind, "level_dbfs": a.level, "preroll_s": a.preroll}

    if kind.startswith("file:"):
        path = kind[5:]
        x, fsr = sf.read(path, dtype="float32", always_2d=True)
        if fsr != sr:
            sys.exit("ERROR: %s is %d Hz but --sr is %d. Resample it first or pass --sr %d."
                     % (path, fsr, sr, fsr))
        x = x.T
        if x.shape[0] == 1:
            x = np.vstack([x, x])
        info.update(path=os.path.abspath(path), sha256=sha256(path), level_dbfs=None)
        return x, info

    n = int(round(a.dur * sr))
    mono = np.zeros(pre + max(n, 1), dtype=np.float64)
    t = np.arange(n) / sr
    if kind == "impulse":
        mono[pre] = amp
        info["impulse_index"] = pre
    elif kind == "sine":
        mono[pre:pre + n] = amp * np.sin(2 * np.pi * a.freq * t)
        info.update(freq_hz=a.freq, dur_s=a.dur)
    elif kind == "noise":
        rng = np.random.default_rng(a.seed)
        mono[pre:pre + n] = amp * rng.uniform(-1, 1, n)
        info.update(dur_s=a.dur, seed=a.seed, dist="uniform")
    elif kind == "sweep":  # exponential sine sweep (Farina)
        f1, f2 = a.f1, min(a.f2, sr * 0.45)
        k = np.log(f2 / f1)
        mono[pre:pre + n] = amp * np.sin(2 * np.pi * f1 * a.dur / k * (np.exp(t * k / a.dur) - 1))
        info.update(f1_hz=f1, f2_hz=f2, dur_s=a.dur)
    elif kind == "burst":  # tone burst with Hann envelope
        env = np.hanning(n) if n > 1 else np.ones(1)
        mono[pre:pre + n] = amp * env * np.sin(2 * np.pi * a.freq * t)
        info.update(freq_hz=a.freq, dur_s=a.dur)
    elif kind == "silence":
        info.update(dur_s=a.dur)
    else:
        sys.exit("ERROR: unknown --signal %r" % kind)

    x = np.zeros((2, mono.size), dtype=np.float32)
    if a.inject in ("both", "L"):
        x[0] = mono
    if a.inject in ("both", "R"):
        x[1] = mono
    info["inject"] = a.inject
    return x, info


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------
def cmd_params(a):
    plugin = load(a.plugin, a.plugin_name)
    rows, full = [], {}
    for name, p in visible_params(plugin).items():
        valid = list(p.valid_values or [])
        vs = [str(x).strip() for x in valid]
        if len(vs) > 8:
            shown = "%s .. %s (%d values)" % (", ".join(vs[:3]), ", ".join(vs[-2:]), len(vs))
        else:
            shown = ", ".join(vs)
        rows.append((name, p.string_value.strip(), "%.4f" % p.raw_value, shown))
        full[name] = {"default_display": p.string_value.strip(),
                      "default_raw": p.raw_value,
                      "range": list(p.range) if p.range else None,
                      "valid_values": vs}
    w = max(len(r[0]) for r in rows)
    print("%-*s  %-12s %-7s %s" % (w, "name", "default", "raw", "valid values"))
    for r in rows:
        print("%-*s  %-12s %-7s %s" % (w, r[0], r[1], r[2], r[3]))
    out = a.json or os.path.join(OUT_DIR, "params_%s.json" % slug(_tag(a.plugin)))
    write_json(out, {"plugin": a.plugin, "name": plugin.name, "parameters": full})
    print("\nfull list saved: %s" % rel(out))


def cmd_signal(a):
    x, info = make_signal(a, a.sr[0])
    x = np.concatenate([x, np.zeros((2, int(a.tail * a.sr[0])), np.float32)], axis=1)
    sf.write(a.out, x.T, a.sr[0], subtype="FLOAT")
    print("wrote %s  (%d Hz, %.3f s) %s" % (a.out, a.sr[0], x.shape[1] / a.sr[0], info))


def _tag(plugin_path):
    return os.path.splitext(os.path.basename(plugin_path.rstrip("/")))[0]


def _expand_vary(plugin_path, plugin_name, vary):
    """--vary name=v1,v2  or  name=all  ->  list of (name, [values])."""
    out = []
    probe = None
    for spec in vary:
        if "=" not in spec:
            sys.exit("ERROR: --vary needs name=v1,v2,... got %r" % spec)
        name, vals = spec.split("=", 1)
        if vals.strip().lower() == "all":
            probe = probe or load(plugin_path, plugin_name)
            if name not in probe.parameters:
                sys.exit("ERROR: unknown parameter %r" % name)
            valid = list(probe.parameters[name].valid_values or [])
            if not valid or len(valid) > 64:
                sys.exit("ERROR: %s has %d values; list them explicitly" % (name, len(valid)))
            vals = [str(v).strip() for v in valid]
        else:
            vals = [v.strip() for v in vals.split(",")]
        out.append((name, vals))
    return out


def cmd_render(a):
    exe = plugin_executable(a.plugin)
    exe_hash = sha256(exe) if exe else None
    import pedalboard

    sets = []
    for s in a.set or []:
        if "=" not in s:
            sys.exit("ERROR: --set needs name=value, got %r" % s)
        k, v = s.split("=", 1)
        sets.append((k.strip(), v.strip()))
    if a.program:
        sets.insert(0, ("program", a.program))  # program first: it may reset others

    vary = _expand_vary(a.plugin, a.plugin_name, a.vary or [])
    names = [n for n, _ in vary]
    combos = list(itertools.product(*[v for _, v in vary])) or [()]
    os.makedirs(a.outdir, exist_ok=True)

    for sr in a.sr:
        for combo in combos:
            settings = list(sets)
            # a varied 'program' must be applied before other settings
            for n, v in zip(names, combo):
                if n == "program":
                    settings = [(n, v)] + [s for s in settings if s[0] != "program"]
                else:
                    settings = [s for s in settings if s[0] != n] + [(n, v)]

            plugin = load(a.plugin, a.plugin_name)
            defaults = param_state(plugin)
            applied = {}
            for k, v in settings:
                applied[k] = set_param(plugin, k, v)
            state = param_state(plugin)

            x, info = make_signal(a, sr)
            x = np.concatenate([x, np.zeros((2, int(round(a.tail * sr))), np.float32)], axis=1)
            t = time.time()
            with quiet_fds():
                y = plugin.process(x, float(sr), buffer_size=a.block, reset=True)
            elapsed = time.time() - t
            y = np.asarray(y, dtype=np.float32)
            if y.shape[1] < x.shape[1]:
                y = np.pad(y, ((0, 0), (0, x.shape[1] - y.shape[1])))

            label = "_".join(slug("%s%s" % (k, v)) for k, v in settings) or "defaults"
            name = a.name or "%s__%s_%dk__%s" % (
                slug(_tag(a.plugin)), slug(a.signal.split("/")[-1]), round(sr / 1000), label)
            if a.name and (len(combos) > 1 or len(a.sr) > 1):
                name = "%s__%d__%s" % (a.name, sr, label)
            wav = os.path.join(a.outdir, name + ".wav")
            sf.write(wav, y.T, sr, subtype="FLOAT")
            if a.save_input:
                sf.write(os.path.join(a.outdir, name + ".input.wav"), x.T, sr, subtype="FLOAT")

            peak = float(np.max(np.abs(y))) if y.size else 0.0
            changed = {k: [defaults.get(k), v] for k, v in state.items() if defaults.get(k) != v}
            side = {
                "wav": rel(wav),
                "plugin": a.plugin,
                "plugin_name": plugin.name,
                "plugin_executable_sha256": exe_hash,
                "host": "pedalboard %s, python %s" % (pedalboard.__version__, sys.version.split()[0]),
                "sample_rate": sr,
                "block_size": a.block,
                "channels_out": int(y.shape[0]),
                "length_samples": int(y.shape[1]),
                "tail_s": a.tail,
                "signal": info,
                "requested": dict(settings),
                "applied": applied,
                "changed_from_default": changed,
                "all_params": state,
                "peak_dbfs": 20 * np.log10(peak) if peak > 0 else None,
                "render_seconds": round(elapsed, 3),
            }
            write_json(os.path.join(a.outdir, name + ".json"), side)
            pk = "%.1f dBFS" % side["peak_dbfs"] if peak > 0 else "SILENT"
            warn = "  WARNING: output above 0 dBFS" if peak > 1.0 else ""
            print("%s  peak %s  applied %s%s" % (rel(wav), pk, applied or "{}", warn))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--plugin", default=DEFAULT_PLUGIN, help="path to .vst3 or .component (default: %(default)s)")
        p.add_argument("--plugin-name", help="sub-plugin name if the bundle holds several")

    def sigargs(p):
        p.add_argument("--signal", default="impulse",
                       help="impulse | sine | noise | sweep | burst | silence | file:PATH (default impulse)")
        p.add_argument("--sr", default="48000", help="sample rate, or a list: 44100,48000,96000")
        p.add_argument("--level", type=float, default=-6.0, help="signal peak in dBFS (default -6)")
        p.add_argument("--dur", type=float, default=2.0, help="signal length in s (sine/noise/sweep/burst)")
        p.add_argument("--freq", type=float, default=1000.0, help="sine/burst frequency in Hz")
        p.add_argument("--f1", type=float, default=20.0, help="sweep start Hz")
        p.add_argument("--f2", type=float, default=20000.0, help="sweep end Hz")
        p.add_argument("--seed", type=int, default=1, help="noise seed")
        p.add_argument("--preroll", type=float, default=0.05, help="silence before the signal, s (default 0.05)")
        p.add_argument("--tail", type=float, default=8.0, help="silence after the signal, s (default 8)")
        p.add_argument("--inject", choices=["both", "L", "R"], default="both", help="input channel(s)")

    p = sub.add_parser("params", help="list plugin parameters and valid values")
    common(p)
    p.add_argument("--json", help="where to save the full list (default analysis/out/params_<plugin>.json)")
    p.set_defaults(func=cmd_params)

    p = sub.add_parser("render", help="render a test signal through the plugin")
    common(p)
    sigargs(p)
    p.add_argument("--program", help="program/preset name, applied before --set")
    p.add_argument("--set", action="append", metavar="NAME=VALUE", help="set a parameter (repeatable)")
    p.add_argument("--vary", action="append", metavar="NAME=V1,V2|all",
                   help="render once per value (repeatable: all combinations)")
    p.add_argument("--block", type=int, default=512, help="host block size (default 512)")
    p.add_argument("--name", help="output base name (default: built from the settings)")
    p.add_argument("--outdir", default=RENDER_DIR, help="default analysis/audio/renders")
    p.add_argument("--save-input", action="store_true", help="also write the input signal")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("signal", help="write a test signal to a WAV without rendering")
    sigargs(p)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_signal)

    a = ap.parse_args()
    if hasattr(a, "sr"):
        a.sr = [int(float(s)) for s in str(a.sr).split(",")]
    a.func(a)
    # The plugin also logs from its static destructors at exit: keep that
    # out of the terminal too.
    sys.stdout.flush()
    sys.stderr.flush()
    log = open(PLUGIN_LOG, "a")
    os.dup2(log.fileno(), 1)
    os.dup2(log.fileno(), 2)


if __name__ == "__main__":
    main()
