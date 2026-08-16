# Change: Initial kernel and player movement (Round 1)

## Objective

Deliver the minimum technical base for Wizard Duel: a stable 262-scanline
NTSC frame, two TIA players visible simultaneously, and vertical-only
movement controlled by both joysticks, together with a reproducible
build/test/CI/docs setup.

## Added

* `src/main.asm` - the complete program: Reset/init, the one-frame loop
  (VSYNC + VBLANK + 192-line kernel + OVERSCAN), joystick reading and
  movement, RESP/HMP positioning, sprite tables and vectors.
* `src/constants.inc` - all TIA/RIOT addresses and build-time constants
  (frame structure, timer values, player geometry, joystick masks).
* `tools/` - cross-platform Python toolchain:
  * `build.py` assembles with DASM and reports ROM usage;
  * `test.py` runs the deterministic validation suite;
  * `run.py` launches Stella;
  * `benchmark.py` measures metrics and persists history;
  * `common.py` shared helpers and dependency checks.
* `tests/` - deterministic suite (ROM format, vectors, symbols, addresses,
  page alignment, memory usage, kernel cycle budget, EN/PT-BR doc pairs).
* `docs/en` and `docs/pt-BR` - architecture, memory map, timing and build
  documentation; `docs/benchmarks/` history.
* `README.md` and the GitHub Actions pipeline.

## Changed

* Corrected the RIOT address constants in `constants.inc`. The I/O
  registers are `SWCHA=$0280`, `SWACNT=$0281`, `SWCHB=$0282`,
  `SWBCNT=$0283`. They were originally mislabelled (`SWCHA=$0281`, etc.),
  which made `LDA SWCHA` read `SWACNT` (a data-direction register that
  returns 0). Every direction bit then appeared "pressed" and the movement
  code produced no visible result. Fixed, rebuilt and re-validated
  end-to-end in the Stella debugger.

## Technical Reasoning

* **Timer tuning**: a naive `TIM64T = value` lasts `value * 64` cycles, but
  the M6532 starts `mySubTimer` at `myDivider - 1` and wraps at
  `(value + 1) * 64`. The timer therefore runs slightly short. Values of 44
  (VBLANK) and 37 (OVERSCAN) were chosen so each wait expires on the
  intended final scanline; measured frame = 19912 cycles = 262 scanlines.
* **Gameplay in VBLANK**: joystick decode and movement are branch-heavy and
  data-dependent; placing them in VBLANK keeps the visible kernel stable at
  one scanline per iteration.
* **Fixed kernel cost**: sprite tables are placed so all 12 row indices
  stay inside one page; the indexed `LDA` never pays a page-cross penalty.
  Worst case is 56 of 76 cycles (20 cycles of slack).
* **Page-aligned `fineAdjustBegin`**: `PosObject` indexes the HMP table with
  a two's-complement remainder; the forced page crossing keeps the `RESPx`
  write on the exact cycle required by the positioning timing contract.

## Timing Impact

Before:
- Frame scanlines: 260 (a shorter VBLANK timer); measured 19760 cycles.
- Kernel worst case: documented 61/76 (recounted as 58 with 4-cycle page
  penalty that cannot actually occur).

After:
- Frame scanlines: 262 exactly; measured 19912 cycles across consecutive
  frames (delta 19912, 19912 via `print _cyclesLo`).
- Kernel worst case: 56/76 cycles (verified from the listing by the test
  suite); best case 44; one-drawn path 50.

## Memory Impact

Before: n/a (first build).
After:
- ROM: 528 bytes used of 4096 (12.9%).
- RAM: 3 bytes used of 128 (P0Y, P1Y, joystate).

## Tests

* Deterministic suite: 37 tests covering build/ROM format, Stella
  `-rominfo`, vectors, symbols, page alignment, memory usage, kernel cycle
  walker and frame region sums - all PASS.
* Runtime validation in the Stella 6.6 debugger (documented, not CI):
  * frame length 262 scanlines via cycle deltas at `StartOfFrame`;
  * both players visible simultaneously (red P0 left, blue P1 right, via
    screenshot pixel analysis);
  * movement with real `SWCHA` input: `joy0Up 0` + `joy1Down 0` moved P0
    48->47 and P1 128->129 and continued across frames; reverse directions
    moved back;
  * clamp behavior verified by poking positions 1/178 and confirming
    0/179 and no wrap.

## Known Limitations

* The exact frame-length/movement runtime checks require the Stella GUI
  debugger, which is not automated on CI. CI relies on the deterministic
  static validation; the gap is documented in the build/timing docs.
* Movement is 1 pixel per frame (no diagonal or horizontal support yet).
* Only 3 variables in RAM; 125 bytes free for later rounds.

## Next Logical Steps

* Add game state beyond positions (e.g., magic, projectiles) without
  touching the kernel timing.
* Extend movement rules or add collision detection in VBLANK/overscan.
* Optionally add a headless runtime frame-length check if Stella exposes a
  stable CLI/driver for it in CI.