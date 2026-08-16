# Wizard Duel - Architecture

Round 1 establishes the minimum technical base for an Atari 2600 game:

* a stable NTSC frame of exactly 262 scanlines
* two TIA players visible simultaneously (P0 on the left, P1 on the right)
* vertical-only movement driven by joystick 1 (P0) and joystick 2 (P1)

There is intentionally no magic system, projectiles, HP, AI, collisions or
HUD yet; the gameplay rules are expected to evolve in later rounds without
requiring architectural changes.

## Code layout

`src/main.asm` contains the complete program in a single `$F000-$FFFF` ROM
bank (4 KiB, no bankswitching). `src/constants.inc` holds all hardware
register addresses and build-time constants.

| Address  | Content                                        |
| -------- | ---------------------------------------------- |
| `$F000`  | `Reset` (initialization)                       |
| `$F016`  | `StartOfFrame` (VSYNC + VBLANK + kernel + OS)  |
| `$F09B`  | `UpdatePlayers` (joystick input + movement)    |
| `$F0D5`  | `PositionPlayers` (RESP0/RESP1 + HMP + HMOVE)  |
| `$F0F4`  | `P0Sprite` / `P1Sprite` (12 bytes each)        |
| `$F200`  | `fineAdjustBegin` (page-aligned HMP table)     |
| `$FFFA`  | NMI / RESET / IRQ vectors                      |

The exact addresses may change between builds; the automated tests resolve
them from the symbol/listing files rather than hard-coding them.

## Execution flow per frame

```
StartOfFrame
 ├─ VSYNC   3 scanlines  (three explicit WSYNC writes)
 ├─ VBLANK 37 scanlines  (TIM64T = 44; gameplay runs here)
 │   ├─ UpdatePlayers    read SWCHA, move P0/P1, clamp to the arena
 │   └─ PositionPlayers  RESP0/RESP1 + HMP0/HMP1 coarse/fine placement
 ├─ KERNEL 192 scanlines (explicit WSYNC loop; render only)
 └─ OVERSCAN 30 scanlines (TIM64T = 37; loop back to StartOfFrame)
```

Gameplay input and state updates happen during VBLANK; the visible kernel
only renders the two sprites. This follows the project rule that display
code must remain timing-predictable and gameplay must stay out of it.

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
(`COLUP1 = $84`). The kernel computes, per scanline, whether the current
line index belongs to a player's 12-row sprite and writes the matching row
byte to `GRP0`/`GRP1`.

Horizontal placement is fixed every frame with the classic
RESP0/RESP1 + HMP0/HMP1 + HMOVE technique: a coarse `RESPx` positions the
sprite to within 15 pixels and a fine `HMPx` offset from the page-aligned
`fineAdjustTable` finishes the job. The `HMOVE` that applies the offsets is
written on the last VBLANK line.

## Variable allocation

Only three zero-page variables are used (3 of 128 bytes of RIOT RAM):

| Address | Name      | Purpose                      |
| ------- | --------- | ---------------------------- |
| `$80`   | `P0Y`     | player 0 vertical position   |
| `$81`   | `P1Y`     | player 1 vertical position   |
| `$82`   | `joystate`| sampled SWCHA value          |

## Why VBLANK for gameplay

The visible kernel has a 76-cycle budget per scanline. Running the joystick
decoding and movement there would add branch-heavy, data-dependent timing
to a rendering path that must stay deterministic. Moving it to VBLANK (see
[timing.md](timing.md)) keeps the kernel stable at exactly one scanline per
iteration regardless of input.