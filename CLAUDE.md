# Project: Audio Plugin Analysis

## Objective

Investigate and debug the audio plugin below using REA.

The long-term goal is to understand its architecture and audio
processing algorithms well enough to guide an independent C++
implementation with comparable audio behaviour.

Prioritize understanding the audio processing over recreating the UI.
Do not assume that recovering original source code is possible.

## Target

Plugin bundle:
/Library/Audio/Plug-Ins/VST3/uaudio_lexicon_224.vst3

Environment: macOS

Treat earlier findings about other plugins as unrelated unless
verified against this exact target.

## Operating Rules

- Use REA as the primary analysis interface.
- Prefer read-only inspection.
- Do not modify, patch, re-sign, or overwrite the installed plugin.
- Put extracted binaries, scripts, and analysis outputs in the project
  workspace or a temporary directory.
- Do not change system configuration, install dependencies, or run
  potentially destructive commands without asking first.
- Do not investigate license bypasses or disable protection mechanisms.
  Note such mechanisms only when they affect analysis or debugging.

## Establish the Target First

Before deep analysis:

1. Identify the actual executable inside the plugin bundle.
2. Record its path, version if available, file hash, and architectures.
3. Confirm which architecture REA is analysing.
4. Check which REA analysis providers are actually available.

Do not repeatedly redo these checks unless the target changes.

## macOS Tooling

Use commands compatible with the installed macOS tools.
Do not assume GNU/Linux command flags are supported.

GNU binutils is installed at:
/opt/homebrew/opt/binutils/bin/

When GNU objdump is appropriate, use:
/opt/homebrew/opt/binutils/bin/objdump

Choose flags for the actual task. Do not automatically append `-i`
to every objdump command.

Do not assume GNU objdump supports every feature of the target
Mach-O binary. Use Apple/LLVM tooling or REA when appropriate.

## REA and Ghidra (use exactly this)

Verified on this Mac, 2026-11-01. Ghidra 12.1.4 is used headless by REA.

Rules:
- Never run `ghidraRun`. It has no `--version` flag and opens the Ghidra GUI.
- Never open the Ghidra GUI. REA runs Ghidra headless in a temp project.
- Do not touch `~/Library/ghidra/ghidra_12.1.4_PUBLIC`.
- Do not delete `/private/tmp/ghidra_12.1.4.zip` or `/private/tmp/ghidra-12.1.4.rb` without asking.

Setup is already done. Do not export or edit these variables yourself:
- The REA MCP server gets `GHIDRA_INSTALL_DIR=/opt/homebrew/opt/ghidra/libexec`
  and `JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home`
  from its own config (`~/.config/opencode/opencode.jsonc` and `~/.claude.json`).
- If REA reports that Ghidra or Java is not found, stop and tell the user.
  Do not try to fix the environment.

Tool names depend on the client. Claude Code shows them as
`mcp__rea__<name>`. opencode may show them as `rea_<name>` or `rea.<name>`.
Use the name your client lists for the REA server.
If your client has a ToolSearch tool, load the REA tools first. Otherwise call them
directly by name. Names used below: open_binary, binary_overview,
list_procedures, inspect_analysis_view, search_procedures, search_strings,
procedure_pseudo_code, xrefs, close_binary.

Workflow, in order:
1. Analyse a single-architecture slice of the target, not the universal
   bundle binary. On Apple Silicon, use the arm64 slice. Store slices in
   `analysis/slices/`. Record each slice's SHA-256 and confirm it matches
   `lipo -thin <arch>` of the installed executable.
2. `mcp__rea__open_binary` takes the parameter `path`, not `input_path`.
   Use an absolute path. Ghidra auto-analysis takes about 2 minutes.
3. `mcp__rea__binary_overview` can exceed 120 s and move to a background task.
   Wait for the task result. Do not call it again.
4. Large results (more than 10 MiB, such as `list_procedures`) must be paged.
   Use `mcp__rea__inspect_analysis_view` on the returned evidence,
   or narrow with `search_procedures` / `search_strings`.
   `detail: summary` returns counts only. Use `detail: complete` for values.
5. Decompile with `mcp__rea__procedure_pseudo_code` using a name or address.
   Use `mcp__rea__xrefs` only with an explicit address.
6. Call `mcp__rea__close_binary` when finished.

Errors:
- `target_unavailable: No app is open` means `open_binary` has not run yet.
  Run it, then retry once.
- `main` or `_start` not found is normal for stripped binaries.
- Do not repeat an unchanged failing call. Record the exact error text.

Process check, without a GUI:
- `ps -Ao pid,lstart,command | grep -i ghidra`
- The headless REA worker has `-Djava.awt.headless=true`. Leave it alone.
- A GUI window has `ghidra.GhidraRun`. Stop it only with the user's approval.

Install check, without a GUI: `rea doctor`, `ls /opt/homebrew/opt/ghidra`, or `brew info ghidra`.

If an operation fails:
- Record the exact error.
- Distinguish installation/discovery failures from import failures,
  architecture limitations, and unsupported tool options.
- Do not claim a tool is unavailable merely because one call failed.
- Do not repeatedly retry the same failing operation unchanged.

If REA's provider rejects a universal Mach-O binary, extract an
appropriate single-architecture slice into the workspace and retry.
Leave the original bundle unchanged.

## Evidence Standards

Separate findings into:
- Confirmed: directly supported by inspection or reproducible tests.
- Hypothesis: plausible but not yet verified.
- Unknown: insufficient evidence.

For important findings, record supporting evidence such as:
- Tool output or a saved output path.
- Symbol/function name.
- Address or offset, with the architecture and analysis context.
- Relevant strings, metadata, or cross-references.
- Reproducible audio test results.

Do not infer a programming language, framework, DSP algorithm,
or source-code availability from a single suggestive string.

Treat decompiled code as an approximation, not recovered original source.
Clearly distinguish extracted constants from inferred meanings.

## Analysis Priorities

Work in this order unless evidence suggests a better next step.

1. Architecture map: binary layout, classes, entry points, the plugin
   factory, and the processor/controller split.
2. Parameter flow: find the parameter table and where each parameter is
   read. Trace the reads into the audio callback.
3. Audio path: find the process/render function. Record buffer and
   sample-rate handling, allocation sizes, filters, modulation, and
   feedback paths.
4. Algorithm structure: from the code and constants, infer the structure.
   Keep every inference as a Hypothesis until a reproducible audio test
   checks it.
5. Variants and presets: compare any built-in programs or modes in the code.

For each step, report:
- the tool calls and their evidence IDs
- Confirmed, Hypothesis and Unknown items, each with address and architecture
- what is still open
