# Wizard Duel - Memory map

The Atari 2600 (6507) exposes 4 KiB of ROM (`$F000-$FFFF`), 128 bytes of
RIOT RAM (`$80-$FF`, mirrored every 256 bytes from `$0280`), the TIA
registers (`$00-$3F`) and the RIOT I/O/timer registers (`$0280-$02FF`).

## ROM layout (`$F000-$FFFF`)

| Address  | Content                                   |
| -------- | ----------------------------------------- |
| `$F000`  | Reset/init + one-frame loop (main.asm)    |
| `$F0F4`  | `P0Sprite`  (12 row bytes)                |
| `$F100`  | `P1Sprite`  (12 row bytes)                |
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
reports both numbers.

## RAM layout (RIOT RAM `$80-$FF`, 128 bytes)

| Address | Name       | Size | Purpose                              |
| ------- | ---------- | ---- | ------------------------------------ |
| `$80`   | `P0Y`      | 1    | player 0 vertical position (0..179)  |
| `$81`   | `P1Y`      | 1    | player 1 vertical position (0..179)  |
| `$82`   | `joystate` | 1    | sampled `SWCHA` value                |
| `$83-$FF`| -          | 125  | unallocated                          |

Only 3 of the 128 bytes are used in Round 1. Variables live in zero page so
all accesses use the short, fast zero-page addressing modes.

## Hardware register usage

* TIA: `VSYNC`, `VBLANK`, `WSYNC`, `NUSIZ0/1`, `COLUP0/1`, `COLUBK`,
  `REFP0/1` (cleared), `RESP0/1`, `GRP0/1`, `HMOVE`, `HMP0/1`, `CTRLPF`,
  `VDELP0/1`.
* RIOT: `SWCHA` (read joysticks), `SWACNT` (set all inputs),
  `INTIM` (read timer), `TIM64T` (write timer, 64-cycle clock).

No other RIOT or TIA resources are used this round.