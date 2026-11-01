# REAudio

Behavioural analysis of an audio plugin (VST3/AU, macOS) and an independent C++ clone
that matches its sound. The target is the single `PLUGIN=` line in `CLAUDE.md`.

Two methods:
- **Static analysis** of the arm64 slice with REA (Ghidra headless).
- **Offline audio renders** through the installed plugin, measured with scripts.

No original source is recovered or reproduced. Findings describe behaviour:
signal flow, delay times, decay, filtering, modulation.

Agent instructions (rules, workflow, evidence standards) are in
[`CLAUDE.md`](CLAUDE.md). Claude Code reads it directly. opencode is expected to
fall back to it as long as there is no `AGENTS.md`, so don't add one.

## Layout

```
CLAUDE.md                 instructions for the analysis agent
analysis/
  TARGET.md               target identity: path, version, hashes (created in Step 0)
  FINDINGS.md             numbered findings: Confirmed / Hypothesis / Unknown
  LOG.md                  one entry per session, ends with the next step
  tools/render.py         headless renderer (pedalboard)
  tools/analyze.py        IR, delay taps, modulation, comparison
  tools/requirements.txt  pinned Python packages
  slices/                 single-architecture binaries (git-ignored)
  audio/renders/          rendered WAVs + JSON sidecars (WAVs git-ignored)
  out/                    analysis results, plots, saved tool output
  COVERAGE.md             per-parameter progress: measured / spec / clone / A/B pass
  SPEC.md                 behavioural spec for the clone
  archive/<name>/         work on previous targets
clone/                    the C++ clone (CMake)
```

## Setup

Requires Homebrew Python (`/opt/homebrew/bin/python3`), the plugin installed
and licensed, and REA with Ghidra for static analysis.

```
/opt/homebrew/bin/python3 -m venv --clear .venv
.venv/bin/pip install -r analysis/tools/requirements.txt
```

Rebuild the venv the same way after a Homebrew Python upgrade.

**Do not use Apple's Python** (`/usr/bin/python3`, Xcode's python3). Loading a
PACE-protected plugin there crashes with EXC_GUARD: PACE can't set exception
ports in Apple-signed processes. The scripts refuse to run under it.

## Quick start

```
.venv/bin/python analysis/tools/render.py params
.venv/bin/python analysis/tools/render.py render --vary decay_time_seconds=1.4,5
.venv/bin/python analysis/tools/analyze.py ir \
    analysis/audio/renders/<name>.wav --plot
```

Some plugins load data in the background and output silence until ready; render.py
waits for that automatically (`--settle auto`). If repeated renders of the same settings
differ, compare measurements rather than samples. More recipes are in `CLAUDE.md` under "Audio renders".
Each script also takes `--help`.

To compare your own implementation, render it with `--plugin <path to your .vst3>`
using the same settings, then run `analyze.py compare plugin.wav yours.wav`.

## Ground rules

- The installed plugin and its content files are never modified, patched,
  re-signed or decrypted.
- No licence or copy-protection bypass. Protected plugins get static analysis and renders
  only (no debuggers or Frida). The clone can be debugged freely.
- Check the vendor's licence terms before publishing or shipping anything derived
  from this work.
