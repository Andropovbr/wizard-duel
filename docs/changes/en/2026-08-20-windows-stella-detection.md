# Change: Fix Windows Stella detection for Stella 7.x GUI builds

## Objective

Make `python tools/run.py` (and `python tools/run.py --debug`) work on
Windows 11 with Stella 7.0 on `PATH`. On Windows the tool failed during the
Stella verification step even though `stella` ran fine from the terminal: the
help text appeared on the user's console, then `cmd.exe` reported "The
filename, directory name, or volume label syntax is incorrect" and the probe
raised `FileNotFoundError` for the never-created `stella-help.txt`.

Branch: `fix/windows-stella-detection`.

## Root cause

Two independent problems were stacked in `probe_stella()` /
`_probe_stella_windows_redirect()` in `tools/common.py`:

1. **Broken shell quoting.** The Windows fallback built the command
   `f'""{path}" -help > "{outfile}" 2>&1"'` and ran it with
   `subprocess.run(cmd, shell=True)`. On Windows, `shell=True` passes the
   string through `cmd.exe /c` with its own convoluted quote handling, and
   the `""...""` idiom is not robust across Python versions. On modern
   Python (3.14) the resulting command line is malformed, `cmd.exe` aborts
   with "A sintaxe do nome do arquivo ... está incorreta", the redirection
   file is never created and the probe dies with `FileNotFoundError`.

2. **The redirect could never capture Stella 7.x output anyway.** Stella 7.x
   is a GUI-subsystem executable. Its `-help` path calls
   `AttachConsole(ATTACH_PARENT_PROCESS)` followed by
   `freopen("CONOUT$", "w", stdout)`, which re-points `stdout` at the console
   screen buffer *regardless of the handle the parent supplied*. The help text
   is written straight to the user's terminal (which is exactly what the user
   observed) and can never be captured through a pipe OR a redirect to a file
   while a parent console exists. The previous comment assumed "a real file
   handle makes the CRT fall back to WriteFile" — that assumption does not
   hold for real Stella 7.x, because Stella itself overrides `stdout`; the
   redirect attempt only caused the help text to be printed a second time.

## Solution

`probe_stella()` keeps the native pipe capture (works on Linux/macOS/CI and
for console-subsystem Stella builds). When the capture is empty on Windows,
the fallback no longer uses `cmd.exe`, `shell=True`, redirections or
temporary files. It reuses the exit code of the `-help` run already performed
and inspects the executable itself via `_looks_like_stella()`: the file must
be a genuine Windows PE (`MZ` + `PE\0\0` headers) and its bytes must contain
the distinctive usage markers `Usage: stella` and `Stella version` (the exact
strings `stella -help` would print, embedded as ASCII in the `.rdata`
section). This is deliberately strong enough to reject random executables
that merely share the name `stella.exe`.

## Added

* `tools/common.py` - `_looks_like_stella()`: chunked binary scan verifying
  PE structure (`MZ` magic, `e_lfanew` -> `PE\0\0`) plus the two usage
  markers, so large executables are not loaded entirely into memory.
* `tests/test_build.py` - `TestStellaProbe` additions and
  `TestStellaProbeWindows` (12 new tests): an executable named `stella` that
  is not Stella is rejected; silent exit-0 executables are rejected on POSIX;
  "Stella" without the usage marker is rejected; a realistic help text in a
  path containing spaces is accepted; and the Windows scenario is simulated
  on any platform by mocking `os.name` and `subprocess.run` — empty
  `capture_output` + exit 0 accepted only when the PE contains the markers,
  non-Stella PE rejected, non-PE rejected, non-zero exit rejected, captured
  output accepted without the fallback, `OSError` reported as "could not
  execute", and a `stella.exe` path containing spaces accepted.

## Removed

* `_probe_stella_windows_redirect()`: the `cmd.exe` / `shell=True` redirect
  to a temp file. Removed because it was both broken (quoting) and provably
  ineffective for Stella 7.x GUI builds (CONOUT$ re-points `stdout`; a file
  redirect captures nothing and only reprints the help).
* `_is_pe_executable()`: folded into `_looks_like_stella()`, which performs
  the stronger PE + markers check.

## Technical Reasoning

- The project principle "visual correctness is not proof of hardware
  correctness" applies here by analogy: the previous fallback *appeared* to
  have a plausible mechanism (file handle -> CRT WriteFile) but the real
  Stella source shows `attachConsole()` unconditionally reopens `stdout` on
  CONOUT$, so no redirection can ever capture it. The fix is based on the
  verified Stella 7.0 `src/common/main.cxx` behavior.
- Only native `subprocess` list-form invocation is used (no `shell=True`), so
  quoting of paths with spaces is handled by Python, no shell metacharacters
  are involved, and behavior is consistent across Python 3.8+ and across
  Windows/Linux/macOS.
- The fallback reuses the exit code of the single `-help` run, so no second
  subprocess (and no second console help dump) is needed.
- The strict text check remains the only verdict on Linux/macOS and in CI,
  so those platforms are not weakened at all.

## Timing Impact

None. No game, ROM, kernel or timing code was touched.

Before:
- Frame scanlines: n/a (unchanged)
- Critical path: n/a (unchanged)

After:
- Frame scanlines: 262 (unchanged)
- Critical path: unchanged

## Memory Impact

Before:
- ROM: 1808 bytes used (unchanged)
- RAM: 81 bytes used (unchanged)

After:
- ROM: 1808 bytes used
- RAM: 81 bytes used

No ROM/RAM impact; the change is Python tooling only.

## Tests

Ran:

```sh
python3 tools/check_env.py          # real dasm + stella probes pass
python3 tools/build.py              # ROM builds, 1808 bytes used
python3 tools/test.py               # full suite
```

Results:
- `tools/test.py`: 261 tests, all OK (12 new Stella probe tests included).
- `tools/check_env.py`: "Tool availability OK: dasm, stella".

## Known Limitations

- On Windows with a GUI Stella and a parent console, `stella -help` prints
  the help text to the user's terminal as a side effect of the probe (it is
  Stella that writes to CONOUT$; there is no way to suppress it without a
  console-less parent). The probe now performs a single run, so the help is
  printed once.
- `stella -rominfo` output has the same CONOUT$ limitation on Windows, so the
  `-rominfo` ROM metadata checks remain CI/Linux-only. This is pre-existing
  behavior and was not changed.
- The Windows fallback validates "genuine Stella" via PE structure + markers
  + exit code rather than captured text; this is inherent to the CONOUT$
  behavior and documented in `tools/common.py`.

## Next Logical Steps

- Run `python tools/run.py` and `python tools/run.py --debug` on a real
  Windows 11 machine with Stella 7.0 to confirm the end-to-end flow.
- If desired, exercise `stella -rominfo` on Windows (e.g. under a
  console-less launch) to decide whether the ROM metadata tests can run there
  too.