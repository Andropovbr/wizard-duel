# Change: VBLANK shake fix (realistic branch timing)

## Objective

Fix a whole-screen frame shake that only appears on real hardware. Round 5's
VBLANK budget was tuned against an emulator that folded every conditional
branch to 2 cycles. On real silicon a taken branch costs 3 cycles (4 across
a page boundary), so the worst-case VBLANK work (~4919 cycles) outran the
T=69 timer expiry (~4553 cycles), `WaitVBlank` stopped polling on the fixed
`INTIM == 0` boundary, and individual frames stretched to 263/264/265
scanlines. The frame visually looked fine in Stella with shortcut timing,
so the bug was invisible until the emulator modeled real branch costs.

## Added

* **Realistic cycle costs in `tools/emu6502.py`**: `execute()` now returns
  extra cycles that `step()` adds back - a taken branch is +1 (another +1 on
  a page crossing) and `LDA abs,Y` is +1 on a page crossing. `step()` was
  also fixed to add the returned cycles **after** `execute()` completes
  (the previous `self.cycles += self.execute(op)` augmented assignment read
  `self.cycles` before the call, silently clobbering WSYNC stalls and the
  new branch costs).
* **VBLANK margin regression test** (`tests/test_frame_timing.py`,
  `test_vblank_never_overruns_with_realistic_branch_timing`): 80 max-stress
  frames (both missiles + both collision latches + alternating fire, HP
  topped up) must all be exactly 19912 cycles = 262 scanlines.
* **VBLANK metrics to the benchmark** (`tools/benchmark.py`): `vblank_work`
  (TIM64T write -> first `LDA INTIM`, worst case, emulated) and
  `vblank_margin` (`(timer - 1) * 64 - vblank_work`), tracked in
  `docs/benchmarks/latest.md` and `history.csv`. The history migrator gained
  the two columns (left empty for pre-Round-6 rows).

## Changed

* `src/constants.inc`: `VBLANK_SCANLINES` 57 -> 64, `KERNEL_SCANLINES`
  192 -> 185, `VBLANK_TIMER_VALUE` 69 -> 77. The timer now expires at
  ~4864 cycles, well past the measured worst-case work of ~4455 cycles
  (margin ~409), so the poll always exits on the fixed timer boundary.
* `src/main.asm`: comments updated to the 3/64/185/10 frame structure
  (VSYNC/VBLANK/KERNEL/OVERSCAN), the TIM64T write and the kernel/overscan
  notes.
* Tests updated to the new constants: `tests/test_timing.py`
  (kernel 192 -> 185, VBLANK 57 -> 64, VBLANK+overscan 67 -> 74) and
  `tests/test_ball.py` (ball bounds now derive from `KERNEL_SCANLINES`
  instead of the hardcoded 192).
* Documentation (EN + PT-BR) updated to the new frame structure and a new
  "Round 6" section documenting the shake root cause and the emulator fix.

## Technical Reasoning

A `TIM64T` wait is only deterministic when the work before it finishes
comfortably before the timer expires. The original bug was a **budget**
error, not a poll error: the emulator undercounted work, so the chosen T
value could not cover the true worst case. Round 6 fixes the budget
(grow VBLANK, shrink the kernel, raise the timer) and makes the model
honest (real branch/page-crossing costs) so the regression is detectable
deterministically. The `vblank_margin` benchmark is the hard gate: a
negative margin means the frame length depends on gameplay input and must
fail CI.

## Timing Impact

Before (emulated with realistic branch timing, worst-case input):
- Frame scanlines: 262/263/264/265 (shake)
- VBLANK worst work: ~4919 cycles (T=69 expiry ~4553, negative margin)

After:
- Frame scanlines: exactly 262, all frames of the max-stress regression
- VBLANK worst work: 4455 cycles
- VBLANK margin: 409 cycles (positive)

## Memory Impact

Before:
- ROM: 1296 bytes
- RAM: 51 bytes

After:
- ROM: 1296 bytes (kernel shrank 7 lines; ROM cost unchanged)
- RAM: 51 bytes

## Tests

Added: `test_vblank_never_overruns_with_realistic_branch_timing`
(80 max-stress frames, all exactly 19912 cycles).
Modified: `tests/test_timing.py` (3 assertions to the new constants),
`tests/test_ball.py` (2 assertions derive from `KERNEL_SCANLINES`).
Executed: `python tools/test.py` - 182 tests, all PASS. Quality gates
(ROM <= 4096, RAM <= 128) PASS.

## Known Limitations

The emulator models the opcodes actually used by the ROM, so the cycle
counts are exact for the executed instructions but the model does not
simulate all 256 opcodes. Pixel-level TIA behavior is still validated via
Stella separately.

## Next Logical Steps

Keep the VBLANK margin regression test alive as gameplay grows; re-run the
benchmark whenever VBLANK work changes and confirm the margin stays
positive. Consider a page-boundary audit of VBLANK code so no future branch
can silently gain a page-crossing cycle on real silicon.