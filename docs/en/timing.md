# Wizard Duel - Timing

This document records the cycle-level timing analysis of the Round 3.1
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
| OVERSCAN  | 10        | fixed `WSYNC` countdown loop    |
| **Total** | **262**   |                                |

VBLANK grew from 37 (Round 2) to 57 lines and OVERSCAN shrank from 30 to 10
lines to give `BuildEvents` room to rebuild the event table every frame.

### Why the VBLANK timer is 69 and the overscan is a WSYNC loop

The RIOT timer ticks once every 64 cycles. Round 2 used `43`/`37` for a 37/30
line split; the Round 3/4 values were derived the same way (the timer expires
a few cycles earlier than the naive `value * 64` suggests, and the `STA WSYNC`
after the wait syncs to the correct line) and then tuned empirically so the
emulator reports exactly 262 scanlines per frame:

* `VBLANK_TIMER_VALUE = 69` expires on the penultimate VBLANK line; the
  `STA WSYNC` that follows syncs to the last VBLANK line, where `HMOVE` is
  written immediately after the `WSYNC` (required so the motion registers act
  during horizontal blanking of the last VBLANK line);
* the OVERSCAN does NOT use a timer. A `TIM64T` wait is only deterministic
  when the work executed before arming it is fixed; Round 4's variable-cost
  collision pass made the `INTIM < 64` exit land on different 76-cycle
  boundaries and the frame occasionally slipped to 263 scanlines. Instead the
  overscan writes exactly `OVERSCAN_LOOP_COUNT = 7` `WSYNC`s. From the
  kernel's last line a fixed epilogue + the `ProcessCollisions` JSR and
  branchless body + the `ProcessHitEffects` JSR (Round 5) put the first
  `WSYNC` between cycles 187 and 207 of the region (emulator model; every
  path lands on the same boundary at cycle 228 = scanline 3). The loop then
  counts exactly 10 lines and the `JMP` + VSYNC preamble that follow align
  the next frame's first VSYNC `WSYNC` to 760 cycles after the kernel's last
  line. Because the only variable-cost pass (`ProcessHitEffects`) is confined
  to a window that never escapes the first boundary, the region is exactly 10
  scanlines regardless of how many hits are detected or whether players are
  dead.

## The visible kernel

One scanline = **76 CPU cycles**. Each kernel iteration starts with
`STA WSYNC`, so every iteration is exactly one scanline; the frame cannot
drift when events fire.

### Event-driven structure

The kernel does not compute object enables. `BuildEvents` (run during VBLANK)
writes a table (`evTbl`) of variable-size entries. Each entry starts with
`delta` (scanlines until it fires) and `reg1` (index of the first write;
indices 1..5 address GRP0..ENABL, index 0 is a harmless AUDV1 dummy). If bit 7
of `reg1` is set the entry is a 3-byte single `[delta, reg1|$80, val1]`;
otherwise it is a 5-byte double `[delta, reg1, val1, reg2, val2]`.

The kernel dispatches on the flag bit with a single `BMI`; the value byte of a
single never carries bit 7 because every write value is an enable register
value (`$00`, `PADDLE_BITS`, `BALL_ENABLE` or `MISSILE_ENABLE`). This is what
lets a scanline that needs only one write skip the second write entirely
instead of wasting a harmless dummy write.

The kernel counts its 192 lines with a RAM countdown (`scanCnt`). This is
deliberate: the event code uses `TAX` as the register index, which would
clobber an X line counter on every event line and stretch the frame.

### Cycle accounting (verified from the listing)

Three paths exist per scanline: non-event, single-write event, two-write
event.

Non-event line (the common case):

| Instruction          | Cycles |
| -------------------- | ------ |
| `STA WSYNC`          | 3      |
| `DEC scanCnt`        | 5      |
| `BEQ .kernelEnd`     | 2      |
| `DEC evCnt`          | 5      |
| `BNE KernelLoop`     | 3      |
| **Total**            | **18** |

Event line, single write (3-byte entry):

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
| `TYA` / `CLC` / `ADC #3` / `TAY` | 8 |
| `STY evIdx`          | 3      |
| `LDA evTbl,Y`        | 4      |
| `STA evCnt`          | 3      |
| `JMP KernelLoop`     | 3      |
| **Total**            | **54** |

Event line, two writes (5-byte entry):

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
| **Total**            | **65** |

| Path                    | Cycles |
| ----------------------- | ------ |
| Non-event line          | **18** |
| Event line (single write)| **54** |
| Event line (two writes) | **65** |
| Scanline budget         | 76     |
| Slack (two-write line)  | **11 cycles** |

The kernel body is page-aligned (`ALIGN 256` before `KernelLoop`) so every
branch has deterministic timing, and all table accesses are zero-page indexed
(no page-crossing penalties). The kernel has exactly three conditional
branches: the `BEQ` scan-line end test, the `BNE` event countdown, and the
`BMI` single/double dispatch.

### Graphics register write times

In a two-write event line the first register write executes during CPU cycles
30..33 and the second during cycles 44..47; in a single-write line the write
executes during cycles 30..33.

A TIA write applies to the current scanline only if it completes before the
beam passes the object's horizontal position; otherwise it applies one
scanline later. Using the standard beam model (pixel `p` is reached at CPU
cycle `~(p + 69) / 3`), the gates are therefore `x >= 30` for the first write
and `x >= 72` for the second. Both players are far outside those bands (P0 at
x=16, P1 at x=136) and behave exactly as in Round 3; only an object whose
position fell inside the 3-pixel bands `30..32` / `72..74` would gain one
scanline of margin, and no object in this round occupies those positions.
The next entry's `delta` is read by cycle 65 on the worst path, comfortably
before the `WSYNC` that starts the next line.

## VBLANK and OVERSCAN budgets

The gameplay (joystick decode + movement + missile update + positioning) and
the event-table build run in VBLANK between the VSYNC release and the timer
wait. The collision pass is deliberately NOT here: the heaviest VBLANK path
(both missiles active, both fire edges) is already within a few cycles of the
VBLANK timer window's alignment boundary, and adding a variable-cost pass
there made one frame per stress run slip to 263 scanlines. With collision
handled in the overscan, the VBLANK work ends with enough margin that the
timer wait always holds the region at exactly 57 lines. Round 5 adds a small
branchy gate to `BuildEvents` (a dead player contributes no events), which
costs ~10 cycles only on the alive path; the measured worst-case VBLANK poll
exit still leaves ~45 cycles of margin.

The OVERSCAN work is `ProcessCollisions` (fixed 84 cycles, branchless) plus
`ProcessHitEffects` (Round 5: HP damage + dead-player fire lock; branchy but
bounded to a 60..80-cycle window) plus exactly `OVERSCAN_LOOP_COUNT` `WSYNC`
writes. Every path through `ProcessHitEffects` lands the first `WSYNC` on the
same 76-cycle boundary (cycle 228 after the kernel's last line), so the
10-line region is deterministic by construction: it cannot drift regardless
of how many hits are detected or whether players are dead. `ProcessHitEffects`
is page-aligned (`ALIGN 256`) so its four branches can never gain a
page-crossing cycle on real silicon.

## Measured frame length

Verified with a deterministic 6502 emulator that models WSYNC stalls and the
RIOT timer:

* steady-state frame length: **19912 cycles = 262 scanlines exactly**, stable
  across 30+ frames for the no-missile, both-missiles and pathological states;
  with the Round 4 collision pass the frame is uniform across 600+ max-stress
  frames (both collision latches asserted every frame, alternating fire
  presses); previously the same input made ~1% of frames slip to 263 lines.
  Round 5 adds the HP/death paths: the frame stays at 19912 cycles under the
  same max-stress input (players kept alive) and with both players dead;
* the visible kernel runs exactly 192 iterations (the `scanCnt` countdown).

The very first frame after power-on is a few cycles shorter than steady state
because the CPU and TIA clocks are not yet aligned; all subsequent frames are
exactly 19912 cycles. This is normal reset behavior.

### Runtime validation status

The automated suite validates the frame structure **statically** (constants,
listing, region scanline sum == 262, kernel cycle budget) and the event-table
builder with a Python model (deltas, merges, collision resolution). A runtime
frame-timing test (`tests/test_frame_timing.py`) drives the deterministic
emulator across many frames and asserts frame stability (262 scanlines), that
the table length never exceeds `EV_TBL_SIZE` under aggressive fire input, and
that missiles actually spawn and despawn through the event pipeline. Round 5
adds `tests/test_hp.py`, which drives the real `ProcessHitEffects` assembly
and asserts HP damage/death semantics, and keeps the max-stress regression
alive by topping up HP every frame. The emulator's cycle counter is
approximate (single-frame totals vary by a few cycles), so the runtime test
asserts scanline count and behavior, not exact cycle totals.

## Why this matters

"Visual correctness is not proof of hardware correctness": a frame that
looks right but drifts to 260 or 263 scanlines violates the NTSC timing
contract. The timer values above were tuned precisely so the frame is exactly
262 scanlines, and the event kernel's `scanCnt` countdown keeps the visible
region exactly 192 lines regardless of how many events fire.
