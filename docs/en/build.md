# Wizard Duel - Build and validation

## Prerequisites

* Python 3.8+
* DASM 2.20.x on `PATH`
* Stella 6.x on `PATH` (for `tools/run.py` and the Stella detection test)
* `xvfb` (Linux only) when the Stella metadata check must run without a
  graphical session (e.g. CI)

On Ubuntu/Debian:

```sh
sudo apt-get install dasm stella xvfb
```

## Canonical commands

```sh
python tools/check_env.py         # verify dasm + stella are installed and work
python tools/build.py             # assemble ROM, report ROM usage
python tools/build.py --clean     # remove artifacts, then build
python tools/test.py              # deterministic validation suite
python tools/test.py --build      # rebuild first, then test
python tools/run.py               # run the ROM in Stella
python tools/run.py --debug       # start in the Stella debugger
python tools/benchmark.py         # measure metrics, update docs/benchmarks
python tools/benchmark.py --json  # print metrics as JSON (no persistence)
python tools/regression.py        # compare current metrics against a baseline
```

`tools/common.py` checks that required executables exist **and behave like the
real tool**. A tool found on `PATH` that is not functional is rejected with a
clear error.

### DASM verification

DASM has no `--version` or `-h` option. Running `dasm --version` makes DASM try
to open a file named `--version`; it prints `Warning: Unable to open
'--version'` and exits 0. That exit code is a **false positive** and proves
nothing about DASM.

Instead `tools/common.py` runs `dasm` with no arguments. DASM's documented
behavior in that case is to print its short help text (`Usage: dasm
sourcefile [options]`) and exit non-zero; this is the deterministic probe used
by `check_env.py`, the build and the test suite.

### Stella verification

`stella -help` is a real option that works without a video device and prints
`Stella <version>` plus `Usage: stella ...`. It is used as the Stella probe.

Note that `stella -rominfo` is **different**: it initializes SDL and therefore
requires a video device even though it never opens a window. On headless Linux
`tools/common.py` automatically retries `-rominfo` through `xvfb-run -a` when
no `DISPLAY` is available. CI installs `xvfb` for this reason.

## Output artifacts

`build/` contains:

* `wizard-duel.bin` - 4096-byte ROM (4 KiB, no bankswitching)
* `wizard-duel.lst` - assembler listing
* `wizard-duel.sym` - symbol table
* `regression-report.txt` / `regression-report.json` - regression comparison

These are generated files and are not committed.

## What the test suite covers

* **Build**: ROM exists, exactly 4096 bytes, vectors present and pointing
  into ROM; Stella's `-rominfo` reports `4K`, NTSC and two joysticks.
* **Memory**: ROM usage <= 4096 bytes, RAM usage <= 128 bytes (only 3 used).
* **Assembly**: required symbols exist, `Reset` at `$F000`,
  `fineAdjustBegin` page-aligned, sprite tables 12 bytes and page-safe.
* **Timing**: frame region scanline sum == 262; kernel worst-case path
  recomputed from the listing with a deterministic 6502 cycle walker and
  asserted <= 76 cycles (worst = 56, best = 44).
* **Regression**: delta computation, hard/soft thresholds, kernel slack,
  baseline resolution (see `docs/en/benchmarks.md`).
* **Tool validation**: DASM/Stella probes accept a real tool and reject a
  missing or wrong executable.
* **Docs**: required EN/PT-BR documentation pairs exist.

## What `stella -rominfo` validates

`stella -rominfo <rom>` inspects the ROM **header/properties** and reports
metadata:

* bankswitch type (`4K`)
* display format (`NTSC`)
* detected controllers (joysticks in both ports)
* whether the ROM is recognized

It does **not** execute the game. It cannot validate:

* actual frame length / scanline count at runtime
* frame stability
* TIA/CPU runtime state
* gameplay behavior

## How scanlines are validated

There is currently **no automated runtime scanline validation**. Stella 6.6
has no documented headless option that advances frames and prints the TIA
scanline counter to a stream; the debugger and the frame-stats overlay require
a graphical session and interactive input. Driving that with keystroke
automation is fragile and deliberately not used in CI.

What is validated automatically instead (deterministic, from the build
artifacts):

* frame region scanline sum equals `FRAME_SCANLINES` (262)
* kernel worst-case path fits the 76-cycle budget, recomputed from the
  listing with a cycle walker
* timer values (VBLANK 44, OVERSCAN 37) are the tuned constants

The exact 262-scanline frame was additionally measured in the Stella debugger
on a local graphical session (`print _cyclesLo` deltas of 19912 cycles =
262 scanlines). That measurement is **manual/development-time**, not a CI
check; see `docs/en/timing.md`. The project does not claim that scanlines
were "validated at runtime by CI" - they were measured locally in the
debugger and validated statically in CI.

## Regression comparison

`python tools/regression.py` compares the current metrics against a baseline
and reports hard failures (exit 1) and soft warnings (exit 0). How the
baseline is chosen, the thresholds used and how to read the report are
documented in `docs/en/benchmarks.md`.

## CI

GitHub Actions (`/.github/workflows/ci.yml`) runs on PRs and pushes to
`main`. The checkout uses `fetch-depth: 0` so the regression step can build
the base branch in a temporary git worktree; on PRs the base branch is
fetched explicitly. CI installs `dasm`, `stella` and `xvfb`, verifies tools
with `check_env.py`, builds cleanly, runs the test suite, generates the
benchmark, runs the regression comparison and publishes the report both as a
job summary and as an artifact.

### CI runtime gap

The runtime measurements (exact 262-scanline frame, movement behavior, both
players visible) were performed in the Stella debugger on a local graphical
session. Automating the Stella GUI debugger on CI is not reliable, so CI
validates the frame structure and timing statically and documents the runtime
gap in `docs/en/timing.md`; the deterministic build-analysis tools are the
CI-safe substitute. Stella's `-rominfo` is exercised in CI (under `xvfb`) as
a ROM-metadata check only.