# Analysis log

## Session 0 (2026-11-01, Claude Code): render tooling set up

Done:
- Created `.venv` on Homebrew Python 3.15.2 with pedalboard, numpy, scipy, soundfile,
  matplotlib (pinned in `analysis/tools/requirements.txt`).
- Wrote `analysis/tools/render.py` (headless VST3/AU renderer) and `analysis/tools/analyze.py`
  (IR, peaks, modulation, compare, spectrogram). Tested on the installed plugin.
- Findings F-001 to F-007 come from those tests.

Errors and protection notes:
- Loading the plugin from Apple's Python (/usr/bin/python3 -> Xcode python3.9) kills the
  process: EXC_GUARD / GUARD_TYPE_MACH_PORT, SET_EXCEPTION_BEHAVIOR, raised in
  `libpacefusion_shared.dylib` (PACE) calling `task_set_exception_ports` during dyld
  initialisers. Category: environment limitation, not a tool bug. Fix: use Homebrew Python
  (the project venv). The tools refuse to start under Apple Python.
- Bundle contains `Resources/__Pace_Eden` (PACE anti-tamper). Expect obfuscated regions in
  static analysis. Do not attach debuggers or Frida to the plugin.

Open questions: see F-002 (modulation source), F-005 (mix vs wet_solo), F-006 (predelay).

**Next step:** Step 0 in CLAUDE.md (TARGET.md, arm64 slice, `rea doctor`), then
analysis priority 2 (architecture map from `GetPluginFactory`).
