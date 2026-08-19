# Wizard Duel - Memory map

The Atari 2600 (6507) exposes 4 KiB of ROM (`$F000-$FFFF`), 128 bytes of
RIOT RAM (`$80-$FF`), the TIA registers (`$00-$3F`) and the RIOT I/O/timer
registers (`$0280-$02FF`).

## ROM layout (`$F000-$FFFF`)

| Address  | Content                                   |
| -------- | ----------------------------------------- |
| `$F000`  | Reset/init (main.asm)                     |
| `$F055`  | `StartOfFrame` (one-frame loop)           |
| `$F07F`  | `WaitVBlank` (TIM64T + game logic)        |
| `$F100`  | `KernelLoop` (event-driven 185-line kernel) |
| `$F150`  | `OverscanWait` (collision + hit effects + WSYNC loop) |
| `$F160`  | `UpdatePlayers` (vertical joystick input) |
| `$F199`  | `UpdateBall` (move + bounce)              |
| `$F1D0`  | `UpdateMissiles` (fire, move, despawn)    |
| `$F265`  | `ProcessCollisions` (fixed-cost, branchless) |
| `$F2A0`  | `newActiveTbl` (m_active update table)    |
| `$F300`  | `ProcessHitEffects` (HP damage + fire lock, page-aligned) |
| `$F338`  | `PositionPlayers` (RESP0/1 + HMP0/1)      |
| `$F35B`  | `PositionBall` (RESBL + HMBL)             |
| `$F36D`  | `PositionMissiles` (RESM0/1 + HMM0/1)     |
| `$F39C`  | `BuildEvents` (insert events in row order) |
| `$F424`  | `InsertEvent` (insert + merge table entry) |
| `$F49A`  | `ShiftBy2` (extend a single into a double) |
| `$F4A8`  | `ShiftBy3` (insert a new single entry)    |
| `$F4B6`  | `ConvertDeltas` (rows -> kernel deltas)   |
| `$F4E7`  | `PosObject` (generic RESPx + HMPx)        |
| `$F500`  | `fineAdjustBegin` (HMP table, page-aligned) |
| `$FFFA`  | NMI vector (`Reset`)                      |
| `$FFFC`  | RESET vector (`Reset`)                    |
| `$FFFE`  | IRQ vector (`Reset`)                      |

`fineAdjustBegin` is page-aligned on purpose: `PosObject` indexes the table
with a two's-complement remainder, and the guaranteed page crossing of the
indexed `LDA` keeps the `RESPx` write on the exact cycle required by the
timing contract of the positioning routine.

There are no sprite graphics tables: both players are solid rectangles drawn
through the event table (see [timing.md]). ROM usage is measured by the
high-water mark of emitted code below the vector block; the `$FF`-filled
padding counts as available space. The build reports both numbers. Round 3.1
uses 1296 of the 4096 bytes.

## RAM layout (RIOT RAM `$80-$FF`, 128 bytes)

Round 5 uses 51 bytes. The event table is variable-size (entries hold
one or two writes) and the builder inserts events directly into it, so the
fixed 55-byte table, the records/order scratch buffers, `evIdx`, `joystate`,
the two separate missile-active flags and `fire_sync` are all gone. Round 4
added `hit_flags` (1 byte); Round 5 adds `p0_hp`/`p1_hp` (2 bytes).

| Address   | Name        | Size | Purpose                              |
| --------- | ----------- | ---- | ------------------------------------ |
| `$80`     | `P0Y`       | 1    | player 0 vertical position (0..179)  |
| `$81`     | `P1Y`       | 1    | player 1 vertical position (0..179)  |
| `$82`     | `p0_hp`     | 1    | player 0 hit points (0..3)           |
| `$83`     | `p1_hp`     | 1    | player 1 hit points (0..3)           |
| `$84`     | `ball_x`    | 1    | ball leftmost visible pixel (0..156) |
| `$85`     | `ball_y`    | 1    | ball first display row (0..188)      |
| `$86`     | `ball_dx`   | 1    | horizontal step (+1 / $FF)           |
| `$87`     | `ball_dy`   | 1    | vertical step (+1 / $FF)             |
| `$88`     | `m0_x`      | 1    | missile 0 horizontal position        |
| `$89`     | `m0_y`      | 1    | missile 0 row (fixed while flying)   |
| `$8A`     | `m1_x`      | 1    | missile 1 horizontal position        |
| `$8B`     | `m1_y`      | 1    | missile 1 row (fixed while flying)   |
| `$8C`     | `m_active`  | 1    | packed active mask (bit0 M0, bit1 M1) |
| `$8D`     | `hit_flags` | 1    | collision results (bit0 P0, bit1 P1) |
| `$8E`     | `fire_prev` | 1    | packed fire edge state (bit7 = sync) |
| `$8F`     | `evCnt`     | 1    | kernel: scanlines to next event      |
| `$90`     | `scanCnt`   | 1    | kernel: 185-line countdown           |
| `$91-$AF` | `evTbl`     | 31   | event table (variable-size, max 31B) |
| `$B0`     | `evRow`     | 1    | builder: current event row           |
| `$B1`     | `tempCount` | 1    | builder: shift point / prevRow       |
| `$B2`     | `tblLen`    | 1    | builder: table length in bytes       |
| `$B3-$FF` | -           | 77   | unallocated                          |

Variables live in zero page so all accesses use the short, fast zero-page
addressing modes. The event table (at most 31 bytes) is the largest single
block; the game state itself is compact. The extra 77 free bytes are the
headroom this optimization buys for future rounds.

## Hardware register usage

* TIA: `VSYNC`, `VBLANK`, `WSYNC`, `NUSIZ0/1`, `COLUP0/1`, `COLUPF`,
  `COLUBK`, `CTRLPF`, `RESP0/1`, `RESM0/1`, `RESBL`, `GRP0/1`, `ENAM0/1`,
  `ENABL`, `HMOVE`, `HMP0/1`, `HMM0/1`, `HMBL`, `VDELP0/1`, `REFP0/1`
  (cleared).
* TIA reads: `INPT4`/`INPT5` (fire buttons).
* RIOT: `SWCHA` (read joysticks), `SWACNT` (set all inputs),
  `INTIM` (read timer), `TIM64T` (write timer, 64-cycle clock).

No other RIOT or TIA resources are used this round.
