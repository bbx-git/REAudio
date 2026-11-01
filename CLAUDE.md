# Project: Audio Plugin Analysis

## Objective

Analyse the audio plugin below with REA (which runs Ghidra headless) and with
offline audio renders.

Goal: understand its architecture and audio processing well enough to write a
behavioural spec for an independent C++ implementation with comparable sound.

- Audio processing comes first. Ignore the UI unless it explains a parameter.
- Original source code cannot be recovered. That is not the goal.
- Describe findings as behaviour: signal flow, delay lengths, gains, filter
  coefficients, modulation. Do not paste decompiled code into the spec or the
  implementation.

## Target

- `<bundle>` = `/Library/Audio/Plug-Ins/VST3/uaudio_lexicon_224.vst3`
- `<exe>` = `<bundle>/Contents/MacOS/uaudio_lexicon_224`
- Version 1.4.16 (build 1508). UADx (native, CPU) version: see F-001.
- The same plugin as AU: `/Library/Audio/Plug-Ins/Components/uaudio_lexicon_224.component`
  (same audio as the VST3, see F-003).
- macOS on Apple Silicon. Analyse the arm64 slice.
- Findings about any other plugin do not apply here unless re-checked against
  this exact binary.

## Session files: read these first, every session

Everything you write goes under `analysis/` in this project. Do not use /tmp.

| Path | Contents |
|---|---|
| `analysis/TARGET.md` | Executable path, version, SHA-256 of `<exe>` and of the slice, architectures, REA provider status |
| `analysis/FINDINGS.md` | Numbered findings (F-001, F-002, ...): Confirmed / Hypothesis / Unknown |
| `analysis/LOG.md` | One entry per session: what was done, exact errors, open questions, **Next step** |
| `analysis/slices/` | Single-architecture slices |
| `analysis/out/` | Saved tool output (pseudo-code, string lists, analysis JSON, plots) |
| `analysis/audio/renders/` | Rendered WAVs, each with a `.json` sidecar |
| `analysis/tools/` | `render.py`, `analyze.py`: ready to use, see "Audio renders" |

At the start of a session: read `TARGET.md`, then `FINDINGS.md`, then the last
entry in `LOG.md`. Continue from its **Next step**.
At the end of each step: update `FINDINGS.md` and append to `LOG.md`.

## Rules

- Never modify, patch, re-sign, move, or overwrite anything inside `<bundle>`
  or the `.component`.
- Write only inside this project directory.
- Ask first before you: install anything, edit any config (opencode, REA,
  shell, system), delete files outside `analysis/`, kill a process, or
  analyse files outside the two plugin bundles.
- Do not investigate license bypasses or disable protection mechanisms. The
  bundle contains `Resources/__Pace_Eden` (PACE anti-tamper). Consequences:
  - Never attach a debugger, Frida, gdb or rizin-debug to the plugin or to a
    process that loaded it. Use static analysis and audio renders only.
  - Static code may contain obfuscated regions. Record where in `LOG.md` and
    move on; do not try to decrypt or unpack them.
- Never repeat a failing command or tool call unchanged. If two different
  approaches fail on the same problem, stop and report.

## Step 0: Establish the target

If `analysis/TARGET.md` exists, skip this step. Only re-check the SHA-256
of `<exe>`. If it differs from `TARGET.md`, the plugin has been updated:
stop and tell the user. Old addresses and findings no longer apply.

Otherwise run these and record the results in `TARGET.md`. These are macOS
(BSD/LLVM) tools: do not use GNU-only flags. Shell variables do not persist
between commands, so write out full paths.

| Purpose | Command |
|---|---|
| Executable name, version | `plutil -p <bundle>/Contents/Info.plist` |
| Bundle contents | `ls -la <bundle>/Contents/MacOS <bundle>/Contents/Resources` |
| Plugin manifest (parameter IDs, program names) | `cat <bundle>/Contents/Resources/manifest.json` |
| Architectures | `lipo -info <exe>` |
| Hash | `shasum -a 256 <exe>` |
| Linked libraries | `otool -arch arm64 -L <exe>` |
| Exported symbols | `nm -arch arm64 -gU <exe>` (shows `_GetPluginFactory`; also `juce::` and `boost::` symbols) |
| Signature (read-only) | `codesign -dv --verbose=2 <bundle> 2>&1` |
| Make the slice | `lipo -thin arm64 <exe> -output analysis/slices/uaudio_lexicon_224-arm64` |
| Slice hash | `shasum -a 256 analysis/slices/uaudio_lexicon_224-arm64` |
| REA providers | `rea doctor` |

There is no `moduleinfo.json` in this bundle; use `manifest.json`.

`objdump` on your PATH is Apple's LLVM objdump. GNU objdump is at
`/opt/homebrew/opt/binutils/bin/objdump` and has limited Mach-O/arm64
support; prefer otool, LLVM objdump, or REA. Choose flags for the task;
do not add `-i` by default.

## REA and Ghidra

Verified on this Mac, 2026-11-01. Ghidra 12.1.4 runs headless inside REA.

Tool names below are bare (`open_binary`). opencode lists them as
`rea_<name>`, Claude Code as `mcp__rea__<name>`. Use the exact name your tool
list shows.

Setup is done. Do not change it:
- Never run `ghidraRun` or open the Ghidra GUI.
- Do not set `GHIDRA_INSTALL_DIR` or `JAVA_HOME`. REA's MCP config provides them.
- If REA reports Ghidra or Java not found: stop and tell the user.
- Do not touch `~/Library/ghidra/ghidra_12.1.4_PUBLIC`,
  `/private/tmp/ghidra_12.1.4.zip`, or `/private/tmp/ghidra-12.1.4.rb`.

Workflow:
1. `open_binary` with `path` = absolute path of the arm64 slice. The
   parameter is `path`, not `input_path`. Never pass the universal `<exe>`.
   Auto-analysis can take several minutes. Wait for it.
2. `binary_overview` at most once per session, and it is optional. If it
   times out or turns into a background task, do not call it again and do not
   guess its result: continue with `search_procedures`, `search_strings` and
   `procedure_pseudo_code`.
3. Never pull a full list into context. Use `search_procedures` or
   `search_strings` with a pattern, or page through `inspect_analysis_view`
   in small pages. `detail: summary` returns counts only;
   `detail: complete` returns values. Save useful results to `analysis/out/`.
4. `procedure_pseudo_code` with a name or address.
5. `xrefs` only with an explicit address.
6. `close_binary` when finished.

Errors:
- `target_unavailable: No app is open`: run `open_binary`, then retry once.
- `main` or `_start` not found: normal. A plugin is a bundle loaded by a
  host and has no `main`. Start from `_GetPluginFactory`.
- Universal binary rejected: you passed `<exe>`. Use the slice.
- Anything else: record the exact error text in `LOG.md` and classify it
  as install/discovery, import, architecture limitation, or unsupported
  option. One failed call does not mean a tool is unavailable.

Process check (no GUI):
- `ps -Ao pid,lstart,command | grep -i '[g]hidra'`
- `-Djava.awt.headless=true` is REA's worker. Leave it alone.
- `ghidra.GhidraRun` is a GUI. Stop it only with the user's approval.
- Install check: `rea doctor`, `ls /opt/homebrew/opt/ghidra`, `brew info ghidra`.

## Audio renders

You can render audio through the plugin yourself, offline, with no DAW. The
tools are ready; do not rewrite them. Run them from the project root with the
project venv:

```
.venv/bin/python analysis/tools/render.py  ...
.venv/bin/python analysis/tools/analyze.py ...
```

Never run them with `python3`, `/usr/bin/python3` or Xcode's Python: the PACE
protection crashes Apple's Python on load and the user gets a crash dialog.
The tools refuse to start there. If `.venv` is broken (for example after a
Homebrew Python upgrade), stop and ask the user. Do not reinstall it yourself.

### render.py

```
render.py params                                   # list parameters and valid values
render.py render [signal options] [settings]       # render, writes WAV + JSON sidecar
render.py signal --signal sine --out FILE.wav      # write a test signal only
```

Settings:
- `--program "Room A"`: set first, because a program changes other parameters (F-004).
- `--set NAME=VALUE`, repeatable. VALUE can be a display value (`"Room A"`, `on`,
  `off`), a number with or without unit (`540`, `3.0s`, `6.6kHz`; the nearest valid
  value is used), or `raw:0.25` (normalised 0..1).
- `--vary NAME=V1,V2,V3` or `--vary program=all`: one render per value.
  Several `--vary` flags render every combination.

Signal options: `--signal impulse|sine|noise|sweep|burst|silence|file:PATH`,
`--sr 48000` (or a list `44100,48000,96000`), `--level -6` (dBFS), `--dur 2`,
`--freq 1000`, `--tail 8`, `--preroll 0.05`, `--inject both|L|R`.
Other: `--plugin PATH` (default: the VST3 above; accepts any `.vst3`/`.component`,
including your own C++ build), `--name BASE`, `--block 512`, `--save-input`.

Output: `analysis/audio/renders/<name>.wav` (float32) and `<name>.json`. The
sidecar lists the requested values, the **applied** values as read back from the
plugin, `changed_from_default`, every parameter's final value, the plugin's
SHA-256, and `signal.impulse_index`. The tool prints one line per render.
Check `applied` there: if it differs from what you meant, fix the value. Each
render uses a fresh plugin instance.

### analyze.py

All times are relative to the signal start (from the sidecar), in ms and samples.

| Command | Use for |
|---|---|
| `info FILE` | length, peak, RMS, settings |
| `ir FILE [--plot]` | first arrival, peak, EDT/T20/T30 broadband and per octave, band levels, echo density, L/R correlation |
| `peaks FILE [--end-ms 120] [--n 25]` | strongest discrete early arrivals: candidate delay-tap times |
| `mod FILE [--plot]` | FM/AM rate and depth of a rendered sine |
| `compare A B` | alignment lag, null test, level difference, per-band T30 table |
| `spectrogram FILE` | PNG spectrogram |

Full results are saved to `analysis/out/<name>.<kind>.json` (and `.png`).
Quote these paths as evidence. Do not open PNGs unless you can view images.

### Test rules

- Deterministic mode: `--set depth=0 --set mode_enh=off` makes renders
  bit-identical (F-002). Use it for delay times, structure and null tests.
  With modulation on, compare statistics (T30, levels), never sample values.
- Use `--set mix=100`. `wet_solo` is On by default (see F-005).
- Change one parameter per test. Keep everything else identical, including the program.
- Delays that scale with sample rate keep their time in ms across 44.1/48/96 kHz;
  delays fixed in samples keep their sample count. Use `--sr 44100,48000,96000`,
  then `peaks` on each file.
- Check repeatability before you trust a difference: render the same settings
  twice and `compare` the two files.

Example recipes:

```
# impulse response of every program, deterministic
render.py render --vary program=all --set mix=100 --set depth=0 --set mode_enh=off
# which delays scale with sample rate
render.py render --program "Room A" --set mix=100 --set depth=0 --set mode_enh=off --sr 44100,48000,96000
analyze.py peaks analysis/audio/renders/<file>.wav --end-ms 100
# what a decay knob does per band
render.py render --program "Room A" --set mix=100 --vary bass=0.6,1.8,4.5,9
analyze.py ir analysis/audio/renders/<file>.wav
# modulation: long sine, compare depth settings
render.py render --signal sine --freq 1000 --dur 10 --tail 1 --set mix=100 --vary depth=0,23,71
analyze.py mod analysis/audio/renders/<file>.wav
```

Later, to compare your C++ implementation: render it with `--plugin <your build>`,
the same signal and settings, then run `analyze.py compare plugin.wav yours.wav`.

## Analysis priorities

Do one step at a time. Write its notes before you start the next one. Combine
static analysis with renders: a constant found in the code becomes Confirmed
when a render shows the matching behaviour.

1. **Architecture map.** Start at `_GetPluginFactory`. Find the processor and
   controller classes it creates. Search strings for C++ RTTI type names,
   `Steinberg` and `juce`. The VST3 layer may be JUCE wrapping a UA framework
   shared with AU/AAX; follow it inward to the DSP classes.
2. **Parameter flow.** The 26 host parameters are already listed (F-007,
   `analysis/out/params_uaudio-lexicon-224.json`). For each: find where the
   processor reads it and what it changes. Map ID → name → range → reader →
   effect. Test each effect with `--vary`.
3. **Audio path.** Find where the sample rate and block size arrive, where delay
   lines are allocated (sizes reveal delay lengths and how they scale with
   sample rate), and the per-sample loop: filters, modulation, feedback.
4. **Algorithm structure.** Build a signal-flow description from code, constants
   and render measurements. Every inference stays a Hypothesis until a render
   checks it.
5. **Variants and programs.** How the 9 programs differ: tables in the code,
   compared with `--vary program=all` renders.

## Evidence standards

Every finding is exactly one of:
- **Confirmed**: directly shown by inspection or a reproducible test.
- **Hypothesis**: plausible, not yet verified.
- **Unknown**: not enough evidence.

Each finding records: function name; address (Ghidra address in the arm64
slice) or render command; the evidence ID or saved output path; the relevant
strings, constants, or xrefs; and how to confirm it.

- One suggestive string is not evidence of a language, framework, DSP
  algorithm, or source availability.
- Decompiled code is an approximation, not original source.
- Keep each extracted constant separate from what you think it means.
  Record the raw hex and the decoded value. Decode with a command, not in
  your head:
  `python3 -c "import struct; print(struct.unpack('>f', bytes.fromhex('3f800000'))[0])"`
  prints 1.0. For a double, use `'>d'` and 16 hex digits. (This one-liner does
  not load the plugin, so plain `python3` is fine here.)

Example `FINDINGS.md` entry:

```
### F-012 One-pole filter on reverb input (Hypothesis)
- Where: FUN_0001a2c4, arm64 slice (SHA-256 in TARGET.md)
- Evidence: procedure_pseudo_code -> analysis/out/FUN_0001a2c4.c, lines 40-58
- Constant (extracted): 0x3f7b7e91 = 0.9824
- Meaning (inferred): feedback coefficient of a one-pole filter.
  If a = exp(-2*pi*fc/fs) at 48 kHz, fc is about 136 Hz. Sample rate not confirmed.
- To confirm: render impulses at 44.1/48/96 kHz in deterministic mode;
  compare the low-band level and T30 from analyze.py ir.
```

## Report at the end of each step

In `LOG.md` and in your reply:
- the tool calls and renders you made, with evidence IDs or output paths
- new Confirmed / Hypothesis / Unknown items, by FINDINGS ID
- what is still open
- the Next step
