# Wizard Duel - Architecture

Round 3 adds basic projectiles and replaces the Round 2 branchless display
kernel with an event-driven one. Round 3.1 shrinks the RAM footprint from 122
to 48 bytes by switching the event table to variable-size entries and
removing the separate record/order scratch buffers. Round 11 fixes a
delta=1 kernel bug by making the kernel apply the event table directly on
every scanline (uniform 5-byte entries, table-direct apply) - see
[event-kernel-timing-analysis.md](event-kernel-timing-analysis.md) for the
full bug analysis.

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
changes. The ball does not interact with the missiles. Ball x player contact is
detected via the TIA latches (Round 6) and the ball is steered horizontally on
contact (Round 7): P0 sends it right, P1 sends it left, vertical motion
unchanged; the rebound is a fixed-cost, branchless pass in overscan. A dead
player keeps occupying the arena but is not rendered and cannot fire; there is
no victory/game-over transition yet.

## Event-driven kernel

With a second pair of objects (the missiles) the Round 2 branchless kernel no
longer fits in the 76-cycle scanline budget (it needed ~98 cycles for two
players, the ball and two missiles). Instead of computing every object's
enable on every scanline, `BuildEvents` runs during VBLANK and writes a table
(`evTbl`) describing the register writes each scanline must perform. The
kernel then counts down to the next entry and applies its writes, keeping
every scanline well under 76 cycles (54 worst case, see
[timing.md](timing.md)).

Each table entry is a fixed 5 bytes (Round 11):

| byte | meaning                                    |
| ---- | ------------------------------------------ |
| 0    | delta: scanlines until this entry fires    |
| 1    | register index of the first write          |
| 2    | value of the first write                   |
| 3    | register index of the second write (0 = none) |
| 4    | value of the second write                  |

The entry is a **single write** when byte 3 is 0 (that second write is a
harmless AUDV0 dummy) and a **double write** otherwise. There is no
variable-size entry and no bit-7 dispatch: the kernel treats every entry
identically, so timing is constant regardless of how many writes an entry
holds.

The kernel applies the table **directly on every scanline** (this is the
delta=1 fix that replaces the Round 10 two-phase pending pipeline). `Y`
always points one entry past the last-decoded one, so each line reads its two
writes from `evTbl-4,Y` / `evTbl-3,Y` (write 1) and `evTbl-2,Y` /
`evTbl-1,Y` (write 2), then counts `evCnt` down:

* if `evCnt > 0` the line is a plain non-event line: 38 cycles total;
* if `evCnt == 0` an event fires: the kernel loads the next entry's delta
  into `evCnt`, advances `Y` by 5, and loops - 54 cycles;
* if that delta is `$FF` (`EV_MARKER_VAL`) the kernel ends on this line - 46
  cycles.

Because the apply block runs unconditionally at the top of every line -
before any countdown - an event on the very next row (delta 1) cannot collide
with the previous event the way the old deferred pipeline did: each entry
applies its writes on the first line of its own display row. Re-applying the
same entry on the lines between events is idempotent and harmless.

The first five bytes of the table are a **dummy entry** (both registers 0,
both writes to AUDV0) so the apply on lines before the first event fires
touches only the harmless dummy register. Real entries start at offset 5.

Deltas: the first entry fires on line `delta - 1`, every following entry
fires `delta` lines after the previous one, so `BuildEvents` computes
`delta(first) = row + 1` and `delta(next) = row - prevRow`. The `evCnt`
countdown handles the first entry (primed with `nullDelta`) and the marker's
delta ends the kernel on line 185. The kernel does not need a line counter in
a register: the countdown + marker structure fixes the visible region at
exactly 185 lines.

### Same-row collisions and write-slot ordering (Rounds 7/8/11)

Up to ten events can land on the same scanline row (two players + ball +
two missiles, ON and OFF each). `InsertEvent` keeps the table sorted by row
and allows at most two writes per entry:

* two events on the same row merge into a double entry - because entries are
  uniform 5-byte records, the merge only fills `reg2/val2` at `+3/+4`; there
  is no shifting of the tail (the old `ShiftBy2` extension of a 3-byte single
  into a 5-byte double is gone);
* a third event on a row that already holds a double is **bumped to row+1**
  and the scan continues - so no scanline ever needs more than two writes,
  which protects the kernel budget.

Round 7 fixed a bug in the bump path: `.insertSingle` stored the event's
original stacked row even after the row was bumped. A third event colliding
with a double then produced two table entries at the same absolute row,
`ConvertDeltas` emitted **delta 0**, and the kernel's `DEC evCnt` wrapped
`0 -> $FF`, so that OFF event never fired and the object stayed enabled to
the bottom edge of the screen (a vertical stretch). The realistic trigger
was both players alive at the same row, both missiles flying and the ball
crossing the missile rows. `AppendEvent` now discards the original stacked
row and writes the effective (possibly bumped) `evRow` instead, keeping the
table strictly sorted with no delta-0 entries in any valid state.

The write *timing* of a double entry also matters (Round 8): the kernel
writes the first register at CPU cycle 15 and the second at cycle 27
(measured on the deterministic emulator). A TIA write only applies to the
current scanline if it completes before the beam passes the object's
horizontal position. The second write therefore requires `x >= 13` on the
conservative beam model. The ball's X spans the whole arena (0..156) and M1
can reach x = 2, so they must never occupy the second slot. `InsertEvent`
enforces the slot rule:

* the ball and M1 events are inserted **before** the players and M0, so on a
  same-row merge they naturally take the first write;
* the ball is never merged with M1 (both can fall below the second-write
  gate) - the later event is bumped to row+1, reusing the three-on-a-row
  mechanism.

With these rules every second write targets GRP0 (x=16), GRP1 (x=136) or
ENAM0 (x >= 18), so the horizontal guarantee holds for all objects at all
positions.

## Code layout

`src/main.asm` contains the complete program in a single `$F000-$FFFF` ROM
bank (4 KiB, no bankswitching). `src/constants.inc` holds all hardware
register addresses and build-time constants.

| Address  | Content                                        |
| -------- | ---------------------------------------------- |
| `$F000`  | `Reset` (initialization)                       |
| `$F055`  | `StartOfFrame` (VSYNC + VBLANK + kernel + OS)  |
| `$F100`  | `KernelLoop` (event-driven display kernel)     |
| `$F134`  | `OverscanWait` (collision + hit effects + WSYNC loop) |
| `$F148`  | `UpdatePlayers` (joystick input + movement)    |
| `$F181`  | `UpdateBall` (ball movement + bounce)          |
| `$F1B8`  | `UpdateMissiles` (fire buttons, movement)      |
| `$F24D`  | `ProcessCollisions` (fixed-cost, branchless)   |
| `$F290`  | `newActiveTbl` (m_active update table)         |
| `$F300`  | `ProcessHitEffects` (HP damage + fire lock)    |
| `$F338`  | `PositionPlayers` (RESP0/RESP1 + HMP + HMOVE)  |
| `$F35B`  | `PositionBall` (RESBL + HMBL)                  |
| `$F36D`  | `PositionMissiles` (RESM0/RESM1 + HMM)         |
| `$F39C`  | `BuildEvents` (insert events in row order)     |
| `$F58A`  | `AppendEvent` (insert/merge/bump a table entry)|
| `$F60F`  | `fineAdjustTable` (page-aligned HMP table)     |
| `$F648`  | `ShiftBy5` (shift the table tail by 5)         |
| `$F65F`  | `ConvertDeltas` (rows -> kernel deltas)        |
| `$F68C`  | `PosObject` (generic RESPx/HMPx)               |
| `$F700`  | `fineAdjustBegin` (page-aligned HMP table)     |
| `$FFFA`  | NMI / RESET / IRQ vectors                      |

There are no sprite graphics tables: both players are solid `PADDLE_BITS`
rectangles drawn through the event table. The exact addresses may change
between builds; the automated tests resolve them from the symbol/listing
files rather than hard-coding them.

## Execution flow per frame

```
StartOfFrame
 ├─ VSYNC   3 scanlines  (three explicit WSYNC writes)
 ├─ VBLANK 64 scanlines  (TIM64T = 77; gameplay + event build run here)
 │   ├─ UpdatePlayers    read SWCHA, move P0/P1, clamp to the arena
 │   ├─ UpdateBall       move the ball, bounce off the arena edges
 │   ├─ UpdateMissiles   read INPT4/INPT5, fire/move/despawn missiles
 │   ├─ PositionPlayers  RESP0/RESP1 + HMP0/HMP1 coarse/fine placement
 │   ├─ PositionBall     RESBL + HMBL placement
 │   ├─ PositionMissiles RESM0/RESM1 + HMM0/HMM1 placement
 │   └─ BuildEvents      rebuild the event table for the visible kernel
├─ KERNEL 185 scanlines (explicit WSYNC loop; render events only)
  └─ OVERSCAN 10 scanlines (ProcessCollisions + ProcessHitEffects + fixed WSYNC loop; back to StartOfFrame)
```

Gameplay input, movement and event building happen during VBLANK; the visible
kernel only applies the precomputed register writes. VBLANK is larger than in
Round 2 (64 vs 37 lines) to give `BuildEvents` room; OVERSCAN shrinks to 10
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
  ignored. The pass is branchless and fixed-cost (117 cycles: 84 for the
  missile hit path, +33 for the ball contact path) so the fixed WSYNC-counted
  overscan stays exact.
* **Ball contact** (same `ProcessCollisions` pass, before `CXCLR`): reads
  `CXP0FB`/`CXP1FB` and records Ball x P0 / Ball x P1 (D6 of each latch,
  `BALL_HIT_P0`/`BALL_HIT_P1`) in the separate byte `ball_contact_flags`
  (CONTACT_P0 bit 0, CONTACT_P1 bit 1; simultaneous contacts both count).
  The D7 player x playfield bits are ignored (the playfield is never
  displayed). Contact is information only: no damage, no missile change, no
  ball rebound, no `hit_flags`/`m_active` change. It is deliberately a
  separate byte because a ball contact is not a missile hit and the spare
  bits of `m_active`/`fire_prev` are rewritten every frame. The record is
  overwritten every overscan, so a contact rendered in frame N is visible
  for frame N+1 and never repeats. A dead player is not rendered
  (`BuildEvents` skips its events), so the TIA never latches a
  ball x dead-player overlap and no HP check is needed.
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

Round 11 uses a direct insertion builder: `BuildEvents` writes a dummy entry
at offset 0 of `evTbl` and then inserts each object's ON/OFF events straight
into the table in row order, so no separate record or order buffers exist.
Because the entries are uniform 5-byte records, insertion is a simple
sorted-insert with a fixed 5-byte shift:

1. `AppendEvent` scans the table comparing entry rows. On a matching row it
   merges: fills `reg2/val2` at `+3/+4` (no shift - the entry is already
   5 bytes wide). On an already-double row it bumps the event to row+1 and
   continues the scan (this can only happen transiently during a single
   build, so the table never exceeds its bound). Otherwise it shifts the tail
   by 5 (`ShiftBy5`) and writes a new 5-byte entry. Insertion order encodes
   the slot rule: the ball and M1 are inserted first, so on a merge they take
   the first write slot; the ball is never merged with M1 (bumped instead).
2. After all events are inserted, `ConvertDeltas` rewrites the rows in place
   as kernel deltas (first delta = row+1, next deltas = row - prevRow,
   advancing by 5 unconditionally) and appends the marker entry whose delta
   is `$FF` (`EV_MARKER_VAL`).

Every event (single or merged double) is a 5-byte entry, so the worst-case
table size is `dummy(5) + 10 * 5 + marker(5) = 60` bytes. `EV_TBL_SIZE = 60`
is a hard bound; `tblLen` tracks the current length and a test asserts it
never exceeds the bound under aggressive fire input.

The marker entry's delta (`$FF`) can never fire inside the 185-line kernel:
it is the countdown value read on the line that ends the kernel.

## Variable allocation

81 of 128 bytes of RIOT RAM are used (the delta=1 kernel and the uniform
60-byte table cost 29 bytes over the Round 10 layout; documented in the
change log). The +1 byte over Round 11 is `ball_contact_flags`, the Round 6
ball x player contact record, deliberately separate from `hit_flags`:

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
| `$8D`      | `hit_flags` | missile hit results (P0/P1 hit bits) |
| `$8E`      | `ball_contact_flags` | ball contact record (P0/P1 bits) |
| `$8F`      | `fire_prev` | packed fire edge + boot-sync state   |
| `$90`      | `evCnt`     | kernel event countdown               |
| `$91-$CC`  | `evTbl`     | event table (dummy + 10 entries + marker, 60B) |
| `$CD`      | `evRow`     | builder working storage              |
| `$CE`      | `tempCount` | builder working storage              |
| `$CF`      | `tblLen`    | builder working storage              |
| `$D0`      | `nullDelta` | first-delta prime value for `evCnt`  |

The savings come from: packed missile flags (one byte for two), no separate
`fire_sync` (bit 7 of `fire_prev`), and no `evIdx` (the kernel reads the
table through `Y`, which always points one entry past the last-decoded one).
The pending-register bytes of the Round 10 kernel are gone because the apply
reads straight from the table.

## Why VBLANK for gameplay

The visible kernel has a 76-cycle budget per scanline. Running the joystick
decoding, movement, bounce checks and the event-table build there would add
branch-heavy, data-dependent timing to a rendering path that must stay
deterministic. Moving them to VBLANK (see [timing.md](timing.md)) keeps the
kernel stable at exactly one scanline per iteration regardless of input or
game state.
