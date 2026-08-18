# Change: Basic projectiles and an event-driven kernel

## Objective

Implement Round 3 "basic projectiles" for Wizard Duel: each player can fire
one missile with the joystick fire button. Adding a second pair of objects
(the missiles) made the Round 2 branchless display kernel impossible (it
needed ~98 cycles for two players, the ball and two missiles against the
76-cycle scanline budget), so the visible kernel was redesigned as an
event-driven kernel driven by a table rebuilt every frame during VBLANK.

## Added

* **Missiles**: `UpdateMissiles` reads the fire buttons (INPT4 for P0, INPT5
  for P1, bit 7 = 0 pressed) and spawns a missile on the rising edge of the
  button. A missile is 2 px wide (NUSIZ0/1 missile-size bits) and 4 rows
  tall, spawns `MISSILE_SPAWN_OFFSET = 4` rows below its player, flies
  horizontally at `MISSILE_SPEED = 2` px/frame and despawns at the arena
  edge (M0 moves right from x=18, M1 moves left from x=134). `fire_prev`
  tracks the previous frame's button state so holding the button does not
  produce a stream of missiles.
* **Event-driven kernel**: the visible kernel no longer computes object
  enables. `BuildEvents` (VBLANK) writes a 5-byte-per-entry table (`evTbl`)
  `[delta, reg1, val1, reg2, val2]`; the kernel counts down to the next
  entry and applies its two register writes. The 192-line countdown lives in
  RAM (`scanCnt`) so the event code can freely use `TAX` as the register
  index.
* **Event builder**: `AddEvent` appends 3-byte `(row, reg, val)` records;
  `SortEvents` insertion-sorts a single-byte order array (`evOrder`) by row;
  `EmitEvents` walks the sorted order, merging at most two same-row records
  into one entry and bumping a pathological third record to row+1
  (`BubbleOrder` restores order). A terminator entry (`delta = $FF`) can
  never fire inside the 192-line kernel.
* **BALL_ENABLE fix**: the enable value is now `%00000010`. The TIA only
  samples bit 1 of the enable registers (verified against the Stella source:
  `myEnam = value & 0x02`), so the old `$FF` was unnecessary.
* **Ball convention change**: `ball_y` is now the first display row
  (display rows `ball_y .. ball_y + 3`), `BALL_Y_MAX = 188`.

## Changed

* `src/main.asm` kernel rewritten (event-driven); the branchless rectangle
  blocks and the Round 2 ball-enable tail are gone.
* Frame structure: VBLANK 37 -> 57 lines, OVERSCAN 30 -> 10 lines (timers
  43/37 -> 69/11) to give `BuildEvents` room while keeping 262 lines.
* `tools/common.py` `ram_usage()` now resolves symbolic `DS` sizes (e.g.
  `DS EV_TBL_SIZE`), which the Round 3 RAM uses.
* `tests/test_timing.py` `_resolve_constant` now handles `*` and bails out
  instead of recursing forever on unresolvable expressions.
* Tests updated for the new kernel/constants; a new `tests/test_events.py`
  models the event builder (deltas, merges, collision resolution).
* Docs updated (EN + pt-BR).

## Technical Reasoning

### Why the event-driven kernel

With five objects (2 players + ball + 2 missiles), branchless per-scanline
enable computation needs ~98 cycles > 76. The event kernel turns the
per-object work into a VBLANK-time table build (where cycles are plentiful)
and keeps the display loop tiny: 18 cycles on a non-event line and 69 on a
two-write event line (7 cycles of slack).

### Why the RAM line countdown

The kernel's event code uses `TAX` (register index for `STA $1A,X`). With an
X line counter this clobbers the counter on every event line, stretching the
frame (measured ~339 lines). Moving the 192-line countdown to RAM (`scanCnt`)
keeps the frame exactly 262 lines.

### Why the order-array sort

The first builder kept records sorted in place (3-byte shifts), costing
~3.8k cycles worst case, which exceeded the VBLANK window together with the
other logic. Sorting a 1-byte `evOrder` array (1-byte shifts) plus a linear
emit cut the builder to ~3.4k cycles worst case, fitting the `69 * 64 =
4416`-cycle window with ~280 cycles of margin. A 3-way collision (three
objects sharing a row) is bumped to row+1 so no scanline ever needs more than
two writes.

### Why the timer/line-count tuning

Timer values were tuned empirically against a deterministic 6502 emulator
that models WSYNC stalls and the RIOT timer. The frame is exactly 262
scanlines (19912 cycles) and stable across all tested states.

## Timing Impact

Before (Round 2):
- Frame scanlines: 262
- Kernel worst path: 62 / 76 cycles (branchless)

After (Round 3):
- Frame scanlines: 262 (stable, verified over 30+ frames in the emulator)
- Kernel worst path: 69 / 76 cycles (two-write event line)
- Kernel best path: 18 / 76 cycles (non-event line)
- Slack: 7 cycles on the event line

The visible kernel now has variable per-line cost (18 vs 69) but each line is
still far under 76 cycles and the total line count is fixed by `scanCnt`.

## Memory Impact

Before (Round 2):
- ROM: 528 / 4096 bytes (12.9%)
- RAM: 7 / 128 bytes

After (Round 3):
- ROM: 1296 / 4096 bytes (31.6%)
- RAM: 121 / 128 bytes (94.5%)

RAM grew sharply because the event table (55 bytes) and the records/order
buffers (40 bytes) are committed per-frame working storage. Only 7 bytes
remain free; this is legal but a deliberate pressure point to watch in later
rounds.

## Tests

Added `tests/test_events.py` (7 tests: deltas, firing rows, merging,
3-way collision bump, terminator, per-line math). Updated `test_timing.py`
(kernel cycle walker for the event kernel), `test_ball.py` (ball constants,
RAM, event-kernel structure), `test_rom.py` (symbols, kernel register
writes), `test_positioning.py` (missile compensation), `test_memory.py`
(RAM 121), `test_regression.py` (BASE metrics). All 111 tests pass.

## Known Limitations

* RAM is at 121/128 bytes; future features need to reuse or reclaim event
  working storage.
* The ball and missiles do not interact with the players (no collisions).
* A 3-way row collision shifts one object one scanline for that frame (rare,
  documented, deterministic).
* Runtime frame validation uses a development-time emulator; CI validates the
  frame statically.

## Next Logical Steps

* Paddle/ball and missile/player collisions.
* Move some game logic to OVERSCAN if VBLANK pressure returns.
* Reclaim RAM (e.g. pack the event table or reuse the order array).
