# Change: ENABL timing fix (ball vertical displacement)

## Objective

Fix the Round 2 visual defect in which the TIA Ball was vertically displaced
by roughly one scanline in certain horizontal regions of the screen, while
keeping the ball's fluid 1 px/frame motion and the 262-scanline frame
completely intact. A secondary goal: recover the kernel timing slack that had
been reduced to 2 cycles and remove the remaining data-dependent timing from
the display path.

## Root cause

The old kernel wrote `ENABL` late in the scanline (~cycle 67, and anywhere
from ~cycle 55 to 68 depending on which player sprite paths were taken). The
project previously assumed `ENABL` is latched for the following scanline, but
the TIA samples the ball enable bit **at the ball's horizontal position**
("This graphics bit is scanned (outputted) only when triggered by its
corresponding position counter" - Stella Programmer's Guide; writes to `ENABL`
take "immediate effects" - Andrew Towers' TIA notes). Consequently, whether a
given scanline drew the ball with the current or the previous line's enable
value depended on `ball_x` relative to the beam position at the moment of the
write. Because that write cycle varied with the player paths, the ball jumped
one scanline in some horizontal regions and its 4x4 shape became ragged.

The players were unaffected for two reasons: their graphics are written well
before the beam reaches their fixed horizontal position (P0 at x=16 is
reached at ~cycle 28.3 while `GRP0` is written at ~cycle 25; P1 at x=136 at
~cycle 68 while `GRP1` is written at ~cycle 49), and their X is constant, so
the "before or after the beam" test never changes for them.

### Rejected approach: VDELBL

Using `VDELBL` was analyzed and rejected. With `VDELBL = 1` the ball output
uses the "old" `ENABL` register, which is reloaded from "new" on every
`GRP1` write. Since `GRP1` is written mid-scanline, the "old" register still
changes in the middle of the line, so the ball output would remain dependent
on `ball_x` (the transition merely moves to the `GRP1` write point). `VDELBL`
does not make the ball render time-independent and is therefore not used.

## Fix

The kernel now writes `ENABL` during the horizontal blanking of every
scanline: `STA ENABL` immediately follows `STA WSYNC` and completes at
~cycle 5, far before the first visible pixel (~cycle 22.7). The enable value
is **precomputed in the tail of the previous scanline** for the current line
and carried in `A` across the loop back-edge, so no RAM byte is needed. The
ball therefore draws on exactly `BALL_HEIGHT` consecutive lines regardless of
`ball_x`.

This forced one structural change: with `ENABL` leading the scanline, a
table-driven player (indexed `LDA` + `JMP`, 23 cycles) could no longer write
`GRP0` before the beam reaches x=16 with a safe margin. Both players are
solid rectangles in Round 2, so they are now rendered as branchless constant
rectangles (18 cycles each) using the new `PADDLE_BITS` constant.

## Added

- `PADDLE_BITS = %00111100` constant (`src/constants.inc`); the kernel uses
  `AND #PADDLE_BITS` after the `LDA #0 / SBC #0` draw/blank test.
- Explicit `LDA #0 / STA ENABL` during overscan init, so the register can
  never hold 1 into overscan even when the ball rests at the bottom of the
  arena.
- `BALL_ENABLE = $FF` (the value the `LDA #0 / SBC #0` trick produces; only
  bit 0 matters to the TIA).
- Kernel comment block documenting the corrected `ENABL` timing, the
  branchless accounting and the per-object write deadlines.

## Changed

- `KernelLoop`: `STA ENABL` right after `STA WSYNC`; both players rendered as
  branchless rectangles; tail precomputes the next line's ball enable.
- Tests rewritten for the branchless kernel (see Tests).
- Documentation updated in EN and PT-BR: `timing.md`, `architecture.md`,
  `memory-map.md`, `benchmarks.md`, `latest.md`, `history.csv`.

## Removed

- `P0Sprite`/`P1Sprite` tables (24 bytes of identical rows). The row pattern
  is now the `PADDLE_BITS` constant. The tables were removed because the
  indexed-`LDA` rendering path cannot fit after the `ENABL` write that must
  lead the scanline; since both rows are identical solid bars, a table held
  no information.
- The incorrect "ENABL is latched for the following line" comment.

## Technical Reasoning

- **Scanline budget**: the branchless kernel costs 62 cycles on every
  scanline (WSYNC 3 + ENABL 3 + P0 18 + P1 18 + tail 20), leaving 14 cycles
  of slack (was 2). All eight historical player/ball path combinations now
  cost the same 62 cycles, and the automated walker asserts there is no
  forward conditional branch left in the kernel body.
- **Object write deadlines**: `ENABL` completes at ~cycle 5 (first visible
  pixel at ~cycle 22.7), `GRP0` at ~cycle 23 (P0 beam position at ~cycle
  28.3), `GRP1` at ~cycle 41 (P1 beam position at ~cycle 68). Every write
  happens before its object's horizontal position.
- **Display convention preserved**: the ball still shows on scanlines
  `ball_y + 1 .. ball_y + BALL_HEIGHT`. Line 0 stores the `A = 0` left over
  from the pre-kernel, so the first visible line is always ball-free.
- **No RAM added**: the enable value lives in `A`, not in a variable.
- **ROM unchanged**: removing the tables and shortening the kernel freed
  bytes inside the page padding reserved for the page-aligned
  `fineAdjustBegin`, so ROM usage stays at 528 bytes.

## Timing Impact

Before:
- Frame scanlines: 262
- Kernel worst/best: 74 / 61 cycles (slack 2)
- `GRP0`/`GRP1`/`ENABL` at ~cycle 26 / 49 / 67

After:
- Frame scanlines: 262 (unchanged)
- Kernel worst/best: 62 / 62 cycles (branchless; slack **14**)
- `ENABL` at ~cycle 5, `GRP0` at ~cycle 23, `GRP1` at ~cycle 41

## Memory Impact

Before:
- ROM: 528 bytes
- RAM: 7 bytes

After:
- ROM: 528 bytes (unchanged; freed bytes absorbed by page padding)
- RAM: 7 bytes (unchanged; the enable value is carried in `A`)

## Tests

- `tests/test_timing.py`: cycle walker simplified for the branchless kernel;
  every path asserted at 62 cycles; new assertion that the kernel body
  contains no forward conditional branches.
- `tests/test_ball.py`: `BALL_ENABLE = $FF`; ENABL written exactly once per
  scanline in the loop body; new relative-write-order test (`ENABL` must
  immediately follow `STA WSYNC`, then `GRP0`, then `GRP1`); new regression
  test asserting the kernel never references `ball_x` (the vertical span is
  identical at every horizontal position); overscan-init ENABL clear is
  asserted structurally (`A9 00 85 1F` in the overscan region); the "last
  line must write ENABL=0 by construction" test was replaced by the
  explicit-clear invariant.
- `tests/test_rom.py`: sprite-table tests removed (tables no longer exist);
  added `PADDLE_BITS` constant check and "two `AND #PADDLE_BITS` in the
  kernel" structural check.
- `tests/test_regression.py`: expected slack updated to 14.
- Full suite: **107 tests pass**; quality gates pass (ROM 528/4096,
  RAM 7/128, 262 scanlines, worst 62/76, slack 14). Benchmark and regression
  rerun green (regression shows two soft warnings vs the Round 1 baseline:
  kernel worst +6 and slack -6, both expected; the worst case actually
  improved from the Round 2 committed value of 74).

## Known Limitations

- Players are constant rectangles: arbitrary per-row sprite art is not
  possible without reintroducing graphics tables and a kernel layout that
  still writes `GRP0` in time after the `ENABL` write.
- Runtime scanline/visual validation remains a manual Stella step (no
  documented headless frame-stat mode); the static suite is the CI-safe
  substitute.

## Next Logical Steps

- Ball vs. paddle collision detection can now use the collision latches
  (`CXBLPF` etc.) against a deterministic kernel.
- Re-verify the frozen-ball rendering sweep on the target/Stella to confirm
  the vertical displacement is gone for every `ball_x`.
