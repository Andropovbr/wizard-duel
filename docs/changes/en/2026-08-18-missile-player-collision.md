# Change: Missile vs Player collision and a deterministic overscan

## Objective

Implement Round 4 for Wizard Duel: the TIA collision latches detect the
cross-fire hits M0 -> P1 and M1 -> P0, record the hit in a one-byte
`hit_flags` bitfield, deactivate the missile that scored, and clear the
latches so a hit is never counted twice. A hard constraint surfaced during
the work: the current frame occasionally slipped from 262 to 263 scanlines
(the `INTIM` poll read at cycle 4561 instead of <= 4555), so the feature
also had to make frame timing deterministic under worst-case collision load.

## Added

* **Collision detection** (`ProcessCollisions`): reads CXM0P (M0 x P1, D7)
  and CXM1P (M1 x P0, D7), ignores the own-player bits (M0 x P0, M1 x P1),
  sets `hit_flags` (bit 1 = P1 hit, bit 0 = P0 hit; simultaneous hits are
  both recorded) and clears the scoring missile's bit in `m_active`.
  `CXCLR` is written at the end of every frame, so a hit rendered in frame N
  is never counted in frame N+2.
* **Fixed overscan region**: the overscan is now exactly `OVERSCAN_LOOP_COUNT
  = 8` `STA WSYNC` writes (a countdown loop) instead of a `TIM64T` wait, and
  `ProcessCollisions` runs at overscan init. The frame is 262 scanlines by
  construction.
* **Branchless fixed-cost collision pass**: `ProcessCollisions` has no
  branches and a fixed 84-cycle cost. The latches become 0/1 flags via the
  carry (`ASL` + `ADC #0`), `hit_flags = 2*hit0 + hit1`, and the `m_active`
  update is a single 16-byte `newActiveTbl` lookup indexed by
  `m_active + 4*hit0 + 8*hit1` (table placed on a 16-byte boundary so the
  indexed `LDA` never crosses a 256-byte page on the real 6502).
* **Tests**: `tests/test_collision.py` (22 tests) drives the real assembly
  on the emulator with injected latch values; a new regression test in
  `tests/test_frame_timing.py` reproduces the exact max-stress scenario that
  used to slip to 263 scanlines and asserts every frame is 19912 cycles.
* **`newActiveTbl`** (16 bytes ROM) and the `hit_flags` RAM byte (49 total).

## Changed

* `ProcessCollisions` moved from the start of VBLANK to overscan init (the
  deactivation still lands before the next frame's `UpdateMissiles`).
* The overscan `TIM64T = 11` wait was removed and replaced by the WSYNC
  countdown; `OVERSCAN_TIMER_VALUE` became `OVERSCAN_LOOP_COUNT`.
* Benchmark metric `overscan_timer` renamed to `overscan_loop`;
  `docs/benchmarks/history.csv` column migrated (historical rows blanked:
  the old values were timer values, not loop counts, and are not
  comparable).
* Docs updated (EN + pt-BR): timing, architecture, memory map, benchmark.

## Technical Reasoning

### Why the collision pass cannot live in VBLANK

The VBLANK region is held at exactly 57 lines by a `TIM64T` wait whose
expiry sits at a fixed cycle (~frame_start + 4555). The timer wait only
holds the boundary while the pre-wait work finishes before the expiry;
otherwise the `STA WSYNC` after the poll lands one full line late. With the
collision pass in VBLANK the heaviest frame (both missiles hit, both fire
edges, both missiles re-spawn) occasionally pushed the work past the expiry
(measured: `INTIM` first read at cycle 4561 on the slipping frames), and the
VBLANK-end WSYNC aligned to 4636 instead of 4560 -> 263 scanlines. Under the
max-stress input (both latches asserted every frame + alternating fire) the
slip rate was ~1% (2/300 frames).

### Why the overscan cannot use a `TIM64T` wait either

A timer wait is only deterministic when the work before arming the timer is
fixed. The RIOT timer has 64-cycle granularity and `INTIM < 64` can exit up
to 63 cycles before the nominal expiry, so with a variable-cost collision
pass (34..66 cycles) the overscan region landed on different 76-cycle
boundaries and the frame varied between 261/262/263 lines depending on the
collision path taken.

### Why the collision pass is branchless and table-driven

The fix required a fixed-cost collision routine so the WSYNC-counted
overscan (whose loop count depends only on the first write's position) is
exact. The emulator (and, importantly, real-hardware timing) cannot apply a
dynamic mask with `AND` (only `AND #imm` is used, and self-modifying code
would break the emulator's ROM-write guard), so the `m_active` update is
performed as one indexed table lookup instead of `AND #mask`. The table
index packs the current active-mask bits (bits 0-1) and the two hit flags
(bits 2-3). A padded-branch variant was rejected: the four path costs
(34/49/51/66) differ by odd numbers, so `NOP` padding cannot equalize them
without contorting the logic.

### Overscan alignment math (verified against the emulator)

From the kernel's last WSYNC: epilogue 30 + JSR 6 + collision body 84 + RTS
6 + `LDX` 2 + first WSYNC write 3 = cycle 131 of the region. That lands
inside scanline 2 (76 < 131 <= 152), so `OVERSCAN_LOOP_COUNT = 8` covers
lines 2..9 (152..684) and the `JMP` + VSYNC preamble align the next frame's
first VSYNC WSYNC to exactly 760. Any fixed body in (21, 97] cycles is safe
for this loop count.

## Rejected approaches

* VBLANK trimming (reading `SWCHA` once instead of four times saves 12
  cycles/frame) left only ~1 cycle of margin on the heaviest frame - too
  fragile.
* Timer sweep on the overscan value (9..14): no value yields a uniform 262
  with variable-cost collision work.
* Self-modifying code to apply the deactivation mask: blocked by the
  emulator's ROM-write guard.
* Padded branch version: path costs differ by odd cycle counts, impossible
  to equalize with `NOP`s.

## Timing Impact

Before (collision in VBLANK, branch version):
- Frame: 262 scanlines with ~1% of max-stress frames slipping to 263
- Overscan: `TIM64T = 11` wait, variable pre-timer work (34..66 cycles)
- VBLANK: collision pass pushed the work to the timer-wait boundary

After (fixed overscan, branchless collision):
- Frame: 262 scanlines (19912 cycles) uniformly over 600+ max-stress frames
- Overscan: 8 WSYNC writes + fixed 84-cycle collision pass, exact 760 cycles
- VBLANK: collision removed; the timer wait holds the region at 57 lines
  with margin

## Memory Impact

Before:
- ROM: 1296 (metric); 1049 honest code bytes vs origin/main baseline
- RAM: 48

After:
- ROM: 1296 (metric, unchanged - the `ALIGN 256` before `fineAdjustBegin`
  absorbs the growth); 1127 honest code bytes (+78)
- RAM: 49 (+1: `hit_flags`)

## Tests

* `tests/test_collision.py`: 22 tests (M0->P1, M1->P0, own-player ignored,
  simultaneous hits, latch persistence, one-shot fire across a hit) - PASS.
* `tests/test_frame_timing.py`: new max-stress frame regression (80 frames
  at exactly 19912 cycles) - PASS.
* Full suite: 166 tests - PASS. Benchmark: ROM 1296 / RAM 49 / kernel worst
  65 of 76 (slack 11). Regression vs origin/main: only RAM +1 byte, no
  warnings, PASS.

## Known Limitations

* The emulator does not model 6502 page-crossing cycle penalties, so the
  `ALIGN 16` on `newActiveTbl` is a hardware-only guarantee (the emulator
  would accept a page-crossing table; real silicon would add one cycle and
  break the fixed cost).
* `hit_flags` is observable but no HP/damage/scoring uses it yet.
* `M0_HIT_P1` / `M1_HIT_P0` constants remain in `constants.inc` as hardware
  documentation but are no longer referenced by the branchless routine.
* The VBLANK timer (69) is now effectively a fallback: the VBLANK work no
  longer approaches its expiry since the collision pass moved out.
* `docs/benchmarks/baseline.json` still carries the historical
  `overscan_timer: 37` field (informational only; the regression tool only
  compares ROM/RAM/kernel/scanlines).

## Next Logical Steps

* Ball vs player / ball vs missile collision (the ball currently passes
  through everything).
* Using `hit_flags` for HP, scoring or a round/game-over transition.
* A VBLANK workload measurement so future VBLANK additions stay within the
  timer window by construction.