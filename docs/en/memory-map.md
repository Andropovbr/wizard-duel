# Wizard Duel - Memory map

The Atari 2600 (6507) exposes 4 KiB of ROM (`$F000-$FFFF`), 128 bytes of
RIOT RAM (`$80-$FF`, mirrored every 256 bytes from `$0280`), the TIA
registers (`$00-$3F`) and the RIOT I/O/timer registers (`$0280-$02FF`).

## ROM layout (`$F000-$FFFF`)

| Address  | Content                                   |
| -------- | ----------------------------------------- |
| `$F000`  | Reset/init (main.asm)                     |
| `$F049`  | `StartOfFrame` (one-frame loop)           |
| `$F06A`  | `WaitVBlank` (TIM64T + game logic)        |
| `$F07B`  | `KernelLoop` (192-scanline kernel)        |
| `$F0C1`  | `OverscanWait`                            |
| `$F0C9`  | `UpdatePlayers` (vertical joystick input) |
| `$F103`  | `UpdateBall` (move + bounce)              |
| `$F13A`  | `PositionPlayers` (RESP0/1 + HMP0/1)      |
| `$F149`  | `PositionBall` (RESBL + HMBL)             |
| `$F154`  | `PosObject` (generic RESPx + HMPx)        |
| `$F164`  | `P0Sprite`  (12 row bytes, paddle)        |
| `$F170`  | `P1Sprite`  (12 row bytes, paddle)        |
| `$F200`  | `fineAdjustBegin` (HMP table, page-aligned) |
| `$FFFA`  | NMI vector (`Reset`)                      |
| `$FFFC`  | RESET vector (`Reset`)                    |
| `$FFFE`  | IRQ vector (`Reset`)                      |

`fineAdjustBegin` is page-aligned on purpose: `PosObject` indexes the table
with a two's-complement remainder, and the guaranteed page crossing of the
indexed `LDA` keeps the `RESPx` write on the exact cycle required by the
timing contract of the positioning routine.

ROM usage is measured by the high-water mark of emitted code below the
vector block; the `$FF`-filled padding counts as available space. The build
reports both numbers. In Round 2 the added ball code still fits inside the
page padding reserved for the aligned `fineAdjustBegin`, so ROM usage is
unchanged at 528 bytes.

## RAM layout (RIOT RAM `$80-$FF`, 128 bytes)

| Address | Name       | Size | Purpose                              |
| ------- | ---------- | ---- | ------------------------------------ |
| `$80`   | `P0Y`      | 1    | player 0 vertical position (0..179)  |
| `$81`   | `P1Y`      | 1    | player 1 vertical position (0..179)  |
| `$82`   | `joystate` | 1    | sampled `SWCHA` value                |
| `$83`   | `ball_x`   | 1    | ball leftmost visible pixel (0..156) |
| `$84`   | `ball_y`   | 1    | ball ENABL write scanline (0..190)   |
| `$85`   | `ball_dx`  | 1    | horizontal step (+1 / $FF)           |
| `$86`   | `ball_dy`  | 1    | vertical step (+1 / $FF)             |
| `$87-$FF`| -          | 121  | unallocated                          |

7 of the 128 bytes are used in Round 2. Variables live in zero page so all
accesses use the short, fast zero-page addressing modes.

## Hardware register usage

* TIA: `VSYNC`, `VBLANK`, `WSYNC`, `NUSIZ0/1`, `COLUP0/1`, `COLUPF`,
  `COLUBK`, `CTRLPF`, `RESP0/1`, `RESBL`, `GRP0/1`, `ENABL`, `HMOVE`,
  `HMP0/1`, `HMBL`, `VDELP0/1`, `REFP0/1` (cleared).
* RIOT: `SWCHA` (read joysticks), `SWACNT` (set all inputs),
  `INTIM` (read timer), `TIM64T` (write timer, 64-cycle clock).

No other RIOT or TIA resources are used this round.