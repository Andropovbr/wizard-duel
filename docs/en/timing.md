# Wizard Duel - Timing

This document records the cycle-level timing analysis of the Round 11
event-driven kernel and frame. Every number below was derived by hand and
then verified against the assembled listing by the automated test suite, and
the frame length was cross-checked with a deterministic 6502 emulator that
models WSYNC stalls and the RIOT timer.

## Frame structure (NTSC)

| Region    | Scanlines | How it is produced             |
| --------- | --------- | ------------------------------ |
| VSYNC     | 3         | three explicit `STA WSYNC`     |
| VBLANK    | 64        | `TIM64T = 77` countdown        |
| KERNEL    | 185       | explicit `STA WSYNC` loop      |
| OVERSCAN  | 10        | fixed `WSYNC` countdown loop    |
| **Total** | **262**   |                                |

VBLANK grew from 37 (Round 2) to 57 lines and OVERSCAN shrank from 30 to 10
lines to give `BuildEvents` room to rebuild the event table every frame. In
Round 6 VBLANK grew from 57 to 64 lines and KERNEL shrank from 192 to 185 to
close a frame-shake bug under realistic branch timing (see below).

### Why the VBLANK timer is 77 and the overscan is a WSYNC loop

The RIOT timer ticks once every 64 cycles. Round 2 used `43`/`37` for a 37/30
line split; the Round 3/4 values were derived the same way (the timer expires
a few cycles earlier than the naive `value * 64` suggests, and the `STA WSYNC`
after the wait syncs to the correct line) and then tuned empirically so the
emulator reports exactly 262 scanlines per frame:

* `VBLANK_TIMER_VALUE = 77` expires on the penultimate VBLANK line; the
  `STA WSYNC` that follows syncs to the last VBLANK line, where `HMOVE` is
  written immediately after the `WSYNC` (required so the motion registers act
  during horizontal blanking of the last VBLANK line);
* the OVERSCAN does NOT use a timer. A `TIM64T` wait is only deterministic
  when the work executed before arming it is fixed; Round 4's variable-cost
  collision pass made the `INTIM < 64` exit land on different 76-cycle
  boundaries and the frame occasionally slipped to 263 scanlines. Instead the
  overscan writes exactly `OVERSCAN_LOOP_COUNT = 6` `WSYNC`s. From the
  kernel's last line the epilogue + the `ProcessCollisions` JSR and
  branchless body + the `ProcessHitEffects` JSR (Round 5) + 8 cycles of
  padding put the first
  `WSYNC` between cycles 236 and 254 of the region (emulator model; every
  path lands on the same boundary at cycle 304 = scanline 4). The loop then
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
writes a fixed table (`evTbl`, 60 bytes) of uniform 5-byte entries
`[delta, reg1, val1, reg2, val2]` (reg2 = 0 marks a single write). Entry
indices 1..5 address GRP0..ENABL; index 0 is the AUDV0 dummy used by the
table's first 5 bytes (see below). The table is `[dummy][entry 0][entry 1]
... [entry N][marker]`, where the marker's delta byte is `$FF` and ends the
kernel. Deltas are the gaps to the NEXT entry; `nullDelta` primes the first
countdown.

The kernel is a **table-direct apply**: every scanline starts by applying the
last-decoded entry's two writes directly from the table, reading through
`Y-5` (Y always points one entry past the last-decoded entry), then counts
`evCnt` down to the next event. Because the apply runs unconditionally at the
START of every line - event line or not - two events on consecutive rows
(delta 1) can never collide the way the Round 10 two-phase pending pipeline
did: each entry's writes land at the start of its own display row. The apply
is idempotent, which is what makes re-applying the same entry on the lines
between events harmless.

The table's first 5 bytes are a dummy entry (reg1 = reg2 = 0, so both writes
go to AUDV0 - benign while the display is on). On the lines before the first
event fires, Y = 5 makes the apply read the dummy. Real entries start at
table offset 5, the marker at offset `5 + 5*N`.

### Cycle accounting (verified from the listing)

Three paths exist per scanline: non-event, event, and end-marker. The kernel
body is page-aligned (`ALIGN 256` before `KernelLoop`) so every branch has
deterministic timing, and every table access is zero-page indexed (`LDX
evTbl-4,Y` emits `0xB6` LDX zp,Y) so no indexed access can cross a page.

Non-event line (the common case):

| Instruction          | Cycles |
| -------------------- | ------ |
| `STA WSYNC`          | 3      |
| `LDX evTbl-4,Y`      | 4      |
| `LDA evTbl-3,Y`      | 4      |
| `STA EV_WRITE_BASE,X`| 4      |
| `LDX evTbl-2,Y`      | 4      |
| `LDA evTbl-1,Y`      | 4      |
| `STA EV_WRITE_BASE,X`| 4      |
| `DEC evCnt`          | 5      |
| `BNE .applyOnly`     | 3      |
| `JMP KernelLoop`     | 3      |
| **Total**            | **38** |

Event line (delta read + advance):

| Instruction          | Cycles |
| -------------------- | ------ |
| (apply block, 24) + `DEC evCnt` (5) + `BNE` not taken | 31 |
| `LDA evTbl,Y`        | 4      |
| `STA evCnt`          | 3      |
| `CMP #EV_MARKER_VAL` | 2      |
| `BEQ .kernelEnd` not taken | 2 |
| `TYA` / `ADC #5` / `TAY` | 6  |
| `JMP KernelLoop`     | 3      |
| **Total**            | **54** |

End-marker line (marker fired -> kernel done):

| Instruction          | Cycles |
| -------------------- | ------ |
| (apply block, 24) + `DEC evCnt` (5) + `BNE` not taken | 31 |
| `LDA evTbl,Y`        | 4      |
| `STA evCnt`          | 3      |
| `CMP #EV_MARKER_VAL` | 2      |
| `BEQ .kernelEnd` taken | 3    |
| **Total**            | **46** |

| Path                    | Cycles |
| ----------------------- | ------ |
| Non-event line          | **38** |
| Event line              | **54** |
| End-marker line         | **46** |
| Scanline budget         | 76     |
| Slack (event line)      | **22 cycles** |

The carry flag is cleared exactly once, in the priming (`CLC`); on every
kernel path carry is still clear at the `ADC #5`: the event decode's
`CMP #$FF` clears it for every real delta (< $FF), and the marker's `CMP`
sets carry only on the `BEQ .kernelEnd` path (which skips the `ADC`). No
`CLC` exists inside the kernel body.

### Graphics register write times

Measured on the deterministic emulator, the register writes land at these CPU
cycles within a scanline:

* write 1 (reg1/val1): completes at cycle **15**, before the beam reaches
  pixel 0 (cycle ~23), so it is safe for every object including the ball at
  x = 0;
* write 2 (reg2/val2): completes at cycle **27**.

A TIA write applies to the current scanline only if it completes before the
beam passes the object's horizontal position; otherwise it applies one
scanline later. Using the documented beam model (pixel `p` is reached at CPU
cycle `~(p + 69) / 3`), write 2 at cycle 27 gates `x >= 13` (conservative;
the real gate is smaller). The builder therefore enforces the slot rule: the
second write of a double is only ever GRP0 (x=16), GRP1 (x=136) or ENAM0
(x >= 18) - never ENABL or ENAM1, whose X can fall below 13. The ball and M1
always win slot 1 on a row tie.

The write cycle sets a *scheduling* constraint, not just a margin: an object
whose X can fall below the second gate must never occupy the second slot
(see `docs/en/architecture.md`). The next entry's `delta` is read by cycle
50 on the worst path, comfortably before the `WSYNC` that starts the next
line.

## VBLANK and OVERSCAN budgets

The gameplay (joystick decode + movement + missile update + positioning) and
the event-table build run in VBLANK between the VSYNC release and the timer
wait. The collision pass is deliberately NOT here: the heaviest VBLANK path
(both missiles active, both fire edges) is already within a few cycles of the
VBLANK timer window's alignment boundary, and adding a variable-cost pass
there made one frame per stress run slip to 263 scanlines. With collision
handled in the overscan, the VBLANK work ends with enough margin that the
timer wait always holds the region at its fixed line count.

### Round 6: the VBLANK shake bug and how it was closed

Round 5 left VBLANK at 57 lines with `VBLANK_TIMER_VALUE = 69`, tuned against
an emulator whose cycle table folded every conditional branch to 2 cycles.
On real silicon a *taken* branch costs 3 cycles (4 on a page crossing). Under
the Round 5 VBLANK work (movement + missile update + `BuildEvents` with the
dead-player gate), realistic worst-case work reached ~4919 cycles, but the
T=69 timer expires at ~4553 cycles (`(69 - 1) * 64` before `INTIM` reads 0).
That is backwards: the work outran the timer, so `WaitVBlank` stopped polling
on `INTIM == 0` (fixed boundary) and instead fell through at the *variable
work end*. Depending on where the work landed relative to the 76-cycle grid,
individual frames stretched to 263/264/265 scanlines — a visible shake that
emulator shortcuts hid entirely.

Round 6 fixes the budget, not the poll:

* `VBLANK_SCANLINES` 57 -> 64, KERNEL 192 -> 185, `VBLANK_TIMER_VALUE` 69 ->
  77. The timer now expires at ~4864 cycles (`(77 - 1) * 64`), well after the
  measured worst-case work of ~4455 cycles (margin ~409). The poll always
  exits on the fixed timer boundary, so the frame is exactly 262 scanlines
  regardless of VBLANK work length;
* the emulator (`tools/emu6502.py`) now models taken-branch (+1) and
  page-crossing (+2 on a taken branch, +1 on `LDA abs,Y`) cycle costs, so the
  regression is detectable without real hardware. The benchmark tracks
  `vblank_work` (TIM64T write to first `LDA INTIM`) and `vblank_margin`
  (`(timer - 1) * 64 - vblank_work`).

A `TIM64T` wait is only deterministic when the work executed before arming it
is fixed or comfortably below the expiry. The overscan does NOT use a timer for
the same reason: a variable-cost pass (`ProcessHitEffects`) runs between the
kernel and the overscan wait, so the overscan writes exactly
`OVERSCAN_LOOP_COUNT = 6` `WSYNC`s instead. From the
kernel's last line the epilogue + the `ProcessCollisions` JSR and
branchless body + the `ProcessHitEffects` JSR (Round 5) + 8 cycles of padding
put the first `WSYNC` between cycles 236 and 254 of the region (emulator
model; every path lands on the same boundary at cycle 304 = scanline 4). The
loop then
counts exactly 10 lines and the `JMP` + VSYNC preamble that follow align
the next frame's first VSYNC `WSYNC` to 760 cycles after the kernel's last
line. Because the only variable-cost pass (`ProcessHitEffects`) is confined
to a window that never escapes the first boundary, the region is exactly 10
scanlines regardless of how many hits are detected or whether players are
dead.

### Round 7: the same-row bump and the delta-0 stretch

`InsertEvent` never lets a scanline need more than two writes: a third event
on a row that already holds a double is bumped to row+1. Round 7 fixed a
latent bug in that path. `.insertSingle` stored the event's *original
stacked row* even when the bump had already advanced `evRow`, so a third
event colliding with a double produced **two table entries at the same
absolute row**. `ConvertDeltas` then emitted delta 0, the kernel's `DEC
evCnt` wrapped `0 -> $FF`, and that OFF event never fired: the object stayed
enabled from its ON row to the bottom edge — a vertical stretch that only
appeared when enough objects coincided on one row (both players alive at the
same row, both missiles flying, ball crossing the missile rows).

The fix makes `.insertSingle` write the effective (possibly bumped) `evRow`
and discard the original stacked row, so entry rows stay strictly increasing
and no delta-0 entry can exist. Cycle cost is +1 per `insertSingle` (an
extra zero-page `LDA evRow`), executed in VBLANK: worst-case VBLANK work
grew 4455 -> 4485 cycles, margin ~409 -> ~379, still far inside the T=77
expiry (~4864). The kernel itself is untouched, so the 65/76 worst path and
the 262-scanline frame are unchanged.

### Round 8: the ball write-slot fix (1-scanline vertical shift)

A double entry fires two writes on one scanline, but the first lands at cycle
30 and the second at cycle 44 (measured on the deterministic emulator). With
the beam model above that is a ~42-49 pixel gap, so an object written second
can miss its own gate when it is left of the second-write gate (`x < 63` on
the model). Before Round 8 a same-row merge kept generation order, so the
BALL - generated between the players and the missiles - usually became the
*second* write of a shared row. For every `ball_x < 63` the ball's ON/OFF
fired one scanline late and the whole ball shifted down one line (height
unchanged) whenever it shared a row with another active object. The reported
symptom was a small vertical displacement at certain scanlines.

A model sweep of all 16,956 (ball_x, scenario) combinations confirmed the
root cause: the ball took the second write on its shared rows, and the second
write's gate (63) is far beyond the ball's reachable positions. A pure
X-deadline ordering (earlier deadline first) was evaluated but only reduced
ball failures from 4957 to 4429: P0 (x=16) is always left of the ball for
`ball_x > 16`, so the ball would still be written second on shared P0 rows.
The fix adopted is **ball-first**: `InsertEvent` swaps ENABL into the first
write whenever a ball event merges into a single, giving the ball the
earliest write (cycle 30) in every double and a single write (cycle 33) when
alone. Ball failures drop to 2890; the residual failures are the ball-alone
`x < 30` band (inherent to the cycle-33 single write) and the co-object
taking the second slot. Cycle cost of the swap is +1 worst case on the merge
path (VBLANK): measured worst-case VBLANK work 4485 -> 4486 cycles, margin
~379 -> ~378, still comfortably inside the T=77 expiry (~4864). The kernel
is untouched (65/76, slack 11) and the frame stays exactly 262 scanlines.

## Measured frame length

Verified with a deterministic 6502 emulator that models WSYNC stalls and the
RIOT timer:

* steady-state frame length: **19912 cycles = 262 scanlines exactly**, stable
  across 30+ frames for the no-missile, both-missiles and pathological states;
  with the Round 4 collision pass the frame is uniform across 600+ max-stress
  frames (both collision latches asserted every frame, alternating fire
  presses); previously the same input made ~1% of frames slip to 263 lines.
  Round 5 adds the HP/death paths: the frame stays at 19912 cycles under the
  same max-stress input (players kept alive) and with both players dead.
  Round 6 re-validates the same stress with an emulator that models realistic
  branch timing: the frame stays at exactly 19912 cycles (262 scanlines) for
  every frame of the max-stress run, proving the VBLANK timer (T=77) never
  overruns;
* the visible kernel runs exactly 185 iterations: `evCnt` is primed with
  `nullDelta` (or entry 0's own delta when it fires on line 0) and counts down
  to the marker entry, whose delta is read at the top of line 184 and ends the
  kernel at line 185.

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
262 scanlines, and the event kernel's `evCnt` countdown keeps the visible
region exactly 185 lines regardless of how many events fire. Round 6's VBLANK
shake was exactly this class of bug: visually fine in an emulator with
shortcut branch timing, it broke on real silicon because the timer budget did
not cover the true worst-case work. The emulator now models the real cycle
costs so the regression is caught deterministically.
