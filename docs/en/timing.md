# Wizard Duel - Timing

This document records the cycle-level timing analysis of the Round 2 kernel
and frame. Every number below was either derived by hand and then verified
against the assembled listing by the automated test suite, or measured in
Stella's debugger.

## Frame structure (NTSC)

| Region    | Scanlines | How it is produced             |
| --------- | --------- | ------------------------------ |
| VSYNC     | 3         | three explicit `STA WSYNC`     |
| VBLANK    | 37        | `TIM64T = 43` countdown        |
| KERNEL    | 192       | explicit `STA WSYNC` loop      |
| OVERSCAN  | 30        | `TIM64T = 37` countdown        |
| **Total** | **262**   |                                |

### Why the timer values are 43 and 37

The RIOT timer ticks once every 64 cycles. Setting `TIM64T = N` would naively
be expected to last `N * 64` cycles, but Stella's M6532 implementation (and
real hardware) behaves slightly differently:

* `mySubTimer` starts at `myDivider - 1`, so the first tick effectively
  happens a few cycles early;
* the countdown wraps when it reaches `(value + 1) * 64` cycles.

Because of this the timer expires on an earlier cycle than a naive
`value * 64` calculation suggests. Empirically (measured with
`print _cyclesLo` at the `StartOfFrame` breakpoint in the Stella debugger):

* `VBLANK_TIMER_VALUE = 43` makes the VBLANK wait expire on line 39; the
  `STA WSYNC` that follows syncs to line 40, where `HMOVE` is written
  immediately after the `WSYNC` (required so the motion registers act during
  horizontal blanking of the last VBLANK line);
* `OVERSCAN_TIMER_VALUE = 37` makes the OVERSCAN wait expire on the final
  frame line.

A naive reading of `37 * 64 = 2368` cycles for overscan corresponds to
`2368 / 76 = 31.1` scanlines; the effective behaviour yields the intended
30 scanlines.

## The visible kernel

One scanline = **76 CPU cycles**. Each kernel iteration starts with
`STA WSYNC`, so every iteration is exactly one scanline; the frame cannot
drift when a player moves.

### Cycle accounting (verified from the listing)

The kernel is **branchless**: the only branch is the tail `BNE` that loops
back to `KernelLoop`, so every scanline costs exactly the same regardless of
player or ball state. This removes all data-dependent timing from the
rendering path.

Per scanline:

| Instruction          | Cycles |
| -------------------- | ------ |
| `STA WSYNC`          | 3      |
| `STA ENABL`          | 3      |
| P0 rectangle block   | 18     |
| P1 rectangle block   | 18     |
| Tail (incl. `BNE`)   | 20     |
| **Total**            | **62** |

Player block (one player):

| Instruction            | Cycles |
| ---------------------- | ------ |
| `TXA`                  | 2      |
| `SEC`                  | 2      |
| `SBC PLAYERxY`         | 3      |
| `CMP #PLAYER_HEIGHT`   | 2      |
| `LDA #0`               | 2      |
| `SBC #0`               | 2      |
| `AND #PADDLE_BITS`     | 2      |
| `STA GRPx`             | 3      |
| **Subtotal**           | **18** |

The `LDA #0 / SBC #0` sequence is a branchless "draw or blank" test: after
`CMP #PLAYER_HEIGHT` the carry is clear exactly on the paddle rows
(`PLAYERx_Y <= X < PLAYERx_Y + height`), so `SBC #0` leaves `A = $FF` there
and `A = $00` everywhere else; `AND #PADDLE_BITS` maps that to the row byte
`%00111100` or 0.

Tail (per scanline):

| Instruction              | Cycles |
| ------------------------ | ------ |
| `TXA`                    | 2      |
| `SEC`                    | 2      |
| `SBC ball_y`             | 3      |
| `CMP #BALL_HEIGHT`       | 2      |
| `LDA #0`                 | 2      |
| `SBC #0`                 | 2      |
| `INX`                    | 2      |
| `CPX #KERNEL_SCANLINES`  | 2      |
| `BNE KernelLoop`         | 3      |
| **Subtotal**             | **20** |

| Path                    | Cycles |
| ----------------------- | ------ |
| Any (kernel is branchless) | **62** |
| Scanline budget         | 76     |
| Slack                   | **14 cycles** |

The slack recovered from 2 to 14 cycles because the old kernel's branch
paths (74 worst case) are gone: the new kernel is shorter and fully
deterministic. The single cost of this design is that both players must be
rendered as constant rectangles: a table-driven player (indexed `LDA` +
`JMP`) cannot fit after the `ENABL` write that must lead the scanline and
still leave `GRP0` with margin.

### Ball enable timing (the Round 2 vertical-displacement fix)

The TIA samples the ball enable bit at the ball's horizontal position; the
value written to `ENABL` is **not** latched for the following scanline. The
previous kernel wrote `ENABL` late in the scanline (~cycle 67), so whether a
given scanline drew the ball with the current or the previous line's enable
value depended on `ball_x` relative to the beam position at the write. The
result was a ball that jumped one scanline vertically in some horizontal
regions.

The fix writes `ENABL` during the horizontal blanking of every scanline:
`STA ENABL` completes at ~cycle 5, far before the first visible pixel
(~cycle 22.7). The value is precomputed in the tail of the *previous*
scanline for the *current* line, so the ball draws on exactly `BALL_HEIGHT`
consecutive lines regardless of `ball_x`: line L shows the ball iff L-1 is a
ball row, i.e. L in `ball_y+1 .. ball_y+BALL_HEIGHT` (the same display
convention as before). Line 0 writes the `A = 0` left over from the
pre-kernel, so the first visible line is always ball-free. `ENABL` is
cleared again during overscan init, so the register can never hold 1 into
overscan even when the ball rests at the bottom of the arena.

Because the enable value is carried in `A` across the loop back-edge, no RAM
byte is needed for it.

### Graphics register write times

`ENABL` completes at ~cycle 5, `GRP0` at ~cycle 23 (before the beam reaches
P0 at x=16, ~cycle 28.3) and `GRP1` at ~cycle 41 (before the beam reaches P1
at x=136, ~cycle 68). All three writes happen before their object's
horizontal position, so each object renders with the value written on the
current scanline.

## VBLANK and OVERSCAN budgets

The gameplay (joystick decode + movement + ball update + positioning) runs
in VBLANK between the VSYNC release and the timer wait. Its cost is:

* `UpdatePlayers`: 3 + 3 + (2+3+2/3) + (2+3+2+2/3) + ... roughly 60 cycles
  worst case for both players;
* `UpdateBall`: four bounce checks + two moves, ~65 cycles worst case
  (branch taken on every check);
* `PositionPlayers`: two `PosObject` calls consuming 1-2 scanlines each;
* `PositionBall`: one `PosObject` call.

This is far below the 37-line VBLANK budget and never interferes with the
visible kernel.

## Measured frame length

Measured in Stella 6.6 with the debugger:

* `print _cyclesLo` at `StartOfFrame` breakpoints across consecutive
  frames: steady-state deltas of **19912 cycles** each.
* `19912 / 76 = 262` scanlines exactly.

The very first frame after power-on is ~55 cycles shorter than steady state
because the CPU and TIA clocks are not yet aligned; all subsequent frames
are exactly 19912 cycles. This is normal reset behavior.

The frame-length measurement is deterministic but requires the Stella GUI
debugger, so it is documented here rather than automated in CI.

### Runtime validation status

There is **no automated runtime scanline validation** in the current
pipeline. Stella 6.6 offers no documented headless option that advances
frames and exposes the TIA scanline counter to stdout; the debugger and the
frame-stats overlay (Alt-L) need a graphical session and interactive input,
and keystroke automation is too fragile for CI. Consequently:

* the 262-scanline frame was measured **manually in the Stella debugger on a
  local graphical session** (`print _cyclesLo` deltas of 19912 cycles);
* the CI pipeline validates the frame structure **statically** (constants,
  listing, region scanline sum == 262, kernel cycle budget) and rejects any
  build whose region scanline sum differs from 262.

The project therefore does not claim that scanlines were "validated at
runtime in CI"; runtime frame validation remains a manual step, and the
architecture keeps the static suite as the deterministic CI-safe substitute.

## Why this matters

"Visual correctness is not proof of hardware correctness": a frame that
looks right but drifts to 260 or 261 scanlines violates the NTSC timing
contract. The timer values above were tuned precisely so the frame is
exactly 262 scanlines in the reference emulator.