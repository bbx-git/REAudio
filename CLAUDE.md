# Project: Audio Plugin Analysis and Clone

## Target: the only line you edit

```
PLUGIN=/Library/Audio/Plug-Ins/VST3/uaudio_lexicon_224.vst3
```

Everything else is derived from this line. The tools (`render.py`) read it too.

| Name | Meaning |
|---|---|
| `<bundle>` | the `PLUGIN=` path (`.vst3` or `.component`) |
| `<exe>` | the Mach-O inside: `<bundle>/Contents/MacOS/<file>` (find it with `ls`) |
| `<name>` | `<bundle>` file name without the extension, e.g. `uaudio_lexicon_224` |
| `<slice>` | `analysis/slices/<name>-arm64` |

## Objective

Understand the plugin's audio processing completely, write a behavioural spec,
and build an **independent C++ clone** that sounds measurably the same.

1. **Measure** the original: renders plus static analysis (REA/Ghidra).
2. **Specify**: `analysis/SPEC.md`, with enough detail to implement from.
3. **Build** the clone in `clone/`.
4. **Debug the clone against the original** with A/B renders until it is within tolerance.

Principles:
- Audio processing comes first. Ignore the UI unless it explains a parameter.
- Original source code cannot be recovered, and that is not the goal.
- Describe behaviour: signal flow, delay lengths, gains, filter coefficients,
  decay, modulation, nonlinearity, sample-rate handling. Never paste decompiled
  code into the spec or the clone. Write the clone from `SPEC.md`.

## Session files: read these first, every session

Everything you write goes under `analysis/` or `clone/`. Do not use /tmp.

| Path | Contents |
|---|---|
| `analysis/TARGET.md` | Bundle path, exe path, version, SHA-256 of `<exe>` and `<slice>`, architectures, protection status, REA status |
| `analysis/FINDINGS.md` | Numbered findings (F-001, ...): Confirmed / Hypothesis / Unknown |
| `analysis/COVERAGE.md` | One row per host parameter: measured / static / in spec / in clone / passes A/B |
| `analysis/SPEC.md` | Behavioural spec for the clone (Phase C) |
| `analysis/LOG.md` | One entry per session: what was done, exact errors, open questions, **Next step** |
| `analysis/slices/` | Single-architecture slices |
| `analysis/out/` | Saved tool output (pseudo-code notes, string lists, analysis JSON, plots) |
| `analysis/audio/renders/` | Rendered WAVs, each with a `.json` sidecar |
| `analysis/tools/` | `render.py`, `analyze.py`: ready to use, see "Audio renders" |
| `analysis/archive/<name>/` | Work on previous targets |
| `clone/` | The C++ clone: source, CMake, build output in `clone/build/` |

At the start of a session:
1. Do the **target check** (below).
2. Read `TARGET.md`, `FINDINGS.md`, `COVERAGE.md`, then the last entry in `LOG.md`.
3. Continue from its **Next step**.

At the end of each step: update `FINDINGS.md` and `COVERAGE.md`, and append to `LOG.md`.

### Target check (every session)

- `TARGET.md` missing: run Phase 0.
- `TARGET.md` names a different bundle than `PLUGIN=`: the user switched target.
  Move `TARGET.md`, `FINDINGS.md`, `COVERAGE.md`, `SPEC.md`, `LOG.md`, `out/`,
  `audio/renders/` and `slices/` into `analysis/archive/<old name>/`. Move
  `clone/` to `analysis/archive/<old name>/clone/`. Then run Phase 0. Do not delete anything.
- Same bundle: re-check only `shasum -a 256 "<exe>"`. If it differs from
  `TARGET.md`, the plugin was updated. Stop and tell the user: old addresses and
  findings may no longer apply.

## Rules

- Never modify, patch, re-sign, move, or overwrite the installed plugin: `<bundle>`,
  its AU/VST3/AAX siblings, or the vendor's content or data folders.
- Write only inside this project directory.
- Ask first before you: install or download anything (including JUCE or the VST3
  SDK), edit any config (opencode, REA, shell, system, the plugin's own settings
  files), delete files outside `analysis/` and `clone/`, kill a process, or
  analyse files outside the target's bundles.
- No licence bypass, ever. Do not investigate licensing, activation, or
  copy-protection code, and do not decrypt, unpack or reverse encrypted
  content or preset files. Measure their effect through renders.
- **Protected targets.** Phase 0 records whether the plugin uses copy protection
  or anti-tamper (PACE/iLok: `__Pace_Eden`, `libpacefusion`, DTCompiler
  `com.paceap...`, licensing exports such as `_g_dwIL*`; or others). If it does:
  - Never attach a debugger, Frida, gdb, lldb, rizin-debug or DTrace to the
    plugin or to any process that loaded it. Static analysis and renders only.
  - Protected or obfuscated code regions: record the address in `LOG.md` and move on.
- **Unprotected targets.** Still no patching. Ask the user once before the first
  dynamic session on the original plugin, and record the approval in `LOG.md`.
- **Your own clone has no limits.** Debug it with lldb, sanitizers, logging,
  probes, unit tests, or any instrumentation you need.
- Never repeat a failing command or tool call unchanged. If two different
  approaches fail on the same problem, stop and report.

## Phase 0: Establish the target

Run these and record the results in `TARGET.md`, including the bundle path
exactly as in `PLUGIN=`. These are macOS (BSD/LLVM) tools: do not use GNU-only
flags. Shell variables do not persist between commands, so write out full,
quoted paths.

| Purpose | Command |
|---|---|
| Executable name, version, compiler | `plutil -p "<bundle>/Contents/Info.plist"` |
| Bundle contents | `ls -la "<bundle>/Contents" "<bundle>/Contents/MacOS" "<bundle>/Contents/Resources"` |
| Manifests (class IDs, parameters, programs) | `cat` any `moduleinfo.json` / `manifest.json` / `.plist` in `Resources` |
| Sibling formats | `ls /Library/Audio/Plug-Ins/Components /Library/Audio/Plug-Ins/VST3 \| grep -i "<name>"` |
| Architectures | `lipo -info "<exe>"` |
| Hash | `shasum -a 256 "<exe>"` |
| Linked libraries | `otool -arch arm64 -L "<exe>"` |
| Exported symbols | `nm -arch arm64 -gU "<exe>"` (count first: `\| wc -l`) |
| Framework hints | `strings -a "<exe>" \| grep -m 20 -iE "juce\|steinberg\|iplug\|dpf"` |
| Signature (read-only) | `codesign -dv --verbose=2 "<bundle>" 2>&1` |
| Protection | from the above: PACE/iLok markers, few exports, encrypted resources. Record Yes/No and the evidence |
| Make the slice | `lipo -thin arm64 "<exe>" -output "<slice>"` (if the exe is already arm64-only, `cp` it) |
| Slice hash | `shasum -a 256 "<slice>"` |
| Parameters | `.venv/bin/python analysis/tools/render.py params` -> creates the rows of `COVERAGE.md` |
| REA providers | `rea doctor` |

Large executables (50 MB or more) make Ghidra auto-analysis slow. Plan for that.

`objdump` on your PATH is Apple's LLVM objdump. GNU objdump is at
`/opt/homebrew/opt/binutils/bin/objdump` and has limited Mach-O/arm64 support.
Prefer otool, LLVM objdump, or REA.

## Phase A: Black-box measurement (renders)

For a protected plugin, renders carry most of the work. Be systematic.

1. **Baseline.** Render the defaults twice and `compare` them. This is the noise
   floor: how much two identical renders differ. Every effect you report must be
   clearly larger than this.
2. **Deterministic mode.** If renders are not repeatable, find which parameters
   cause it (usually modulation or random seeds): set them to minimum or off until
   two renders null below -100 dB. Measure everything else in that mode, then
   measure the modulation separately.
3. **Per-parameter sweep**, one parameter at a time, everything else at default
   (or in deterministic mode). For every row of `COVERAGE.md`:
   - continuous: at least min / 25% / 50% / 75% / max (`raw:0`, `raw:0.25`, ...)
   - stepped or enum: `--vary NAME=all`
   - pick the signal for the effect: impulse (decay, EQ, delays), sine at
     -30/-12/0 dBFS (gain, THD, compression curve), `mod` on a sine (LFO rate
     and depth), sweep (frequency response), burst (envelope, attack/release)
   - write the mapping as a table or formula: raw value -> display value -> measured value
4. **Sample rate.** `--sr 44100,48000,96000`: delays fixed in ms keep their ms;
   delays fixed in samples keep their sample count. Also check filter cutoffs and LFO rates.
5. **Block size.** `--block 64,512,2048` should not change the output. If it does, record it.
6. **Programs and presets.** Render each program; `changed_from_default` in the
   sidecar shows what it sets. Set programs before other parameters (render.py does this).
7. **Interactions.** After the single sweeps, test pairs that plausibly interact
   (for example size × decay, or drive × output).

## Phase B: Static analysis (REA / Ghidra)

Use the code to explain what the renders show: structure, exact constants,
delay tables, coefficient formulas, smoothing, denormal handling, oversampling.

1. **Architecture map.** Start at `_GetPluginFactory` (VST3) or the AU factory
   symbol from `Info.plist`. Find the processor and controller classes (class
   IDs from the manifest). Search strings for RTTI names, framework names,
   parameter names (from `COVERAGE.md`), and resource names. Follow them inward to the DSP.
2. **Parameter flow.** For each parameter: where is it read, and what does it
   change? Map ID -> name -> range -> reader -> effect -> curve.
3. **Audio path.** Find where the sample rate and block size arrive (setup /
   prepare), what is allocated there (buffer lengths = delay lines), and the
   per-block process function: filters, delays, feedback, gain stages, modulators.
4. **Constant tables.** Arrays of floats or ints near the DSP (delay lengths,
   coefficients, LFO tables) are very valuable. Dump them with `read_bytes`,
   decode them with a command, and save them to `analysis/out/`.

## Phase C: Behavioural spec (`analysis/SPEC.md`)

Write it so a developer who has never seen the plugin could implement it.
Structure:

1. Overview: block diagram (signal flow, mono/stereo, wet/dry topology), latency.
2. One section per DSP block in signal order: purpose, inputs/outputs, the
   algorithm in plain words or formulas, every constant with units and its
   finding ID, and sample-rate behaviour.
3. Parameter table: ID, name, range, default, taper/curve formula, smoothing
   time, which blocks it controls.
4. Programs: the parameter values each program sets.
5. Open items: everything still Hypothesis or Unknown, and how it was approximated.

Every spec statement cites a finding ID. If no finding exists, write the
finding first.

## Phase D: Build the clone (`clone/`)

- Framework: ask the user on first entry (default suggestion: JUCE + CMake,
  building VST3 and AU). Downloading a framework needs approval (see Rules).
- Layout: `clone/CMakeLists.txt`, `clone/src/dsp/` (one class per SPEC block,
  no framework dependency), `clone/src/plugin/` (wrapper), `clone/tests/`.
- Use the same parameter names, ranges and defaults as the original, so that
  `render.py --set` and `--vary` work unchanged on both.
- Build: `cmake -S clone -B clone/build -DCMAKE_BUILD_TYPE=Release && cmake --build clone/build`.
  Record the exact command and the output path in `LOG.md`.
- Never install the clone into `/Library/Audio/Plug-Ins`. Render it from
  `clone/build/...` with `--plugin` (use `--settle 0` if it loads instantly).
- Unit-test each DSP block on its own (impulse response, gain, delay length)
  before you test the whole plugin.

## Phase E: Debug the clone against the original (A/B loop)

Repeat until every `COVERAGE.md` row passes:

1. Render the original and the clone with identical signal and settings
   (`--name orig_X` / `--name clone_X`, same `--sr`, `--block`, `--signal`).
2. `analyze.py compare orig.wav clone.wav`; also run `ir`, `peaks` or `mod`,
   depending on the parameter.
3. Find the **largest** deviation. Find its cause (by bisecting: bypass blocks
   in the clone, add debug outputs, probe intermediate signals), fix one
   thing, then rebuild and re-render.
4. Record the result per row in `COVERAGE.md` and per session in `LOG.md`.

Acceptance (default tolerances; tighten them if the noise floor allows):

| Metric | Tolerance |
|---|---|
| Deterministic settings, if the original is deterministic | null below -60 dB, or explain why not |
| T30 / EDT, broadband and per octave | ±5% |
| Band levels per octave | ±0.5 dB |
| Discrete early arrivals (`peaks`) | ±0.5 ms, ±1 dB |
| Echo density, L/R correlation | within the original's run-to-run spread × 2 |
| Modulation rate / depth | ±5% |
| Static gain / THD at -30/-12/0 dBFS | ±0.2 dB / ±3 dB THD |
| Parameter curves | every swept point within the tolerances above |
| Sample rates 44.1 / 48 / 96 kHz | all pass |

**Done** means every parameter row passes at all three sample rates, the
programs pass, and `SPEC.md` has no open items left that are audible.

## REA and Ghidra

Ghidra runs headless inside REA. Tool names below are bare (`open_binary`).
opencode lists them as `rea_<name>`, Claude Code as `mcp__rea__<name>`. Use the
exact name your tool list shows.

Setup is done. Do not change it:
- Never run `ghidraRun` or open the Ghidra GUI.
- Do not set `GHIDRA_INSTALL_DIR` or `JAVA_HOME`. REA's MCP config provides them.
- If REA reports that Ghidra or Java was not found: stop and tell the user.
- Do not touch `~/Library/ghidra/`, or Ghidra installers in `/private/tmp`.

Workflow:
1. `open_binary` with `path` = absolute path of `<slice>`. The parameter is
   `path`, not `input_path`. Never pass a universal binary. Auto-analysis can
   take many minutes. Wait for it.
2. `binary_overview` at most once per session (optional). If it times out or
   turns into a background task, do not call it again and do not guess its result.
3. Never pull a full list into context. Use `search_procedures` / `search_strings`
   with a pattern, or page through `inspect_analysis_view` in small pages.
   `detail: summary` returns counts only; `detail: complete` returns values.
   Save useful results to `analysis/out/`.
4. `procedure_pseudo_code` with a name or address. `xrefs` only with an explicit address.
5. Rename functions you have understood (`set_address_name`) so later sessions benefit.
6. `close_binary` when finished.

Errors:
- `target_unavailable: No app is open`: run `open_binary`, then retry once.
- `main` or `_start` not found: normal for a plugin. Start from the factory export.
- Universal binary rejected: use the slice.
- Anything else: record the exact error text in `LOG.md`, classified as
  install/discovery, import, architecture limitation, or unsupported option.

Process check (no GUI): `ps -Ao pid,lstart,command | grep -i '[g]hidra'`.
`-Djava.awt.headless=true` is REA's worker: leave it alone. `ghidra.GhidraRun`
is a GUI: stop it only with the user's approval.

## Audio renders

Run the tools from the project root with the project venv:

```
.venv/bin/python analysis/tools/render.py  ...
.venv/bin/python analysis/tools/analyze.py ...
```

Never use `python3`, `/usr/bin/python3` or Xcode's Python: copy-protected
plugins (PACE) crash Apple-signed Python on load, and the user gets a crash
dialog. The tools refuse to start there. If `.venv` is broken (for example after
a Homebrew Python upgrade), stop and ask the user. Do not reinstall it yourself.
Do not rewrite the tools. Small fixes are allowed: describe them in `LOG.md`.

`--plugin` defaults to the `PLUGIN=` line. Pass it only for the clone or a sibling format.

### render.py

```
render.py params                                   # list parameters and valid values
render.py render [signal options] [settings]       # render; writes WAV + JSON sidecar
render.py signal --signal sine --out FILE.wav      # write a test signal only
```

Settings:
- `--set NAME=VALUE`, repeatable. VALUE can be a display value (`on`, `"Room A"`),
  a number with or without a unit (`720`, `4.8kHz`; the nearest valid value is
  used), or `raw:0.25` (normalised 0..1).
- `--vary NAME=V1,V2,V3` (or `NAME=all` for up to 128 values): one render per
  value. Several `--vary` flags render every combination.
- `--program NAME`. Parameters named like program/preset/bank/patch are always applied first.

Signal options: `--signal impulse|sine|noise|sweep|burst|silence|file:PATH`,
`--sr 48000` (or a list `44100,48000,96000`), `--level -6` (dBFS), `--dur 2`,
`--freq 1000`, `--tail 8`, `--preroll 0.05`, `--inject both|L|R`.
Other: `--plugin PATH`, `--plugin-name`, `--name BASE`, `--block 512`, `--save-input`,
`--settle auto|0|SECONDS` (auto waits until the output is stable; plugins that
load data in the background output silence until then).

Output: `analysis/audio/renders/<name>.wav` (float32) and `<name>.json`. The
sidecar lists the requested values, the **applied** values as read back from
the plugin, `changed_from_default`, every parameter's final value, the plugin's
SHA-256, `signal.impulse_index` and `settle`. One line per render:

```
analysis/audio/renders/<name>.wav  peak -34.0 dBFS  settled 2.2s  applied {...}
```

`SILENT` or `WARNING: plugin did not settle` means the render is invalid:
record it in `LOG.md` and do not analyse it. If `applied` differs from what you
meant, fix the value.

### analyze.py

All times are relative to the signal start (from the sidecar), in ms and samples.

| Command | Use for |
|---|---|
| `info FILE` | length, peak, RMS, settings |
| `ir FILE [--plot]` | first arrival, peak, EDT/T20/T30 broadband and per octave, band levels, echo density, L/R correlation |
| `peaks FILE [--end-ms 120] [--n 25]` | strongest discrete early arrivals |
| `mod FILE [--plot]` | FM/AM rate and depth of a rendered sine |
| `compare A B` | alignment lag, null test, level difference, per-band T30 table |
| `spectrogram FILE` | PNG spectrogram |

Results are saved to `analysis/out/<name>.<kind>.json` (and `.png`). Quote
these paths as evidence. If you need a measurement that analyze.py lacks (THD,
transfer curve, frequency response from a sweep), write a small script in
`analysis/tools/` and record it in `LOG.md`.

### Test rules

- Compare statistics (T30, band levels, arrival times), not sample values,
  unless the plugin is in deterministic mode.
- Change one parameter per test. Keep everything else identical.
- Keep the wet/dry mix at 100% wet unless you are testing the mix.
- Name the program or preset used in every finding.

## Evidence standards

Every finding is exactly one of:
- **Confirmed**: directly shown by inspection or a reproducible test.
- **Hypothesis**: plausible, not yet verified.
- **Unknown**: not enough evidence.

Each finding records: function name; address (Ghidra address in `<slice>`) or
render command; the evidence path; the relevant strings, constants or xrefs;
and how to confirm it. A constant found in code becomes Confirmed when a render
shows the matching behaviour.

- One suggestive string is not evidence of a language, framework or algorithm.
- Vendor marketing and descriptions of the original hardware are not evidence
  about this binary. Keep them as Hypothesis.
- Decompiled code is an approximation, not original source.
- Keep each extracted constant separate from what you think it means. Record
  the raw hex and the decoded value, and decode with a command:
  `python3 -c "import struct; print(struct.unpack('>f', bytes.fromhex('3f800000'))[0])"`
  (`'>d'` and 16 hex digits for a double; this one-liner does not load the
  plugin, so plain `python3` is fine).

Example:

```
### F-012 One-pole low-pass in the feedback path (Hypothesis)
- Where: FUN_0001a2c4, <slice> (SHA-256 in TARGET.md)
- Evidence: procedure_pseudo_code -> analysis/out/FUN_0001a2c4.notes.md
- Constant (extracted): 0x3f7b7e91 = 0.9824
- Meaning (inferred): a = exp(-2*pi*fc/fs); at 48 kHz, fc is about 136 Hz.
- To confirm: --vary <damping param> with --sr 44100,48000,96000; compare band levels.
```

## Report at the end of each step

In `LOG.md` and in your reply:
- the tool calls and renders you ran, with evidence paths
- new Confirmed / Hypothesis / Unknown items, by FINDINGS ID
- `COVERAGE.md` progress (rows measured / specified / implemented / passing)
- what is still open
- the **Next step**
