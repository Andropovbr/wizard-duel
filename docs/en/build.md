# Wizard Duel - Build and validation

## Prerequisites

* Python 3.8+
* DASM 2.20.x on `PATH`
* Stella 6.x on `PATH` (for `tools/run.py` and the Stella detection test)

On Ubuntu/Debian:

```sh
sudo apt-get install dasm stella
```

## Canonical commands

```sh
python tools/build.py           # assemble ROM, report ROM usage
python tools/build.py --clean   # remove artifacts, then build
python tools/test.py            # deterministic validation suite
python tools/test.py --build    # rebuild first, then test
python tools/run.py             # run the ROM in Stella
python tools/run.py --debug     # start in the Stella debugger
python tools/benchmark.py       # measure metrics, update docs/benchmarks
```

`tools/common.py` checks that required executables exist and fails with a
clear message if they are missing.

## Output artifacts

`build/` contains:

* `wizard-duel.bin` - 4096-byte ROM (4 KiB, no bankswitching)
* `wizard-duel.lst` - assembler listing
* `wizard-duel.sym` - symbol table

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
* **Docs**: required EN/PT-BR documentation pairs exist.

## CI runtime gap

The runtime measurements (exact 262-scanline frame, movement behavior, both
players visible) were performed in the Stella debugger on a local graphical
session. Automating the Stella GUI debugger on CI is not reliable, so the CI
pipeline validates the frame structure and timing statically and documents
the runtime gap in `docs/en/timing.md`; the deterministic build-analysis
tools are the CI-safe substitute. Stella's `-rominfo` is still exercised
headlessly in CI as a ROM-format check.