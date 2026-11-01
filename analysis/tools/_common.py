"""Shared helpers for render.py and analyze.py.

Run every tool with the project venv:
    .venv/bin/python analysis/tools/<tool>.py ...
"""
import hashlib
import json
import os
import re
import sys

PROJECT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _plugin_from_claude_md():
    """The target plugin is the single `PLUGIN=<path>` line in CLAUDE.md."""
    try:
        with open(os.path.join(PROJECT, "CLAUDE.md")) as f:
            m = re.search(r"^PLUGIN=(.+?)\s*$", f.read(), re.M)
        return m.group(1).strip().strip('"') if m else None
    except OSError:
        return None


DEFAULT_PLUGIN = _plugin_from_claude_md()
RENDER_DIR = os.path.join(PROJECT, "analysis", "audio", "renders")
OUT_DIR = os.path.join(PROJECT, "analysis", "out")


def check_interpreter():
    """Refuse to run under Apple's Python.

    PACE-protected plugins (UADx) call task_set_exception_ports while they
    load. Apple-signed Python (/usr/bin/python3, Xcode's python3) has
    guarded exception ports, so the process is killed with EXC_GUARD and
    macOS shows a "Python quit unexpectedly" dialog. Homebrew Python works.
    """
    real = os.path.realpath(sys.executable)
    bad = ("/usr/bin/", "/System/", "/Applications/Xcode", "/Library/Developer/")
    if real.startswith(bad):
        sys.exit(
            "ERROR: running under Apple Python (%s).\n"
            "Use the project venv instead:  .venv/bin/python %s ..."
            % (real, os.path.relpath(sys.argv[0], PROJECT))
        )


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def plugin_executable(plugin_path):
    """Return the Mach-O inside a .vst3/.component bundle (or None)."""
    macos = os.path.join(plugin_path, "Contents", "MacOS")
    if os.path.isdir(macos):
        names = sorted(os.listdir(macos))
        if names:
            return os.path.join(macos, names[0])
    return None


def slug(text):
    text = re.sub(r"[^A-Za-z0-9.+-]+", "-", str(text)).strip("-")
    return text[:120] or "x"


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, default=_json_default)
        f.write("\n")


def _json_default(o):
    try:
        import numpy as np

        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
    except ImportError:
        pass
    return str(o)


def rel(path):
    return os.path.relpath(path, PROJECT)
