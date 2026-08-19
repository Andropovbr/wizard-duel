# Wizard Duel - Architecture

Round 3 adds basic projectiles and replaces the Round 2 branchless display
kernel with an event-driven one. Round 3.1 shrinks the RAM footprint from 122
to 48 bytes by switching the event table to variable-size entries and
removing the separate record/order scratch buffers.

Features:

* a stable NTSC frame of exactly 262 scanlines
* two TIA players visible simultaneously (P0 on the left, P1 on the right),
  rendered as simple vertical paddles
* vertical-only movement driven by joystick 1 (P0) and joystick 2 (P1)
* a TIA Ball object that moves continuously and bounces off the four arena
  edges
* each player can fire one missile with the joystick fire button (INPT4 for
  P0, INPT5 for P1); missiles fly horizontally at 2 px/frame and despawn at
  the arena edges
* cross-fire collisions (M0 -> P1, M1 -> P0) are detected by the TIA latches
  and consume HP: each player starts with `PLAYER_START_HP = 3` hit points
  (Round 5)

There is intentionally no magic system, AI, scoring or HUD yet; the gameplay
rules are expected to evolve in later rounds without requiring architectural
changes. The ball does not interact with the players or missiles in this
round. A dead player keeps occupying the arena but is not rendered and
cannot fire; there is no victory/game-over transition yet.

## Event-driven kernel

With a second pair of objects (the missiles) the Round 2 branchless kernel no
longer fits in the 76-cycle scanline budget (it needed ~98 cycles for two
players, the ball and two missiles). Instead of computing every object's
enable on every scanline, `BuildEvents` runs during VBLANK and writes a small
table (`evTbl`) describing the register writes each scanline must perform.
The kernel then only counts down to the next entry and applies its writes,
keeping every scanline well under 76 cycles (65 worst case, see
[timing.md](timing.md)).

Each table entry is variable size (Round 3.1):

| byte | meaning                                    |
| ---- | ------------------------------------------ |
| 0    | delta: scanlines until this entry fires    |
| 1    | register index of the first write          |

If the entry has a second write, bit 7 of byte 1 is clear and two more bytes
follow:

| byte | meaning                                    |
| ---- | ------------------------------------------ |
| 2    | value of the first write                   |
| 3    | register index of the second write         |
| 4    | value of the second write                  |

If bit 7 of byte 1 is set, the entry is a single write and only one value
byte follows (the value carries no bit 7 because it is always an enable
register write of `$00`, `PADDLE_BITS`, `BALL_ENABLE` or `MISSILE_ENABLE`,
none of which set bit 7). The kernel dispatches on that bit with a single
`BMI`:

* single entry (3 bytes): delta + `reg|$80` + value
* double entry (5 bytes): delta + reg + value + reg + value

Both paths are straight-line, so event lines keep deterministic timing (54
cycles single, 65 double, 11 cycles slack on the worst path). A single event
line needs no second write at all; when no event fires, the kernel spends
only 18 cycles before `WSYNC`.

Register indices are offsets from `EV_WRITE_BASE = AUDV1 ($1A)`: index 0
writes AUDV1 (a harmless dummy), 1..5 address GRP0..ENABL.

Deltas: the first entry fires on line `delta - 1`, every following entry
fires `delta` lines after the previous one, so `BuildEvents` computes
`delta(first) = row + 1` and `delta(next) = row - prevRow`. The kernel counts
its 192 lines with a RAM countdown (`scanCnt`) rather than the X register,
because the event code uses `TAX` as the register index and would clobber an
X line counter on every event line.

## Code layout

`src/main.asm` contains the complete program in a single `$F000-$FFFF` ROM
bank (4 KiB, no bankswitching). `src/constants.inc` holds all hardware
register addresses and build-time constants.

| Address  | Content                                        |
| -------- | ---------------------------------------------- |
| `$F000`  | `Reset` (initialization)                       |
| `$F055`  | `StartOfFrame` (VSYNC + VBLANK + kernel + OS)  |
| `$F100`  | `KernelLoop` (event-driven display kernel)     |
| `$F150`  | `OverscanWait` (collision + hit effects + WSYNC loop) |
| `$F160`  | `UpdatePlayers` (joystick input + movement)    |
| `$F199`  | `UpdateBall` (ball movement + bounce)          |
| `$F1D0`  | `UpdateMissiles` (fire buttons, movement)      |
| `$F265`  | `ProcessCollisions` (fixed-cost, branchless)   |
| `$F2A0`  | `newActiveTbl` (m_active update table)         |
| `$F300`  | `ProcessHitEffects` (HP damage + fire lock)    |
| `$F338`  | `PositionPlayers` (RESP0/RESP1 + HMP + HMOVE)  |
| `$F35B`  | `PositionBall` (RESBL + HMBL)                  |
| `$F36D`  | `PositionMissiles` (RESM0/RESM1 + HMM)         |
| `$F39C`  | `BuildEvents` (insert events in row order)     |
| `$F424`  | `InsertEvent` (insert/merge a table entry)     |
| `$F49A`  | `ShiftBy2` (extend a single into a double)     |
| `$F4A8`  | `ShiftBy3` (insert a new single entry)         |
| `$F4B6`  | `ConvertDeltas` (rows -> kernel deltas)        |
| `$F4E7`  | `PosObject` (generic RESPx/HMPx)               |
| `$F500`  | `fineAdjustBegin` (page-aligned HMP table)     |
| `$FFFA`  | NMI / RESET / IRQ vectors                      |

There are no sprite graphics tables: both players are solid `PADDLE_BITS`
rectangles drawn through the event table. The exact addresses may change
between builds; the automated tests resolve them from the symbol/listing
files rather than hard-coding them.

## Execution flow per frame

```
StartOfFrame
 ├─ VSYNC   3 scanlines  (three explicit WSYNC writes)
 ├─ VBLANK 57 scanlines  (TIM64T = 69; gameplay + event build run here)
 │   ├─ UpdatePlayers    read SWCHA, move P0/P1, clamp to the arena
 │   ├─ UpdateBall       move the ball, bounce off the arena edges
 │   ├─ UpdateMissiles   read INPT4/INPT5, fire/move/despawn missiles
 │   ├─ PositionPlayers  RESP0/RESP1 + HMP0/HMP1 coarse/fine placement
 │   ├─ PositionBall     RESBL + HMBL placement
 │   ├─ PositionMissiles RESM0/RESM1 + HMM0/HMM1 placement
 │   └─ BuildEvents      rebuild the event table for the visible kernel
├─ KERNEL 192 scanlines (explicit WSYNC loop; render events only)
  └─ OVERSCAN 10 scanlines (ProcessCollisions + ProcessHitEffects + fixed WSYNC loop; back to StartOfFrame)
```

Gameplay input, movement and event building happen during VBLANK; the visible
kernel only applies the precomputed register writes. VBLANK is larger than in
Round 2 (57 vs 37 lines) to give `BuildEvents` room; OVERSCAN shrinks to 10
lines to keep the frame at 262.

## Input

Joysticks are read from the RIOT I/O port `SWCHA` (`$0280`), which is active
low: a bit is 0 when the corresponding direction is pushed. Only the
vertical directions are used this round:

| Port | Direction | SWCHA bit |
| ---- | --------- | --------- |
| P0 (left, joystick 1) | up    | D4 |
| P0 (left, joystick 1) | down  | D5 |
| P1 (right, joystick 2)| up    | D0 |
| P1 (right, joystick 2)| down  | D1 |

`UpdatePlayers` samples `SWCHA` and applies at most one up/down step per
player, guarding the arena boundaries so the position never wraps. The value
is consumed immediately; no `joystate` RAM variable is needed (a Round 3.1
memory saving).

## Missiles

Each player can fire one missile with the fire button. Fire buttons are read
through the TIA INPT latches: bit 7 of `INPT4` (P0) and `INPT5` (P1) is 0
while pressed. `UpdateMissiles` samples both buttons independently each frame
and fires on the **rising edge** of the button (released -> pressed), and only
while that player's missile is inactive:

* holding the button does not produce a stream of missiles (`fire_prev`
  remembers the previous frame's state);
* a rising edge while a missile is still flying neither spawns a second one
  nor resets the existing one;
* releasing the button only rearms the input, so the next released -> pressed
  transition fires again.

Missile state is packed into two bytes: `m_active` holds both active flags
(bit 0 = M0, bit 1 = M1) and `fire_prev` packs the two previous-frame button
bits plus bit 7 as the boot-sync flag.

**Boot synchronisation**: on real hardware (and in Stella) the TIA INPT
latches read the fire lines as pressed for the first frames after RESET. The
first `UpdateMissiles` call after power-on therefore only adopts the real
button state into `fire_prev` (setting the `FIRE_SYNC` bit 7), it never
fires. This guarantees that booting with FIRE released produces no shot, and
booting with FIRE held produces no automatic shot either - the player must
release and press again.

A missile is `MISSILE_HEIGHT = 4` scanlines tall and `MISSILE_WIDTH = 2`
pixels wide (set through the NUSIZ0/NUSIZ1 missile size bits). It spawns
`MISSILE_SPAWN_OFFSET = 4` rows below its player, keeps that row while
flying, moves horizontally at `MISSILE_SPEED = 2` px/frame and despawns at
the arena edge:

* M0 (left player): starts at x = 18, moves right, despawns at x > 158
* M1 (right player): starts at x = 134, moves left, despawns at x < 2

Missiles render in the ball's color (`COLUPF`) and, like the ball, use the
`input = x + 8` horizontal compensation (they are TIA Missile objects, not
Player objects).

## Collision and hit points

Cross-fire collisions are detected by the TIA collision latches and resolved
in the overscan, keeping the visible kernel purely render-focused:

* **Detection** (`ProcessCollisions`, overscan init): reads CXM0P/CXM1P,
  records the cross-fire hits M0 -> P1 and M1 -> P0 in the one-byte
  `hit_flags` bitfield (bit 0 = P0, bit 1 = P1; simultaneous hits both
  count), clears the scoring missile's bit in `m_active`, and writes `CXCLR`
  so a hit is never counted twice. Own-player bits (M0 x P0, M1 x P1) are
  ignored. The pass is branchless and fixed-cost (84 cycles) so the fixed
  WSYNC-counted overscan stays exact.
* **Damage** (`ProcessHitEffects`, same overscan, after collisions): removes
  one HP from the hit player (no underflow below 0; `hit_flags` is read but
  not cleared here - `ProcessCollisions` overwrites it next frame, so each
  hit is consumed exactly once) and forces a dead player's FIRE bit in
  `fire_prev` to "pressed" so `UpdateMissiles` never sees a rising edge
  (the lock is recomputed every overscan because `UpdateMissiles` rewrites
  `fire_prev` every VBLANK). The routine is page-aligned and branchy but
  bounded to a 60..80-cycle window that still lands the first overscan WSYNC
  on the same boundary on every path.
* **Death**: a player at 0 HP is not rendered (`BuildEvents` skips its P0/P1
  events) and cannot fire, but keeps its position and movement; a missile
  that was already flying survives its owner's death. There is no
  victory/game-over transition yet - the round simply continues.

## Rendering

The visible kernel is event-driven (see above). Both players are drawn as
single-copy TIA sprites with different colors: P0 is red (`COLUP0 = $46`) and
P1 is blue (`COLUP1 = $84`). Each sprite is a solid rectangle of `%00111100`
(a 4-pixel-wide paddle) on `PLAYER_HEIGHT = 12` rows. The ball is the TIA
Ball object, 4 pixels wide (CTRLPF D5:D4 = `%10`) and 4 rows tall. Missiles
are the TIA Missile objects, 2 pixels wide and 4 rows tall.

The event table records an ON event (turn the register on) and an OFF event
(turn it off) at each object's display rows:

| object | ON event                              | OFF event                       |
| ------ | ------------------------------------- | ------------------------------- |
| P0     | `(P0Y, GRP0, PADDLE_BITS)`            | `(P0Y+12, GRP0, 0)`             |
| P1     | `(P1Y, GRP1, PADDLE_BITS)`            | `(P1Y+12, GRP1, 0)`             |
| Ball   | `(ball_y, ENABL, BALL_ENABLE)`        | `(ball_y+4, ENABL, 0)`          |
| M0     | `(m0_y, ENAM0, MISSILE_ENABLE)`       | `(m0_y+4, ENAM0, 0)`            |
| M1     | `(m1_y, ENAM1, MISSILE_ENABLE)`       | `(m1_y+4, ENAM1, 0)`            |

`BALL_ENABLE` and `MISSILE_ENABLE` are `%00000010`: the TIA only samples bit 1
of the enable registers (verified against the Stella source), so the old
`$FF` value was unnecessary.

Horizontal placement is fixed every frame with the classic
RESP0/RESP1/RESM0/RESM1/RESBL + HMP + HMOVE technique: a coarse strobe
positions the object to within 15 pixels and a fine `HMPx`/`HMMx`/`HMBL`
offset from the page-aligned `fineAdjustTable` finishes the job. The `HMOVE`
that applies the offsets is written immediately after a `STA WSYNC` on the
last VBLANK line, as the Stella Programmer's Guide requires.

Measured on the target (TIA/Stella), the routine renders a player at
`15*q + (s - 7)` for `q >= 1` and at `3 + (s - 7)` for `q = 0`, where
`q = input / 15` and `s = input mod 15`. The ball and the missiles render
1 pixel left of a player for the same input, so `PositionBall`/`PositionMissiles`
pass `x + 8` (or `x + 5` when that is below 15) and the players pass `X + 7`
(or `X + 4`).

## Ball movement and bounce

`UpdateBall` moves the ball one pixel per frame on both axes at constant
speed. `ball_dx`/`ball_dy` store the direction step (+1 or $FF). Bouncing is
implemented by reversing a direction when the ball reaches an exact arena
edge before moving, so the position is always clamped to the valid range and
can never wrap through an unsigned underflow. `ball_y` is the first display
row; the ball occupies rows `ball_y .. ball_y + 3`. The ball does not collide
with the players or the missiles; it bounces only off the four edges of the
play area.

## Event table builder

Round 3.1 replaces the record/order/emit pipeline with a direct insertion
builder: `BuildEvents` resets the table to a single `$FF` terminator and then
inserts each object's ON/OFF events straight into `evTbl` in row order, so no
separate record or order buffers exist (the 40 bytes they used in Round 3 are
gone). Because the entries are variable size, insertion needs an explicit
move loop instead of a stable sort:

1. `InsertEvent` scans the table comparing entry rows. On a matching row it
   merges:
   * a single entry -> `ShiftBy2` shifts the tail by 2 and writes the second
     value (the merged entry becomes a 5-byte double);
   * an already-double entry -> the row is bumped to row+1 and the scan
     continues (this can only happen transiently during a single build, so
     the table never exceeds its bound).
   Otherwise `ShiftBy3` shifts the tail by 3 and writes a new 3-byte single.
2. After all events are inserted, `ConvertDeltas` rewrites the rows in place
   as kernel deltas (first delta = row+1, next deltas = row - prevRow),
   leaving the `$FF` terminator at the end of the table.

Because a 3-byte single can merge into a 5-byte double, the worst-case table
size is no longer 10 x 5 bytes: with 10 object boundaries and at most one
double per row, the table needs at most 31 bytes. `EV_TBL_SIZE = 31` is a
hard bound; `tblLen` tracks the current length and a test asserts it never
exceeds the bound under aggressive fire input.

The table ends with a terminator entry whose delta (`$FF`) can never fire
inside the 192-line kernel.

## Variable allocation

51 of 128 bytes of RIOT RAM are used (48 in Round 3.1, +1 for `hit_flags`
in Round 4, +2 for `p0_hp`/`p1_hp` in Round 5):

| Address    | Name        | Purpose                              |
| ---------- | ----------- | ------------------------------------ |
| `$80`      | `P0Y`       | player 0 vertical position           |
| `$81`      | `P1Y`       | player 1 vertical position           |
| `$82`      | `p0_hp`     | player 0 hit points (0 = dead)       |
| `$83`      | `p1_hp`     | player 1 hit points (0 = dead)       |
| `$84`      | `ball_x`    | ball leftmost visible pixel          |
| `$85`      | `ball_y`    | ball first display row               |
| `$86`      | `ball_dx`   | horizontal direction step            |
| `$87`      | `ball_dy`   | vertical direction step              |
| `$88-$89`  | `m0_x/m0_y` | missile 0 position                   |
| `$8A-$8B`  | `m1_x/m1_y` | missile 1 position                   |
| `$8C`      | `m_active`  | packed missile active mask (M0/M1)   |
| `$8D`      | `hit_flags` | collision results (P0/P1 hit bits)   |
| `$8E`      | `fire_prev` | packed fire edge + boot-sync state   |
| `$8F-$90`  | `evCnt/scanCnt` | kernel state                     |
| `$91-$AF`  | `evTbl`     | event table (variable size, max 31B) |
| `$B0-$B2`  | `evRow/tempCount/tblLen` | builder working storage |

The savings come from: variable-size table entries (31 vs 55 bytes), no
record/order buffers (0 vs 40 bytes), no `joystate` (re-read `SWCHA`), packed
missile flags (one byte for two), no separate `fire_sync` (bit 7 of
`fire_prev`), and no `evIdx` (the kernel scans the table linearly).

## Why VBLANK for gameplay

The visible kernel has a 76-cycle budget per scanline. Running the joystick
decoding, movement, bounce checks and the event-table build there would add
branch-heavy, data-dependent timing to a rendering path that must stay
deterministic. Moving them to VBLANK (see [timing.md](timing.md)) keeps the
kernel stable at exactly one scanline per iteration regardless of input or
game state.
