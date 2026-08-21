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
| `$F134`  | `OverscanWait` (collision + hit effects + WSYNC loop) |
| `$F148`  | `UpdatePlayers` (vertical joystick input) |
| `$F181`  | `UpdateBall` (move + bounce)              |
| `$F1B8`  | `UpdateMissiles` (fire, move, despawn)    |
| `$F24D`  | `ProcessCollisions` (fixed-cost, branchless) |
| `$F2A0`  | `newActiveTbl` (m_active update table)    |
| `$F2B0`  | `ApplyBallRebound` (fixed-cost, branchless ball steer) |
| `$F2D0`  | `reboundTbl` (ball dx table, 16-byte aligned) |
| `$F300`  | `ProcessHitEffects` (HP damage + fire lock, page-aligned) |
| `$F338`  | `PositionPlayers` (RESP0/1 + HMP0/1)      |
| `$F35B`  | `PositionBall` (RESBL + HMBL)             |
| `$F36D`  | `PositionMissiles` (RESM0/1 + HMM0/1)     |
| `$F39C`  | `BuildEvents` (insert events in row order) |
| `$F58A`  | `AppendEvent` (insert + merge table entry) |
| `$F60F`  | `fineAdjustTable` (HMP table)             |
| `$F648`  | `ShiftBy5` (shift entries by one slot)    |
| `$F65F`  | `ConvertDeltas` (rows -> kernel deltas)   |
| `$F68C`  | `PosObject` (generic RESPx + HMPx)        |
| `$F700`  | `fineAdjustBegin` (HMP table, page-aligned) |
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
padding counts as available space. The build reports both numbers. Round 6
uses 1808 of the 4096 bytes; the round's added ball-contact code (24 bytes)
was absorbed by existing `ALIGN` slack, so the high-water mark did not move.

## RAM layout (RIOT RAM `$80-$FF`, 128 bytes)

Round 12 uses 86 bytes ($80-$D5). The event table is a fixed 60-byte block:
a 5-byte dummy at offset 0, up to 10 real 5-byte entries and the 5-byte
end-marker. The kernel reads the entries directly (table-direct apply), so
the Round 10 pending registers and the Round 5 scratch buffers/`scanCnt`/
`joystate`/separate missile flags are all gone. Round 12 adds 5 bytes for
game state, mode, and switch input (`game_state`, `game_mode`,
`select_prev`, `reset_prev`, `swchb_cur`).

| Address   | Name        | Size | Purpose                              |
| --------- | ----------- | ---- | ------------------------------------ |
| `$80`     | `P0Y`       | 1    | player 0 vertical position (0..166)  |
| `$81`     | `P1Y`       | 1    | player 1 vertical position (0..166)  |
| `$82`     | `p0_hp`     | 1    | player 0 hit points (0..3)           |
| `$83`     | `p1_hp`     | 1    | player 1 hit points (0..3)           |
| `$84`     | `ball_x`    | 1    | ball leftmost visible pixel (0..156) |
| `$85`     | `ball_y`    | 1    | ball first display row (0..181)      |
| `$86`     | `ball_dx`   | 1    | horizontal step (+1 / $FF)           |
| `$87`     | `ball_dy`   | 1    | vertical step (+1 / $FF)             |
| `$88`     | `m0_x`      | 1    | missile 0 horizontal position        |
| `$89`     | `m0_y`      | 1    | missile 0 row (fixed while flying)   |
| `$8A`     | `m1_x`      | 1    | missile 1 horizontal position        |
| `$8B`     | `m1_y`      | 1    | missile 1 row (fixed while flying)   |
| `$8C`     | `m_active`  | 1    | packed active mask (bit0 M0, bit1 M1) |
| `$8D`     | `hit_flags` | 1    | missile hit results (bit0 P0, bit1 P1) |
| `$8E`     | `ball_contact_flags` | 1 | ball contact record (bit0 P0, bit1 P1) |
| `$8F`     | `fire_prev` | 1    | packed fire edge state (bit7 = sync) |
| `$90`     | `evCnt`     | 1    | kernel: scanlines to next event      |
| `$91`     | `game_state`| 1    | STATE_MENU (0) or STATE_PLAYING (1)  |
| `$92`     | `game_mode` | 1    | MODE_DUEL (0) or MODE_SCORE (1)     |
| `$93`     | `select_prev`| 1   | previous frame SELECT bit (bit 1)    |
| `$94`     | `reset_prev`| 1    | previous frame RESET bit (bit 0)     |
| `$95`     | `swchb_cur` | 1    | current frame SWCHB snapshot         |
| `$96-$D1` | `evTbl`     | 60   | dummy (5B) + entries (max 10 x 5B) + marker (5B) |
| `$D2`     | `evRow`     | 1    | builder: current event row           |
| `$D3`     | `tempCount` | 1    | builder: shift point / prevRow       |
| `$D4`     | `tblLen`    | 1    | builder: number of real entries      |
| `$D5`     | `nullDelta` | 1    | first entry's delta (185 when empty) |
| `$D6-$FF` | -           | 42   | unallocated                          |

Variables live in zero page so all accesses use the short, fast zero-page
addressing modes. The event table (60 bytes) is the largest single block and
is deliberately page-0 resident: the kernel indexes `evTbl-4,Y` (a zero-page
base) with Y up to 55, so no indexed access can cross a page boundary and
every kernel write has deterministic timing. The extra 47 free bytes are the
headroom for future rounds.

## Hardware register usage

* TIA: `VSYNC`, `VBLANK`, `WSYNC`, `NUSIZ0/1`, `COLUP0/1`, `COLUPF`,
  `COLUBK`, `CTRLPF`, `RESP0/1`, `RESM0/1`, `RESBL`, `GRP0/1`, `ENAM0/1`,
  `ENABL`, `HMOVE`, `HMP0/1`, `HMM0/1`, `HMBL`, `VDELP0/1`, `REFP0/1`
  (cleared).
* TIA reads: `INPT4`/`INPT5` (fire buttons).
* RIOT: `SWCHA` (read joysticks), `SWACNT` (set all inputs),
  `INTIM` (read timer), `TIM64T` (write timer, 64-cycle clock).

No other RIOT or TIA resources are used this round.
