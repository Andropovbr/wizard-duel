# Wizard Duel - Architecture

Round 3 adds basic projectiles and replaces the Round 2 branchless display
kernel with an event-driven one:

* a stable NTSC frame of exactly 262 scanlines
* two TIA players visible simultaneously (P0 on the left, P1 on the right),
  rendered as simple vertical paddles
* vertical-only movement driven by joystick 1 (P0) and joystick 2 (P1)
* a TIA Ball object that moves continuously and bounces off the four arena
  edges
* each player can fire one missile with the joystick fire button (INPT4 for
  P0, INPT5 for P1); missiles fly horizontally at 2 px/frame and despawn at
  the arena edges

There is intentionally no magic system, HP, AI, collisions, scoring or HUD
yet; the gameplay rules are expected to evolve in later rounds without
requiring architectural changes. The ball and the missiles do not interact
with the players in this round.

## Event-driven kernel

With a second pair of objects (the missiles) the Round 2 branchless kernel no
longer fits in the 76-cycle scanline budget (it needed ~98 cycles for two
players, the ball and two missiles). Instead of computing every object's
enable on every scanline, `BuildEvents` runs during VBLANK and writes a small
table (`evTbl`) describing the register writes each scanline must perform.
The kernel then only counts down to the next entry and applies its writes,
keeping every scanline well under 76 cycles (69 worst case, see
[timing.md](timing.md)).

Each table entry is 5 bytes:

| byte | meaning                                    |
| ---- | ------------------------------------------ |
| 0    | delta: scanlines until this entry fires    |
| 1    | register index of the first write          |
| 2    | value of the first write                   |
| 3    | register index of the second write         |
| 4    | value of the second write                  |

Register indices are offsets from `EV_WRITE_BASE = AUDV1 ($1A)`: index 0
writes AUDV1 (a harmless dummy), 1..5 address GRP0..ENABL. Every entry always
performs two writes, so the event path is straight-line code.

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
| `$F04F`  | `StartOfFrame` (VSYNC + VBLANK + kernel + OS)  |
| `$F100`  | `KernelLoop` (event-driven display kernel)     |
| `$F142`  | `OverscanWait`                                 |
| `$F14A`  | `UpdatePlayers` (joystick input + movement)    |
| `$F184`  | `UpdateBall` (ball movement + bounce)          |
| `$F1BB`  | `UpdateMissiles` (fire buttons, movement)      |
| `$F238`  | `PositionPlayers` (RESP0/RESP1 + HMP + HMOVE)  |
| `$F25B`  | `PositionBall` (RESBL + HMBL)                  |
| `$F26D`  | `PositionMissiles` (RESM0/RESM1 + HMM)         |
| `$F298`  | `BuildEvents` (rebuild the event table)        |
| `$F313`  | `AddEvent` (append a record)                   |
| `$F332`  | `SortEvents` (insertion sort of the order)     |
| `$F372`  | `EmitEvents` (write the table)                 |
| `$F421`  | `BubbleOrder` (collision resolution)           |
| `$F454`  | `PosObject` (generic RESPx/HMPx)               |
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
 └─ OVERSCAN 10 scanlines (TIM64T = 11; loop back to StartOfFrame)
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

`UpdatePlayers` samples `SWCHA` once per frame into the `joystate` RAM
variable, then applies at most one up/down step per player, guarding the
arena boundaries so the position never wraps.

## Missiles

Each player can fire one missile with the fire button. Fire buttons are read
through the TIA INPT latches: bit 7 of `INPT4` (P0) and `INPT5` (P1) is 0
while pressed. `UpdateMissiles` samples both buttons each frame and spawns a
missile on the rising edge (button released, then pressed); holding the
button does not produce a stream of missiles (`fire_prev` remembers the
previous frame's state).

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

`BuildEvents` has three phases:

1. **Generate** - `AddEvent` appends one 3-byte record `(row, reg, val)` per
   object boundary and records its byte offset in the `evOrder` array.
2. **Sort** - `SortEvents` insertion-sorts the `evOrder` array by row. Sorting
   single-byte offsets (rather than the 3-byte records) keeps this cheap
   enough for the VBLANK budget.
3. **Emit** - `EmitEvents` walks the sorted order and writes the table,
   merging at most two same-row records into a single two-write entry. If a
   pathological third record shares a row, its row is bumped to row+1 and
   `BubbleOrder` restores the sorted order. This guarantees no scanline ever
   needs more than two writes.

The table ends with a terminator entry whose delta (`$FF`) can never fire
inside the 192-line kernel.

## Variable allocation

121 of 128 bytes of RIOT RAM are used:

| Address | Name      | Purpose                              |
| ------- | --------- | ------------------------------------ |
| `$80`   | `P0Y`     | player 0 vertical position           |
| `$81`   | `P1Y`     | player 1 vertical position           |
| `$82`   | `joystate`| sampled SWCHA value                  |
| `$83`   | `ball_x`  | ball leftmost visible pixel          |
| `$84`   | `ball_y`  | ball first display row               |
| `$85`   | `ball_dx` | horizontal direction step            |
| `$86`   | `ball_dy` | vertical direction step              |
| `$87-$8C` | `m0_x/m0_y/m0_active`, `m1_x/m1_y/m1_active` | missiles |
| `$8D`   | `fire_prev` | packed fire-button edge state      |
| `$8E-$90` | `evCnt/evIdx/scanCnt` | kernel state              |
| `$91-$C7` | `evTbl`  | event table (11 entries x 5 bytes)   |
| `$C8-$E5` | `events` | event records (up to 10 x 3 bytes) |
| `$E6`   | `evCount` | number of records this frame        |
| `$E7-$F0` | `evOrder` | sorted record offsets             |
| `$F1-$F8` | builder/kernel temps            |

## Why VBLANK for gameplay

The visible kernel has a 76-cycle budget per scanline. Running the joystick
decoding, movement, bounce checks and the event-table build there would add
branch-heavy, data-dependent timing to a rendering path that must stay
deterministic. Moving them to VBLANK (see [timing.md](timing.md)) keeps the
kernel stable at exactly one scanline per iteration regardless of input or
game state.
