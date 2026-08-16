# Change: Validation infrastructure hardening

Date: 2026-08-16
Branch: `round-1-initial-kernel`
Commit: `d488448`

## Objective

Strengthen the Round 1 validation infrastructure without touching gameplay:
fix an invalid DASM availability check, describe Stella validation accurately,
add kernel slack as a first-class metric, and implement a baseline-based
regression comparison with centralized thresholds, plus tests, CI changes and
bilingual documentation.

## Added

- `tools/check_env.py`: cross-platform verification that `dasm` and `stella`
  are installed **and** behave like the real tool.
- `tools/regression.py`: baseline resolution + hard/soft regression
  comparison with a developer-facing report (text + optional JSON), exit 1
  on hard regressions, 0 otherwise.
- `docs/en/benchmarks.md` and `docs/pt-BR/benchmarks.md`: metrics, baseline
  strategy, thresholds, kernel slack and how to read the CI report.
- `docs/benchmarks/baseline.json`: the persisted Round 1 regression baseline
  (ROM 528 B, RAM 3 B, 262 scanlines, kernel worst 56/76, slack 20, best 44).
- `tests/test_regression.py`: delta math, warning thresholds, hard
  regressions, kernel slack, history migration and baseline resolution.
- `stella_rominfo()` helper in `tools/common.py` that retries `-rominfo`
  through `xvfb-run` on headless Linux.
- `python tools/benchmark.py --json` (machine-readable metrics for building
  the base branch during regression) and `--update-baseline`.

## Changed

- `tools/common.py`: `tool()` now runs a deterministic functional probe;
  `probe_dasm()`/`probe_stella()` reject missing or wrong executables.
- `tools/build.py` and `tools/run.py`: use the new probes.
- `tools/benchmark.py`: records `kernel_slack`, migrates `history.csv` in
  place (adds the `kernel_slack` column, computing `slack = budget - worst`;
  the original Round 1 row becomes 20), and manages `baseline.json`.
- `tests/test_build.py`: the Stella test now uses `stella_rominfo()`
  (xvfb-aware) and new DASM/Stella probe tests were added.
- `.github/workflows/ci.yml`: `fetch-depth: 0`, installs `xvfb`, fetches the
  base branch on PRs, verifies tools with `check_env.py`, runs the regression
  comparison, publishes the report to the job summary and as an artifact.
- `docs/en/{build,timing}.md` and `docs/pt-BR/{build,timing}.md`: accurate
  descriptions of what `-rominfo` does and does not validate, the scanline
  validation status, and the new commands.

## Removed

- The CI step `dasm --version` (invalid; see below).
- The claim that `stella -rominfo` runs "headless" without qualification
  (it initializes SDL and needs a video device).

## Why `dasm --version` was wrong, and the fix

DASM has no `--version` or `-h` option. Running `dasm --version` makes DASM
treat `--version` as a source file, fail to open it, print
`Warning: Unable to open '--version'`, and exit **0** ("Complete"). A
verification that only looks at the exit code therefore passes even when
DASM is broken, and the message is actively misleading.

The replacement probe runs `dasm` with no arguments. DASM's documented
behavior (user guide) is to print its short help text (`Usage: dasm
sourcefile [options]`, which also contains the version banner `DASM
2.20.14.1`) and exit non-zero. The check verifies the output contains the
usage text, i.e. the executable really is a working DASM, not just a file
named `dasm` on PATH. `stella -help` is used the same way for Stella (it is a
real option and works without a display).

## Validating ROM metadata vs executing the ROM

`stella -rominfo <rom>` reads the ROM properties and reports bankswitch type
(`4K`), display format (`NTSC`) and detected controllers. It is valuable but
metadata-only: the cartridge is never executed, so nothing about runtime
frame length, scanline stability or gameplay is checked. Worse, in Stella 6.6
`-rominfo` initializes SDL and fails with "Couldn't initialize SDL" when no
video device exists, so on CI it must run under `xvfb-run`. The tooling now
does this transparently.

## Real limitations of Stella runtime validation

Stella 6.6 has no documented headless option that advances frames and prints
the TIA scanline counter to stdout. The debugger and the Alt-L frame-stats
overlay require a graphical session and interactive input; driving them with
keystroke automation is fragile and deliberately not used in CI. Therefore:

- the exact 262-scanline frame was measured **manually** in the Stella
  debugger on a local session (`print _cyclesLo` deltas of 19912 cycles);
- CI validates the frame structure **statically** (constants, listing,
  region scanline sum == 262, kernel cycle budget).

The project does not claim scanlines were validated at runtime by CI; that
limit is documented explicitly in both languages.

## Why in-limit regressions still matter

A ROM that grows from 528 to 700 bytes still fits in 4 KiB, but it is
meaningful: it shows where code is going and can warn about approaching the
ceiling before a future change breaks the build. The same applies to RAM and
kernel cycles. So the pipeline distinguishes **hard regressions** (hardware
limits violated; CI fails) from **soft regressions** (growth within limits;
reported as warnings with centralized thresholds: ROM +32 B or +5%, RAM +4 B,
kernel worst +4 cycles, slack -4 cycles). Warnings do not fail CI, but they
make every meaningful change visible instead of letting accumulated growth
hide.

## How the baseline is chosen

Prefer the **base branch**, built in a temporary git worktree with the base's
own tooling (requires `fetch-depth: 0` in CI); on PRs the base branch is
`GITHUB_BASE_REF`. When the base cannot be built (e.g. it predates the
tooling, as `main` does before this round), fall back to the base's committed
`baseline.json`, then to the local persisted `docs/benchmarks/baseline.json`,
and finally report "no baseline" without failing. The comparison never uses
the branch's most recent `history.csv` row, because that is the branch's own
latest run and could hide regressions accumulated over several commits. For
this round, `main` cannot be built yet, so the persisted Round 1
`baseline.json` (baseline == current) is used; it is the first baseline the
project records.

## Why kernel slack is a first-class metric

An NTSC scanline is 76 CPU cycles; the kernel's worst path (both players
drawn) costs 56, leaving **20 cycles of slack**. Slack is the safety margin
for future gameplay work inside the visible kernel, and on this platform
timing correctness is a requirement, not a preference. Recording slack
(`kernel_budget - kernel_worst`) in the benchmark, history, baseline and
regression report makes a reduction visible immediately as a performance
regression, even when the frame still renders.

## Timing impact

Before:
- Frame scanlines: 262
- Kernel worst/best: 56 / 44 cycles

After:
- Frame scanlines: 262 (no gameplay or timing changes; tooling only)
- Kernel worst/best: 56 / 44 cycles
- Kernel slack: 20 cycles (now recorded)

## Memory impact

Before:
- ROM: 528 bytes
- RAM: 3 bytes

After:
- ROM: 528 bytes (tooling/docs only; ROM unchanged)
- RAM: 3 bytes

## Tests

Added `tests/test_regression.py` (deltas, formatting, thresholds, hard
regressions, kernel slack, history migration, baseline resolution). Extended
`tests/test_build.py` with DASM/Stella probe tests and the xvfb-aware ROM
metadata test. Updated `tests/test_docs.py` for the new benchmarks doc pair.
Full suite result: all pass (see report).

## Known limitations

- No automated runtime scanline validation; the 262-scanline frame remains a
  manual debugger measurement (documented, not claimed by CI).
- The first baseline is self-referential (baseline == current) because the
  base branch predates the tooling; it becomes meaningful from the next
  change onward.
- Soft-regression thresholds are intentionally conservative and centralized
  in `tools/regression.py`; they may need revisiting as the game grows.

## Next logical steps

- Re-run the Stella debugger measurements after any kernel/VBLANK change and
  record them in the timing docs.
- Revisit thresholds once real gameplay code starts consuming ROM and kernel
  cycles.
- If a future Stella release exposes a stable headless frame/scanline
  interface, add runtime validation to the pipeline and remove the manual
  gap.