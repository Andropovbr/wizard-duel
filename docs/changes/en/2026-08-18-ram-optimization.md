# Change: RAM optimization with variable-size event entries

## Objective

Round 3 finished with 122 of 128 RIOT bytes used (94.5%), leaving only 6
bytes free. This round ("3.1") reclaims RAM without changing any gameplay:
the target was to fit the game comfortably under 64 bytes so future features
(e.g. collisions, scoring) have room, while preserving every Round 3
behavior (players, ball, two missiles, fire input, 262 scanlines, kernel
within 76 cycles, ROM within 4 KiB).

## Added

* **Variable-size event entries**: `evTbl` entries are no longer a fixed
  5-byte two-write record. A single entry is 3 bytes `[delta, reg1|$80, val1]`
  (bit 7 of the register index marks it); a double entry is 5 bytes
  `[delta, reg1, val1, reg2, val2]`. The kernel dispatches on the flag bit
  with a single `BMI`; a scanline that needs only one write skips the second
  write entirely (54 cycles instead of 65).
* **Direct insertion builder**: `BuildEvents` no longer appends `(row, reg,
  val)` records and sorts an order array. It inserts each object boundary
  event straight into `evTbl` in row order, so the 30-byte records buffer,
  the 10-byte order array and the record counter are gone.
  * `InsertEvent` scans the table comparing rows; on a matching row it merges
    a single into a double (`ShiftBy2`, tail shifted by 2) or bumps an
    already-double row by +1 and continues. Otherwise `ShiftBy3` shifts the
    tail by 3 and writes a new single.
  * `ConvertDeltas` rewrites the stored rows in place as kernel deltas
    (first delta = row+1, following deltas = row - prevRow), leaving the
    `$FF` terminator at the end.
* **Packed missile state**: `m_active` holds both active flags (bit0 M0,
  bit1 M1), replacing `m0_active` and `m1_active`.
* **Packed fire state**: boot synchronisation moved into bit 7 of `fire_prev`
  (`FIRE_SYNC`), replacing the separate `fire_sync` byte.
* **New runtime frame-timing test** `tests/test_frame_timing.py`: drives the
  deterministic emulator across many frames and asserts frame stability (262
  scanlines), that the table length never exceeds `EV_TBL_SIZE = 31` under
  aggressive fire input, and that missiles actually spawn and despawn through
  the event pipeline.
* **RAM regression gates** in `tools/regression.py`: `RAM_PRESSURE_WARN_PCT =
  75.0` / `RAM_PRESSURE_STRONG_PCT = 90.0` (of a 64-byte project budget) emit
  soft warnings, and using more than the `PROJECT_RAM_BUDGET = 64` bytes is a
  hard CI failure; RAM growth is also compared by absolute bytes and
  percentage.

## Changed

* `src/main.asm`: kernel rewritten for variable-size entries (three paths:
  18 / 54 / 65 cycles, one `BMI` dispatch added); old `AddEvent`,
  `SortEvents`, `EmitEvents`, `BubbleOrder` replaced by `InsertEvent`,
  `ShiftBy2`, `ShiftBy3`, `ConvertDeltas`; RAM block rewritten to 48 bytes;
  `UpdatePlayers` re-reads `SWCHA` for each direction (the `joystate` byte is
  gone); `UpdateMissiles` uses the packed `m_active` mask and the `FIRE_SYNC`
  bit.
* `src/constants.inc`: `EV_TBL_SIZE = 31`, `EV_SINGLE_FLAG = $80`,
  `M0_BIT`/`M1_BIT`, `FIRE_SYNC`.
* `tools/emu6502.py`: added `BMI` (opcode 0x30) to the emulator so the frame
  tests can execute the kernel dispatch.
* `tools/benchmark.py`: the kernel worst-case simulation now reports the
  two-write event path (65 cycles).
* `tools/regression.py`: RAM pressure/budget gates (see Added).
* Tests updated: `test_timing.py` (three kernel paths, two-write walker),
  `test_events.py` (rewritten to model the byte-list builder), `test_rom.py`
  (new symbols), `test_memory.py` (48 bytes), `test_ball.py` (RAM budget
  comment), `test_missile_fire.py` (packed state decoding),
  `test_regression.py` (new RAM base + pressure/budget cases).
* Docs updated (EN + pt-BR).

## Removed

* `joystate` RAM byte (input is re-read from the port each use).
* `evIdx` RAM byte (the kernel holds the table offset in Y across the whole
  frame instead of storing it between lines).
* `fire_sync` RAM byte (folded into bit 7 of `fire_prev`).
* `m0_active` / `m1_active` bytes (folded into the `m_active` mask).
* `events` (30B), `evCount` (1B), `evOrder` (10B), and the builder temps
  (8B) - the direct insertion builder needs no record/order scratch space.
* `AddEvent` / `SortEvents` / `EmitEvents` / `BubbleOrder` subroutines.

## Technical Reasoning

### Why variable-size entries

Round 3's fixed 5-byte entries were a simplification: "every entry always
performs two writes" made the event path straight-line, but it forced every
object boundary to consume 5 bytes even when only one register needed
writing, and it pushed the kernel to 69 cycles. Two observations made
variable entries cheap:

1. The table is built in RAM every frame and indexed by Y, so the kernel can
   read the flag bit from the entry itself and branch once (`BMI`). A single
   conditional branch in the event path is acceptable: both outcomes are
   straight-line, so both have fixed timing (54 vs 65 cycles).
2. Every write value is an enable register value (`$00`, `PADDLE_BITS`,
   `BALL_ENABLE`, `MISSILE_ENABLE`), none of which sets bit 7, so the flag bit
   can live in the register-index byte without stealing a value bit.

### Why direct insertion instead of records + sort

The Round 3 builder wrote records and sorted an order array specifically to
keep the per-frame CPU cost inside VBLANK. With variable entries there is no
fixed record size to sort cheaply, and the 40 bytes of scratch would defeat
the memory goal. Inserting directly into the table costs more cycles (shifts
of a variable tail) but stays well within the 69*64 = 4416-cycle VBLANK
window; the saved 40 bytes of RAM are worth far more to the project than the
spare VBLANK cycles.

### Why the ShiftBy loops use `CPX`/`BNE` and not `CPX`/`BCS`

The first implementation counted shifts with `DEX` and terminated with
`CPX tempCount; BCS`. `DEX` wraps from 0 to $FF, so when the loop reached
zero (and with the register values involved) the `BCS` did not always
terminate, causing an infinite loop that corrupted memory and the stack.
`CPX tempCount; BNE` is the correct termination: it exits as soon as X equals
the saved index, independent of the wrap-around behavior of `DEX`.

### Why `InsertEvent` pushes the row

`InsertEvent` records the current row, register and value and then may call
`ShiftBy2`/`ShiftBy3`. Each subroutine needs the register/value on the stack,
and the merge path needs the row again after the shift to decide whether to
advance the scan. A missing `PHA` for the row produced a stack imbalance: the
routine popped more bytes than it pushed, returning to a corrupted return
address. All three values are now pushed and popped symmetrically on every
path.

### Why the table is bounded at 31 bytes

The table starts as a 1-byte `$FF` terminator. Ten object boundaries are
inserted (P0/P1 on/off, ball on/off, M0/M1 on/off). A single is 3 bytes, a
double 5. The worst case for size is every boundary on its own row (no
merging): 10 singles * 3 = 30 bytes plus the 1-byte terminator = 31 bytes.
Merging a pair into a double only reduces the total (2 singles = 6 bytes
become 5). `EV_TBL_SIZE = 31` is therefore an exact hard bound; a runtime
test asserts the builder never exceeds it under aggressive fire input.

### Why the two-write kernel path is cheaper than Round 3

The new double path reads the flag byte once and, because the single path is
shorter, the double path no longer needs the `STY evIdx` round trip between
the write pair and the next-delta load - Y stays live across the whole frame.
Worst path drops from 69 to 65 cycles (slack 7 -> 11).

### Why the write-time gates moved to 30/72

With the two writes now at cycles 30..33 and 44..47 (double path), a write
applies to the current scanline only if the beam has not yet passed the
object's horizontal position. Using the standard beam model (pixel p reached
at cycle ~(p+69)/3), the gates are x >= 30 and x >= 72. P0 (x=16) and P1
(x=136) are far outside both bands, so their behavior is identical to Round 3;
no object in this round sits inside the 30..32 / 72..74 pixel bands.

## Timing Impact

Before (Round 3):
- Frame scanlines: 262
- Kernel worst path: 69 / 76 cycles (two-write event line, slack 7)
- Kernel best path: 18 / 76 cycles (non-event line)

After (Round 3.1):
- Frame scanlines: 262 (stable; runtime test runs many frames)
- Kernel worst path: 65 / 76 cycles (two-write event line)
- Kernel single-write path: 54 / 76 cycles (new)
- Kernel best path: 18 / 76 cycles (non-event line)
- Slack: 11 cycles on the worst event line (was 7)

## Memory Impact

Before (Round 3):
- ROM: 1296 / 4096 bytes (31.6%)
- RAM: 122 / 128 bytes (95.3%)

After (Round 3.1):
- ROM: 1296 / 4096 bytes (31.6%)
- RAM: 48 / 128 bytes (37.5%), 80 bytes free

RAM dropped 74 bytes (122 -> 48) with no ROM growth: the variable-size table
(31 vs 55 bytes), no record/order buffers (40 bytes), and the four packed
bytes all contribute. The game now sits at 48 of a 64-byte project budget.

## Tests

Added `tests/test_frame_timing.py` (frame stability, aggressive-fire table
bound, missile spawn/despawn via the event pipeline). Rewrote
`tests/test_events.py` to model the byte-list builder (insert, merge single
into double, bump double row, shift 2/3, convert deltas, firing rows).
Updated `test_timing.py`, `test_rom.py`, `test_memory.py`, `test_ball.py`,
`test_missile_fire.py`, `test_regression.py`. All 143 tests pass; build
reports 1296 ROM / 48 RAM.

## Known Limitations

* `BuildEvents` cost a few hundred more VBLANK cycles than Round 3 (shifts of
  a variable tail); still comfortably inside the VBLANK window.
* A transient same-row double bump (row+1) can still occur during insertion,
  but only once per build and never beyond the table bound.
* The runtime frame test asserts scanline count and behavior, not exact cycle
  totals (the emulator's cycle counter is approximate).
* RAM usage is now measured at 48 bytes; the regression suite compares against
  the Round 1 persisted baseline, so the 122-byte Round 3 spike is visible in
  the history rather than hidden.

## Next Logical Steps

* Missile/player and ball/player collisions now have 80 bytes of RAM
  headroom.
* Consider a separate collision state byte or a small HUD.
* Move part of the event build to OVERSCAN if VBLANK pressure ever returns.