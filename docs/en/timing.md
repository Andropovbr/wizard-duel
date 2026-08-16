# Wizard Duel - Timing

This document records the cycle-level timing analysis of the Round 1 kernel
and frame. Every number below was either derived by hand and then verified
against the assembled listing by the automated test suite, or measured in
Stella's debugger.

## Frame structure (NTSC)

| Region    | Scanlines | How it is produced             |
| --------- | --------- | ------------------------------ |
| VSYNC     | 3         | three explicit `STA WSYNC`     |
| VBLANK    | 37        | `TIM64T = 44` countdown        |
| KERNEL    | 192       | explicit `STA WSYNC` loop      |
| OVERSCAN  | 30        | `TIM64T = 37` countdown        |
| **Total** | **262**   |                                |

### Why the timer values are 44 and 37

The RIOT timer ticks once every 64 cycles. Setting `TIM64T = N` would naively
be expected to last `N * 64` cycles, but Stella's M6532 implementation (and
real hardware) behaves slightly differently:

* `mySubTimer` starts at `myDivider - 1`, so the first tick effectively
  happens a few cycles early;
* the countdown wraps when it reaches `(value + 1) * 64` cycles.

Because of this the timer expires on an earlier cycle than a naive
`value * 64` calculation suggests. Empirically (measured with
`print _cyclesLo` at the `StartOfFrame` breakpoint in the Stella debugger):

* `VBLANK_TIMER_VALUE = 44` makes the VBLANK wait expire on the final
  VBLANK scanline (line 40 of the frame);
* `OVERSCAN_TIMER_VALUE = 37` makes the OVERSCAN wait expire on the final
  frame line.

A naive reading of `37 * 64 = 2368` cycles for overscan corresponds to
`2368 / 76 = 31.1` scanlines; the effective behaviour yields the intended
30 scanlines.

## The visible kernel

One scanline = **76 CPU cycles**. Each kernel iteration starts with
`STA WSYNC`, so every iteration is exactly one scanline regardless of
branching; the frame cannot drift when a player moves.

### Cycle accounting (verified from the listing)

Drawn path per player (sprite row written):

| Instruction       | Cycles |
| ----------------- | ------ |
| `TXA`             | 2      |
| `SEC`             | 2      |
| `SBC P0Y`         | 3      |
| `CMP #height`     | 2      |
| `BCS .P0Blank`    | 2 (not taken) |
| `TAY`             | 2      |
| `LDA P0Sprite,Y`  | 4      |
| `JMP .P0Done`     | 3      |
| `STA GRP0`        | 3      |
| **Subtotal**      | **23** |

Blank path per player (no sprite row this line):

| Instruction       | Cycles |
| ----------------- | ------ |
| `TXA`             | 2      |
| `SEC`             | 2      |
| `SBC P0Y`         | 3      |
| `CMP #height`     | 2      |
| `BCS .P0Blank`    | 3 (taken) |
| `LDA #0`          | 2      |
| `STA GRP0`        | 3      |
| **Subtotal**      | **17** |

Tail (per scanline): `INX` 2 + `CPX #192` 2 + `BNE` 3 + `STA WSYNC` 3
= **10**.

| Path                     | Cycles |
| ------------------------ | ------ |
| Both sprites drawn       | 23+23+10 = **56** |
| Both sprites blank       | 17+17+10 = **44** |
| One drawn, one blank     | 23+17+10 = **50** |
| Scanline budget          | 76     |
| Worst-case slack         | **20 cycles** |

The sprite tables are laid out so every possible row index (0..11) stays
inside a single page; the indexed `LDA` never pays the +1 page-cross
penalty. This is asserted by the test suite.

`GRP0` is written at ~cycle 23 of its scanline and `GRP1` at ~cycle 46;
both are latched for the following line, well before the 76-cycle limit.

## VBLANK and OVERSCAN budgets

The gameplay (joystick decode + movement + positioning) runs in VBLANK
between the VSYNC release and the timer wait. Its cost is:

* `UpdatePlayers`: 3 + 3 + (2+3+2/3) + (2+3+2+2/3) + ... roughly 60 cycles
  worst case for both players;
* `PositionPlayers`: two `PosObject` calls consuming 1-2 scanlines each.

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
debugger, so it is documented here rather than automated in CI. The CI
pipeline validates the frame structure statically (constants, listing) and
rejects any build whose region scanline sum differs from 262.

## Why this matters

"Visual correctness is not proof of hardware correctness": a frame that
looks right but drifts to 260 or 261 scanlines violates the NTSC timing
contract. The timer values above were tuned precisely so the frame is
exactly 262 scanlines in the reference emulator.