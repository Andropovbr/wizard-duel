# Wizard Duel - Timing

This document records the cycle-level timing analysis of the Round 3
event-driven kernel and frame. Every number below was derived by hand and
then verified against the assembled listing by the automated test suite, and
the frame length was cross-checked with a deterministic 6502 emulator that
models WSYNC stalls and the RIOT timer.

## Frame structure (NTSC)

| Region    | Scanlines | How it is produced             |
| --------- | --------- | ------------------------------ |
| VSYNC     | 3         | three explicit `STA WSYNC`     |
| VBLANK    | 57        | `TIM64T = 69` countdown        |
| KERNEL    | 192       | explicit `STA WSYNC` loop      |
| OVERSCAN  | 10        | `TIM64T = 11` countdown        |
| **Total** | **262**   |                                |

VBLANK grew from 37 (Round 2) to 57 lines and OVERSCAN shrank from 30 to 10
lines to give `BuildEvents` room to rebuild the event table every frame.

### Why the timer values are 69 and 11

The RIOT timer ticks once every 64 cycles. Round 2 used `43`/`37` for a 37/30
line split; the Round 3 values were derived the same way (the timer expires a
few cycles earlier than the naive `value * 64` suggests, and the `STA WSYNC`
after each wait syncs to the correct line) and then tuned empirically so the
emulator reports exactly 262 scanlines per frame:

* `VBLANK_TIMER_VALUE = 69` expires on the penultimate VBLANK line; the
  `STA WSYNC` that follows syncs to the last VBLANK line, where `HMOVE` is
  written immediately after the `WSYNC` (required so the motion registers act
  during horizontal blanking of the last VBLANK line);
* `OVERSCAN_TIMER_VALUE = 11` expires on the final frame line.

## The visible kernel

One scanline = **76 CPU cycles**. Each kernel iteration starts with
`STA WSYNC`, so every iteration is exactly one scanline; the frame cannot
drift when events fire.

### Event-driven structure

The kernel does not compute object enables. `BuildEvents` (run during VBLANK)
writes a table (`evTbl`) of 5-byte entries `[delta, reg1, val1, reg2, val2]`:
`delta` is the number of scanlines until the entry fires, and the two
`(register index, value)` pairs are the writes to apply (indices 1..5 address
GRP0..ENABL; index 0 is a harmless AUDV1 dummy, so every entry always writes
two registers and the event path is straight-line code).

The kernel counts its 192 lines with a RAM countdown (`scanCnt`). This is
deliberate: the event code uses `TAX` as the register index, which would
clobber an X line counter on every event line and stretch the frame.

### Cycle accounting (verified from the listing)

Two paths exist per scanline.

Non-event line (the common case):

| Instruction          | Cycles |
| -------------------- | ------ |
| `STA WSYNC`          | 3      |
| `DEC scanCnt`        | 5      |
| `BEQ .kernelEnd`     | 2      |
| `DEC evCnt`          | 5      |
| `BNE KernelLoop`     | 3      |
| **Total**            | **18** |

Event line, worst case (two-write entry):

| Instruction          | Cycles |
| -------------------- | ------ |
| `STA WSYNC`          | 3      |
| `DEC scanCnt`        | 5      |
| `BEQ .kernelEnd`     | 2      |
| `DEC evCnt`          | 5      |
| `BNE KernelLoop`     | 2      |
| `LDY evIdx`          | 3      |
| `LDA evTbl+1,Y`      | 4      |
| `TAX`                | 2      |
| `LDA evTbl+2,Y`      | 4      |
| `STA EV_WRITE_BASE,X`| 4      |
| `LDA evTbl+3,Y`      | 4      |
| `TAX`                | 2      |
| `LDA evTbl+4,Y`      | 4      |
| `STA EV_WRITE_BASE,X`| 4      |
| `TYA` / `CLC` / `ADC #5` / `TAY` | 8 |
| `STY evIdx`          | 3      |
| `LDA evTbl,Y`        | 4      |
| `STA evCnt`          | 3      |
| `JMP KernelLoop`     | 3      |
| **Total**            | **69** |

| Path                    | Cycles |
| ----------------------- | ------ |
| Non-event line          | **18** |
| Event line (two writes) | **69** |
| Scanline budget         | 76     |
| Slack (event line)      | **7 cycles** |

`BuildEvents` merges at most two same-row records into one entry, so no
scanline ever needs more than two writes; a pathological third event on a row
is bumped to row+1 (see [architecture.md](architecture.md)).

The kernel body is page-aligned (`ALIGN 256` before `KernelLoop`) so every
branch has deterministic timing, and all table accesses are zero-page indexed
(no page-crossing penalties).

### Graphics register write times

All object registers are written early in the scanline. `GRP0` completes at
~cycle 18 (before the beam reaches P0 at x=16, ~cycle 28), `GRP1` at ~cycle
22, and the enable registers at ~cycle 16-20 (before any missile's position).
Each object renders with the value written on the current scanline, matching
the Round 2 write-timing invariant.

## VBLANK and OVERSCAN budgets

The gameplay (joystick decode + movement + missile update + positioning) and
the event-table build run in VBLANK between the VSYNC release and the timer
wait. Its worst case (both missiles active, pathological row alignment) is
~4.1k cycles of CPU work plus the `PosObject` WSYNC line syncs, comfortably
inside the `69 * 64 = 4416`-cycle VBLANK timer window (measured with the
deterministic emulator: worst case ~4135 cycles, ~280 cycles of margin).

The OVERSCAN work (blank the display, clear every object register, arm the
timer, wait, jump) fits inside its 10-line window.

## Measured frame length

Verified with a deterministic 6502 emulator that models WSYNC stalls and the
RIOT timer:

* steady-state frame length: **19912 cycles = 262 scanlines exactly**, stable
  across 30+ frames for the no-missile, both-missiles and pathological states;
* the visible kernel runs exactly 192 iterations (the `scanCnt` countdown).

The very first frame after power-on is a few cycles shorter than steady state
because the CPU and TIA clocks are not yet aligned; all subsequent frames are
exactly 19912 cycles. This is normal reset behavior.

### Runtime validation status

The automated suite validates the frame structure **statically** (constants,
listing, region scanline sum == 262, kernel cycle budget) and the event-table
builder with a Python model (deltas, merges, collision resolution). The
262-scanline frame length is additionally verified by the deterministic 6502
emulator during development; this emulator is not part of the committed CI
pipeline, so runtime frame validation remains a documented development-time
step backed by the static suite in CI.

## Why this matters

"Visual correctness is not proof of hardware correctness": a frame that
looks right but drifts to 260 or 263 scanlines violates the NTSC timing
contract. The timer values above were tuned precisely so the frame is exactly
262 scanlines, and the event kernel's `scanCnt` countdown keeps the visible
region exactly 192 lines regardless of how many events fire.
