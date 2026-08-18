# Wizard Duel - Memory map

The Atari 2600 (6507) exposes 4 KiB of ROM (`$F000-$FFFF`), 128 bytes of
RIOT RAM (`$80-$FF`), the TIA registers (`$00-$3F`) and the RIOT I/O/timer
registers (`$0280-$02FF`).

## ROM layout (`$F000-$FFFF`)

| Address  | Content                                   |
| -------- | ----------------------------------------- |
| `$F000`  | Reset/init (main.asm)                     |
| `$F04F`  | `StartOfFrame` (one-frame loop)           |
| `$F079`  | `WaitVBlank` (TIM64T + game logic)        |
| `$F100`  | `KernelLoop` (event-driven 192-line kernel) |
| `$F142`  | `OverscanWait`                            |
| `$F14A`  | `UpdatePlayers` (vertical joystick input) |
| `$F184`  | `UpdateBall` (move + bounce)              |
| `$F1BB`  | `UpdateMissiles` (fire, move, despawn)    |
| `$F238`  | `PositionPlayers` (RESP0/1 + HMP0/1)      |
| `$F25B`  | `PositionBall` (RESBL + HMBL)             |
| `$F26D`  | `PositionMissiles` (RESM0/1 + HMM0/1)     |
| `$F298`  | `BuildEvents` (rebuild the event table)   |
| `$F313`  | `AddEvent` (append a record)              |
| `$F332`  | `SortEvents` (insertion sort)             |
| `$F372`  | `EmitEvents` (write the table)            |
| `$F421`  | `BubbleOrder` (collision resolution)      |
| `$F454`  | `PosObject` (generic RESPx + HMPx)        |
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
padding counts as available space. The build reports both numbers. Round 3
uses 1296 of the 4096 bytes.

## RAM layout (RIOT RAM `$80-$FF`, 128 bytes)

| Address   | Name       | Size | Purpose                              |
| --------- | ---------- | ---- | ------------------------------------ |
| `$80`     | `P0Y`      | 1    | player 0 vertical position (0..179)  |
| `$81`     | `P1Y`      | 1    | player 1 vertical position (0..179)  |
| `$82`     | `joystate` | 1    | sampled `SWCHA` value                |
| `$83`     | `ball_x`   | 1    | ball leftmost visible pixel (0..156) |
| `$84`     | `ball_y`   | 1    | ball first display row (0..188)      |
| `$85`     | `ball_dx`  | 1    | horizontal step (+1 / $FF)           |
| `$86`     | `ball_dy`  | 1    | vertical step (+1 / $FF)             |
| `$87`     | `m0_x`     | 1    | missile 0 horizontal position        |
| `$88`     | `m0_y`     | 1    | missile 0 row (fixed while flying)   |
| `$89`     | `m0_active`| 1    | missile 0 active flag                |
| `$8A`     | `m1_x`     | 1    | missile 1 horizontal position        |
| `$8B`     | `m1_y`     | 1    | missile 1 row (fixed while flying)   |
| `$8C`     | `m1_active`| 1    | missile 1 active flag                |
| `$8D`     | `fire_prev`| 1    | packed fire-button edge state        |
| `$8E`     | `evCnt`    | 1    | kernel: scanlines to next event      |
| `$8F`     | `evIdx`    | 1    | kernel: current event-table offset   |
| `$90`     | `scanCnt`  | 1    | kernel: 192-line countdown           |
| `$91-$C7` | `evTbl`    | 55   | event table (11 entries x 5 bytes)   |
| `$C8-$E5` | `events`   | 30   | event records (up to 10 x 3 bytes)   |
| `$E6`     | `evCount`  | 1    | number of event records this frame   |
| `$E7-$F0` | `evOrder`  | 10   | record byte offsets, sorted by row   |
| `$F1-$F8` | temps      | 8    | builder/kernel working storage       |
| `$F9`     | `fire_sync`| 1    | fire-input boot synchronisation      |
| `$FA-$FF` | -          | 6    | unallocated                          |

121 of the 128 bytes are used in Round 3. Variables live in zero page so all
accesses use the short, fast zero-page addressing modes. The event table (55
bytes) and the records/order buffers (40 bytes) are the dominant consumers;
the game state itself is compact.

## Hardware register usage

* TIA: `VSYNC`, `VBLANK`, `WSYNC`, `NUSIZ0/1`, `COLUP0/1`, `COLUPF`,
  `COLUBK`, `CTRLPF`, `RESP0/1`, `RESM0/1`, `RESBL`, `GRP0/1`, `ENAM0/1`,
  `ENABL`, `HMOVE`, `HMP0/1`, `HMM0/1`, `HMBL`, `VDELP0/1`, `REFP0/1`
  (cleared).
* TIA reads: `INPT4`/`INPT5` (fire buttons).
* RIOT: `SWCHA` (read joysticks), `SWACNT` (set all inputs),
  `INTIM` (read timer), `TIM64T` (write timer, 64-cycle clock).

No other RIOT or TIA resources are used this round.
