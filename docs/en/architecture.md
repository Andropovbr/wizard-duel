# Wizard Duel - Architecture

Round 2 establishes the minimum technical base for an Atari 2600 game:

* a stable NTSC frame of exactly 262 scanlines
* two TIA players visible simultaneously (P0 on the left, P1 on the right),
  rendered as simple vertical paddles
* vertical-only movement driven by joystick 1 (P0) and joystick 2 (P1)
* a TIA Ball object that moves continuously and bounces off the four arena
  edges

There is intentionally no magic system, projectiles, HP, AI, collisions,
scoring or HUD yet; the gameplay rules are expected to evolve in later
rounds without requiring architectural changes. The ball does not interact
with the players in this round.

## Code layout

`src/main.asm` contains the complete program in a single `$F000-$FFFF` ROM
bank (4 KiB, no bankswitching). `src/constants.inc` holds all hardware
register addresses and build-time constants.

| Address  | Content                                        |
| -------- | ---------------------------------------------- |
| `$F000`  | `Reset` (initialization)                       |
| `$F049`  | `StartOfFrame` (VSYNC + VBLANK + kernel + OS)  |
| `$F0C1`  | `UpdatePlayers` (joystick input + movement)    |
| `$F0FB`  | `UpdateBall` (ball movement + bounce)          |
| `$F132`  | `PositionPlayers` (RESP0/RESP1 + HMP + HMOVE)  |
| `$F155`  | `PositionBall` (RESBL + HMBL)                  |
| `$F167`  | `PosObject` (generic RESPx/HMPx)               |
| `$F200`  | `fineAdjustBegin` (page-aligned HMP table)     |
| `$FFFA`  | NMI / RESET / IRQ vectors                      |

There are no sprite graphics tables: both players are solid `PADDLE_BITS`
rectangles rendered branchlessly inside the kernel (see [timing.md](timing.md)).

The exact addresses may change between builds; the automated tests resolve
them from the symbol/listing files rather than hard-coding them.

## Execution flow per frame

```
StartOfFrame
 ├─ VSYNC   3 scanlines  (three explicit WSYNC writes)
 ├─ VBLANK 37 scanlines  (TIM64T = 43; gameplay runs here)
 │   ├─ UpdatePlayers    read SWCHA, move P0/P1, clamp to the arena
 │   ├─ UpdateBall       move the ball, bounce off the arena edges
 │   ├─ PositionPlayers  RESP0/RESP1 + HMP0/HMP1 coarse/fine placement
 │   └─ PositionBall     RESBL + HMBL placement
 ├─ KERNEL 192 scanlines (explicit WSYNC loop; render only)
 └─ OVERSCAN 30 scanlines (TIM64T = 37; loop back to StartOfFrame)
```

Gameplay input and state updates happen during VBLANK; the visible kernel
only renders the two sprites and the ball. This follows the project rule
that display code must remain timing-predictable and gameplay must stay out
of it.

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

## Rendering

Both players are drawn as single-copy TIA sprites (`NUSIZ0/1 = 0`) with
different colors: P0 is red (`COLUP0 = $46`) and P1 is blue
(`COLUP1 = $84`). Each sprite is a solid rectangle of `%00111100` (a
4-pixel-wide paddle). The kernel renders each player with a branchless
"draw or blank" test: per scanline it computes whether `X` is inside the
player's 12-row band and writes either the constant `PADDLE_BITS` row byte
or 0 to `GRP0`/`GRP1` (the `LDA #0 / SBC #0` trick, 18 cycles per player).

The ball is drawn with the TIA Ball object (4 pixels wide via `CTRLPF`
D5:D4 = `%10` = 4 color clocks, `BALL_HEIGHT = 4` scanlines tall, colored by
`COLUPF`). A single-scanline-tall ball renders as a thin dash and, having no
vertical overlap between consecutive frames, looks stroboscopic when it
moves 1 px/frame; the 4x4 ball is close to square. The kernel enables it on
`BALL_HEIGHT` consecutive scanlines by testing `line - ball_y < BALL_HEIGHT`
in its tail and carrying the result in `A` across the loop. The enable bit
is sampled by the TIA at the ball's horizontal position, so `STA ENABL` is
written during the horizontal blanking of every scanline (immediately after
`STA WSYNC`), precomputed for the current line in the previous scanline's
tail. This keeps the ball exactly `BALL_HEIGHT` lines tall at every `ball_x`
(see [timing.md](timing.md)); earlier, writing `ENABL` late in the scanline
made the ball jump one scanline in some horizontal regions.

Horizontal placement is fixed every frame with the classic
RESP0/RESP1/HMBL + HMP0/HMP1/HMBL + HMOVE technique: a coarse `RESPx`/`RESBL`
positions the object to within 15 pixels and a fine `HMPx`/`HMBL` offset
from the page-aligned `fineAdjustTable` finishes the job. The `HMOVE` that
applies the offsets is written immediately after a `STA WSYNC` on the last
VBLANK line, as the Stella Programmer's Guide requires; before this fix the
`HMOVE` followed a timer poll instead of a `WSYNC`, so the fine offsets were
never applied and objects snapped to the 15-pixel coarse grid.

Measured on the target (TIA/Stella), the routine renders a player at
`15*q + (s - 7)` for `q >= 1` and at `3 + (s - 7)` for `q = 0` (the shortest
divide path strokes `RESP` before TIA cycle 23), where `q = input / 15` and
`s = input mod 15`. `PositionBall` therefore passes `ball_x + 8` (or
`ball_x + 5` when that is below 15, cancelling the q = 0 coarse base of 3)
and the ball's 1-color-clock-left shift vs a player, so it renders at
exactly `ball_x`; `PositionPlayers` passes `X + 7` (or `X + 4`).

## Ball movement and bounce

`UpdateBall` moves the ball one pixel per frame on both axes at constant
speed. `ball_dx`/`ball_dy` store the direction step (+1 or $FF). Bouncing is
implemented by reversing a direction when the ball reaches an exact arena
edge (`BALL_X_MIN/MAX`, `BALL_Y_MIN/MAX`) *before* moving, so the position
is always clamped to the valid range and can never wrap through an unsigned
underflow. The ball does not collide with the players or the playfield; it
bounces only off the four edges of the play area.

## Variable allocation

Seven zero-page variables are used (7 of 128 bytes of RIOT RAM):

| Address | Name      | Purpose                      |
| ------- | --------- | ---------------------------- |
| `$80`   | `P0Y`     | player 0 vertical position   |
| `$81`   | `P1Y`     | player 1 vertical position   |
| `$82`   | `joystate`| sampled SWCHA value          |
| `$83`   | `ball_x`  | ball leftmost visible pixel  |
| `$84`   | `ball_y`  | first ball ENABL scanline      |
| `$85`   | `ball_dx` | horizontal direction step    |
| `$86`   | `ball_dy` | vertical direction step      |

## Why VBLANK for gameplay

The visible kernel has a 76-cycle budget per scanline. Running the joystick
decoding, movement and bounce checks there would add branch-heavy,
data-dependent timing to a rendering path that must stay deterministic.
Moving it to VBLANK (see [timing.md](timing.md)) keeps the kernel stable at
exactly one scanline per iteration regardless of input or ball position.