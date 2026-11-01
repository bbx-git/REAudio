# Findings: UADx Lexicon 224 (uaudio_lexicon_224, v1.4.16 build 1508)

Executable SHA-256 (universal): 541a002d5e69715c6f9147c039d8746ab6199dcd6071ad12f2801903071c0296
All renders: render.py via pedalboard 0.9.26, Homebrew Python 3.15.2, block 512.

### F-001 Audio is produced in-process on the CPU (Confirmed)
- Evidence: offline renders through the VST3 with pedalboard produce reverb output
  (e.g. `analysis/out/uaudio-lexicon-224__impulse_48k__programRoom-A_mix100.ir.json`).
  `otool -arch arm64 -L` lists no UA driver libraries; Accelerate is linked.
  `Resources/manifest.json` names the bundle "UADx Lexicon 224 Digital Reverb".
- Still open: which code in the binary does the DSP (static analysis).

### F-002 Default settings are not repeatable; depth=0 + mode_enh=off is bit-exact (Confirmed)
- Test: Room A, mix 100, 48 kHz, impulse. Two renders with defaults: null -21 dB,
  correlation 0.996, T30 per band within 1%. With depth=0: null -30 dB.
  With depth=0 and mode_enh=off: files identical (null -287 dB).
- Meaning (inferred): depth and mode_enh drive modulation whose phase or seed is not reset
  between instances. Unknown: random seed or free-running clock.

### F-003 AU and VST3 produce the same audio, offset by 5 samples (Confirmed)
- Test: as F-002, deterministic settings. AU (`uaudio_lexicon_224.component`) vs VST3:
  null -287 dB after aligning; AU output is 5 samples earlier.

### F-004 Selecting a program also changes other parameters (Confirmed)
- Room A sets: bass 1.8 s, mid 1.8 s, treble_decay 4.40 kHz, diffusion 24, pitch 02
  (defaults: 3.0 s, 2.0 s, 6.60 kHz, 28, 01). Read back from the plugin after the change.
- Consequence: always set the program first, then the other parameters (render.py does this).

### F-005 With wet_solo On, mix appears to have no effect (Hypothesis)
- Evidence: mix 0 vs mix 100 (defaults, SmHall A) have energy within 0.1 dB; differences
  match F-002's run-to-run variation. No dry impulse at t0 in either render.
- To confirm: in deterministic mode, render mix 0/50/100 with wet_solo on and off; compare.

### F-006 Earliest wet arrival is earlier than the displayed predelay (Confirmed measurement, meaning Unknown)
- Room A, 48 kHz, predelay displayed "024 ms": first arrival (-40 dB re peak)
  L 7.42 ms (356 samples), R 4.29 ms (206 samples). Strongest peak L 25.54 ms, R 18.44 ms.
- Unknown: what predelay controls (maybe a tap of the main path, not the first arrival).
- To check: vary predelay=24,60,152 in deterministic mode; run `analyze.py peaks`.

### F-007 Parameter list as reported to the host (Confirmed)
- 26 parameters. Full list with valid values: `analysis/out/params_uaudio-lexicon-224.json`.
- Programs: SmHall B, VocPlate, LgHall B, Chamber, PercPlate, SmHall A, Room A, ConstPlate, Chorus.
