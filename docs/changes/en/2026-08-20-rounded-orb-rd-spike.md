# Change: Rounded Orb R&D Spike

## Objective

Investigate ALL possible TIA techniques for producing a visually "rounded orb"
in the Wizard Duel game. Produce a comparison matrix with at least 3 concrete
alternatives and recommend a solution. This is an R&D spike -- no production
code is implemented or merged.

## Added

- `docs/changes/en/2026-08-20-rounded-orb-rd-spike.md` (this file)
- `docs/changes/pt-BR/2026-08-20-pesquisa-orb-arredondado.md` (Portuguese)

## Changed

None. No source code was modified.

## Removed

None.

## Technical Reasoning

### Current Ball Rendering

The current ball is a 4x4 rectangular block:

```
XXXX
XXXX
XXXX
XXXX
```

- Width: 4 color clocks (CTRLPF D5:D4 = `%10`)
- Height: 4 scanlines (ENABL = 1 for 4 rows)
- Color: $0E (white)
- Shape: fixed, per-frame CTRLPF setting

### Target: Visually Rounded Orb

A diamond shape (the closest approximation to "round" at this resolution):

```
.XX.     2 pixels  (CTRLPF narrow)
XXXX     4 pixels  (CTRLPF wide)
XXXX     4 pixels  (CTRLPF wide)
.XX.     2 pixels  (CTRLPF narrow)
```

Or a 6-line version for better vertical resolution:

```
..X..    1 pixel   (CTRLPF narrowest)
.XXX.    2 pixels  (CTRLPF narrow)
XXXXX    4 pixels  (CTRLPF wide)
XXXXX    4 pixels  (CTRLPF wide)
.XXX.    2 pixels  (CTRLPF narrow)
..X..    1 pixel   (CTRLPF narrowest)
```

### Hardware Capabilities Explored

| TIA Register | Address | Per-Scanline? | Effect |
|---|---|---|---|
| CTRLPF | $0A | Yes (D5:D4) | Ball width: 1/2/4/8 pixels |
| ENABL | $1F | Yes (bit 1) | Ball on/off per scanline |
| COLUPF | $08 | Yes | Ball/playfield color |
| RESBL | $14 | Yes (START signal) | Ball horizontal reposition |
| HMBL | $24 | Per-frame only | Ball fine horizontal movement |
| VDELBL | $27 | Per-CLK | Ball vertical delay |
| PF0/PF1/PF2 | $0D-$0F | Yes | Playfield shape (shared COLUPF) |
| NUSIZ0/1 | $04-$05 | Per-frame only | Player/missile sizing |

Key insight from subagent research: RESBL generates a START signal (unlike
RESPn/RESMn), enabling per-scanline ball repositioning. This is unusual among
TIA position registers and enables creative approaches.

---

## Family 1: CTRLPF Width Changes Within Event Kernel

**Approach**: Write CTRLPF in the event table for each ball row to change
width per scanline. Combine with ENABL on/off.

**Implementation sketch**: Each ball row event writes CTRLPF (new width) +
ENABL (on). A separate restore event writes CTRLPF (default) + ENABL (off).

**Cycle analysis**:

The current event kernel applies writes at cycles 15 (write 1) and 27 (write 2).
CTRLPF ($0A) at address offset 10 is below the x >= 15 gate for write 2.
Therefore CTRLPF **must be write 1** in any event entry.

| Row | Event writes | Cycle cost |
|---|---|---|
| Ball row N (width+on) | CTRLPF=new, ENABL=on | 54 (standard event) |
| Ball row N+1 (restore+off) | CTRLPF=default, ENABL=off | 54 (standard event) |

For a 4-row diamond (2-4-4-2): 4 width-change events + 2 restore events = 6
events for the ball alone. Plus existing 2 players (4 events) + 2 missiles
(4 events) = 14 total. Exceeds EV_MAX_EVENTS = 10.

**RAM**: 0 extra bytes (uses existing event table slots).
**ROM**: +20-40 bytes (event entries, CTRLPF values).
**Event table**: 6 ball events vs current 2. **Exceeds capacity** under collision stress.
**Collision**: Ball collision latches detect per-pixel overlap. Narrower rows
produce fewer collision pixels. Semantics change (narrower ball = harder to hit).
**Risk**: HIGH -- event table overflow under stress.

**Verdict**: REJECTED -- event table overflow. The 10-event cap cannot
accommodate 6 ball events + 8 player/missile events.

---

## Family 2: CTRLPF Width Changes in Dedicated Orb Mini-Loop

**Approach**: Insert a dedicated "orb mini-loop" that runs exactly
BALL_HEIGHT scanlines before the main event kernel. This mini-loop handles
ENABL + CTRLPF writes per row with its own cycle budget, completely separate
from the event table.

**Implementation sketch**:

```asm
; --- Orb mini-loop (BALL_HEIGHT iterations) ---
OrbLoop:
    STA WSYNC           ; 3   start of scanline
    ; ---- apply orb row ----
    LDX orb_row_idx     ; 3   0..BALL_HEIGHT-1
    LDA orb_width_tbl,X ; 4   CTRLPF value for this row
    STA CTRLPF          ; 3   set ball width (must be before RESBL)
    LDA orb_enabl_tbl,X ; 4   ENABL value (on/off)
    STA ENABL           ; 3   enable/disable ball
    ; ---- reposition ball (RESBL fires after beam reaches ball_x) ----
    ; RESBL must fire at cycle ~50+ for ball_x=78 (beam at x=78 ~cycle 49)
    ; NOP padding to align RESBL after cycle 49
    NOP                 ; 2
    NOP                 ; 2
    NOP                 ; 2
    NOP                 ; 2
    NOP                 ; 2
    NOP                 ; 2
    NOP                 ; 2
    NOP                 ; 2   ~16 cycles padding (cycles 21-36)
    NOP                 ; 2
    NOP                 ; 2
    NOP                 ; 2
    NOP                 ; 2
    NOP                 ; 2
    NOP                 ; 2
    NOP                 ; 2
    NOP                 ; 2   ~32 cycles padding (cycles 37-52)
    STA RESBL           ; 4   reset ball position (cycle ~53+)
    DEC orb_row_idx     ; 5
    BNE OrbLoop         ; 2/3
```

**Cycle analysis**:

| Path | Cycles | Rest | Notes |
|---|---|---|---|
| Orb row (ball on) | ~62 | 58 | CTRLPF+ENABL+NOPs+RESBL |
| Orb row (ball off) | ~62 | 58 | Same but ENABL=0 (ball invisible) |
| Non-orb rows | ~38 | 34 | Main kernel (38 cycles, no ball event) |

Worst case: 62 cycles (slack 14). The NOP padding aligns RESBL after the beam
reaches ball_x. For ball_x=78: beam reaches ~cycle 49, RESBL fires ~cycle 53.
For ball_x=0: beam reaches ~cycle 23, RESBL fires ~cycle 53 (ball shifted
right by ~30 pixels -- **horizontal offset**).

**Problem**: The NOP padding is fixed but ball_x varies. For small ball_x,
RESBL fires too late and the ball shifts right. The NOP count must be
adaptive (computed per frame based on ball_x), which adds VBLANK cost and
RAM for a computed delay.

**Adaptive delay**: compute `delay = 53 - (ball_x * 3/7 + 23)` in VBLANK.
This requires a multiply or lookup table. ~20-30 bytes ROM, 1-2 bytes RAM.

**RAM**: 1 byte (orb_row_idx) + 1 byte (orb_delay) = 2 bytes.
**ROM**: +80-120 bytes (mini-loop, lookup tables, VBLANK delay computation).
**Event table**: No change -- ball events are skipped in BuildEvents.
**Collision**: Ball collision latches still detect per-pixel overlap. The
narrower rows produce fewer collision pixels. The ball's horizontal position
is determined by RESBL timing, which may differ from the current PositionBall.
Collision semantics may shift (ball appears at different x than expected).
**Risk**: MEDIUM -- timing complexity, adaptive delay, collision x-shift.

**Verdict**: VIABLE but complex. The adaptive delay and collision x-shift
make this risky. The cycle budget (62 worst) is acceptable.

---

## Family 3: Playfield Rendering (PF0/PF1/PF2)

**Approach**: Use the playfield registers to render the orb shape instead of
(or in addition to) the Ball object. The playfield can be written per-scanline
and produces 40-pixel-wide mirrored or asymmetric output.

**Problem**: The playfield spans the LEFT half of the screen (pixels 0-79).
The ball is typically at x=78 (center). The right half (pixels 80-159) is
only available with playfield mirroring, which duplicates the left half.

With mirrored playfield: PF output appears at both x and 159-x. For ball at
x=78: PF pixel at x=78 mirrors to x=81. The orb would appear at BOTH x=78
and x=81 -- **double image**.

With asymmetric playfield: PF output only on left half. Ball at x=78 is on
the right half -- **invisible**.

**Verdict**: REJECTED -- playfield cannot render at the ball's position without
artifacts. The 40-pixel limitation and mirroring behavior make this impractical.

---

## Family 4: Color Luminance Gradient Illusion

**Approach**: Change COLUPF per scanline to create a luminance gradient across
the ball's 4 rows, simulating depth/roundness through shading rather than
shape.

```
Row 0: $0E (bright white)  -- highlight
Row 1: $0C (medium white)  -- mid-tone
Row 2: $0A (dim white)     -- shadow
Row 3: $08 (dark white)    -- deep shadow
```

**Cycle analysis**:

COLUPF ($08) is at address offset 8. The event kernel writes at cycles 15
(write 1) and 27 (write 2). COLUPF at offset 8 is below the x >= 15 gate
for write 2, so it must be write 1.

For a 4-row ball with per-row color: 4 color-change events + 1 restore event
= 5 events for the ball. Plus 8 player/missile events = 13 total. Exceeds
EV_MAX_EVENTS = 10.

**Alternative**: Change COLUPF in the event kernel's apply block by adding a
third write. This breaks the constant-cost invariant (54 cycles worst becomes
~68 cycles). Slack drops from 22 to 8. Acceptable but tight.

**Alternative**: Use the orb mini-loop (Family 2) with COLUPF writes instead
of CTRLPF. The color change happens before the beam reaches the ball, so
timing is simpler (no RESBL alignment needed).

```asm
OrbColorLoop:
    STA WSYNC           ; 3
    LDA orb_color_tbl,X ; 4
    STA COLUPF          ; 3   set ball color for this row
    LDA #BALL_ENABLE    ; 2
    STA ENABL           ; 3   enable ball
    ; ball renders at x=78 with the color just set
    ...                 ; NOPs to fill scanline
    DEC orb_row_idx     ; 5
    BNE OrbColorLoop    ; 2/3
```

**Visual result**: Luminance gradient creates depth illusion but the ball
remains rectangular (4x4 block with varying brightness per row). Not a
shape change -- a shading effect.

**RAM**: 1 byte (orb_row_idx) + 4 bytes (color table) = 5 bytes.
**ROM**: +40-60 bytes (mini-loop, color table).
**Event table**: Ball color events removed from table (handled by mini-loop).
**Collision**: No change -- ball shape is still 4x4 rectangular.
**Risk**: LOW -- simple implementation, no timing complexity.

**Verdict**: VIABLE as a complementary technique. Does not produce rounded
shape but adds visual interest. Could be combined with Family 2 or 8.

---

## Family 5: NUSIZ Multiplexing

**Approach**: Use NUSIZ0/NUSIZ1 to create multiple copies of a player object
at different horizontal positions, combining them to form the orb shape.

**Problem**: NUSIZ is per-frame only (written during VBLANK, takes effect on
the next frame). Cannot be changed per-scanline. The orb shape would be
static for the entire frame.

Additionally, NUSIZ affects player objects (P0/P1), which are already used
for the wizards. Repurposing a player for the orb removes a wizard.

**Verdict**: REJECTED -- NUSIZ is per-frame only and players are occupied.

---

## Family 6: RESP Repositioning

**Approach**: Use RESP0/RESP1 to reposition a player object per-scanline,
creating the orb shape by varying the horizontal position of a player sprite.

**Problem**: RESP resets the position counter, which takes effect when the
beam next reaches the reset point. This is the same mechanism as RESBL but
for player objects. However:

1. Players P0/P1 are occupied by wizards.
2. RESP repositioning shifts the ENTIRE player sprite, not just the ball.
3. The player sprite would need to be reconfigured per-row (GRP0/GRP1
   changes), which requires additional writes.

**Verdict**: REJECTED -- players are occupied, and the approach requires
per-row GRP changes that exceed the event budget.

---

## Family 7: Ball Object + Color Illusion (Combined)

**Approach**: Combine the current rectangular ball with a per-scanline
COLUPF gradient (Family 4) to create a "rounded" visual impression through
shading, even though the shape remains rectangular.

**Visual result**:

```
Row 0: $0E  XXXX  (bright)
Row 1: $0C  XXXX  (medium)
Row 2: $0A  XXXX  (dim)
Row 3: $08  XXXX  (dark)
```

This creates a top-lit sphere illusion. The rectangular shape is mitigated
by the luminance gradient.

**Implementation**: Use the orb mini-loop (Family 2) with COLUPF writes
instead of CTRLPF. Simpler than CTRLPF because no RESBL alignment is needed.

**RAM**: 1 byte (orb_row_idx) + 4 bytes (color table) = 5 bytes.
**ROM**: +30-50 bytes (mini-loop, color table).
**Event table**: Ball events removed (handled by mini-loop). Saves 2 events.
**Collision**: No change -- ball is still 4x4 rectangular.
**Risk**: LOW.

**Verdict**: VIABLE. Simple, low-risk, adds visual interest. Not truly
"rounded" but improves the visual impression.

---

## Family 8: Dedicated Orb Kernel Specialization (Orb Mini-Loop with CTRLPF)

**Approach**: A dedicated "orb mini-loop" running exactly BALL_HEIGHT
scanlines before the main kernel, handling ENABL + CTRLPF changes per row.
The ball's horizontal position is re-synchronized with RESBL on each scanline.
This is the most ambitious approach and the strongest candidate for a true
rounded shape.

**Implementation**:

```asm
; --- Orb mini-loop (runs BALL_HEIGHT scanlines before kernel) ---
; Y = ball_y - 2 (orb starts 2 rows above ball center)
; orb_row_idx counts down from BALL_HEIGHT

OrbLoop:
    STA WSYNC               ; 3   start of scanline
    ; ---- set ball width for this row ----
    LDX orb_row_idx         ; 3   0..BALL_HEIGHT-1
    LDA orb_width_tbl,X     ; 4   CTRLPF value (narrow/wide)
    STA CTRLPF              ; 3   set ball width (write at cycle 13)
    ; ---- enable/disable ball ----
    LDA orb_enabl_tbl,X     ; 4   ENABL value (on/off)
    STA ENABL               ; 3   enable ball (write at cycle 20)
    ; ---- reposition ball (RESBL must fire after beam reaches ball_x) ----
    ; For ball_x=78: beam reaches ~cycle 49
    ; NOP padding to align RESBL after cycle 49
    .rept 16
    NOP                     ; 2   each NOP = 2 cycles
    .endr                   ; 32 cycles padding (cycles 21-52)
    STA RESBL               ; 4   reset ball position (cycle ~53)
    ; ---- count down ----
    DEC orb_row_idx         ; 5
    BNE OrbLoop             ; 2/3
    ; ---- restore CTRLPF default ----
    LDA #BALL_SIZE_CTRLPF   ; 2
    STA CTRLPF              ; 3   restore default width
```

**Cycle analysis**:

| Path | Cycles | Rest | Notes |
|---|---|---|---|
| Orb row (ball on) | ~66 | 62 | CTRLPF+ENABL+16 NOPs+RESBL+countdown |
| Orb row (ball off) | ~66 | 62 | Same but ENABL=0 |
| Non-orb rows (kernel) | 38 | 34 | Standard event kernel |

Worst case: 66 cycles (slack 10). Under the ≤64 target but under ≤70 danger
bound. Acceptable.

**Horizontal positioning problem**: The NOP count is fixed but ball_x varies.
For ball_x=78: beam reaches ~cycle 49, RESBL at ~cycle 53 (correct). For
ball_x=0: beam reaches ~cycle 23, RESBL at ~cycle 53 (ball shifts right by
~30 pixels). For ball_x=156: beam reaches ~cycle 75, RESBL at ~cycle 53
(ball shifts left).

**Solution**: Compute the NOP delay adaptively in VBLANK:

```asm
; delay_count = (ball_x * 3 / 7) + offset
; or use a 160-entry lookup table (160 bytes -- too expensive)
; or use a coarse+fine approach: coarse (bank of NOPs) + fine (computed)
```

A simpler approach: use HMBL for fine positioning instead of RESBL. HMBL
applies a -8..+7 pixel fine offset. Combined with coarse RESP positioning
(set once in VBLANK), HMBL can adjust the ball's position by up to 7 pixels
per scanline. But HMBL is per-frame only (requires HMOVE strobe).

**Alternative**: Accept the horizontal offset and adjust ball_x in the game
logic to compensate. If the orb mini-loop shifts the ball right by N pixels,
set ball_x = ball_x - N in UpdateBall. This is a fixed offset, not
adaptive. Simple but imprecise.

**Best approach**: Use RESBL with an adaptive delay computed from ball_x.
The delay formula: `delay_cycles = 53 - (23 + ball_x * 52 / 156)`.
This requires a multiply or lookup. Cost: ~30-40 bytes ROM, 1-2 bytes RAM.

**RAM**: 1 byte (orb_row_idx) + 1 byte (orb_delay) = 2 bytes.
**ROM**: +80-120 bytes (mini-loop, lookup tables, VBLANK delay computation).
**Event table**: Ball events removed from BuildEvents. Saves 2 events.
**Collision**: Ball collision latches detect per-pixel overlap. The narrower
rows (2 pixels) produce fewer collision pixels than the current 4-pixel rows.
The ball's effective hit box changes per row. Collision semantics are
**different** from the current rectangular ball.
**Risk**: MEDIUM -- timing complexity, adaptive delay, collision shape change.

**Verdict**: VIABLE. Produces a true diamond shape. The adaptive delay and
collision shape change are manageable risks.

---

## Comparison Matrix

| Metric | F1: Event CTRLPF | F2: Mini-Loop CTRLPF | F3: Playfield | F4: Color Gradient | F5: NUSIZ | F6: RESP | F7: Ball+Color | F8: Orb Mini-Loop |
|---|---|---|---|---|---|---|---|---|
| **Visual result** | Diamond | Diamond | N/A | Shading | N/A | N/A | Shading | Diamond |
| **Shape change** | Yes | Yes | No | No | No | No | No | Yes |
| **Kernel worst** | 54 | 62 | N/A | 68 | N/A | N/A | 50 | 66 |
| **Kernel slack** | 22 | 14 | N/A | 8 | N/A | N/A | 26 | 10 |
| **RAM delta** | 0 | +2 | N/A | +5 | N/A | N/A | +5 | +2 |
| **ROM delta** | +20-40 | +80-120 | N/A | +30-50 | N/A | N/A | +30-50 | +80-120 |
| **Event table** | +4 events | No change | N/A | +3 events | N/A | N/A | -2 events | -2 events |
| **Event overflow** | YES (14>10) | No | N/A | YES (13>10) | N/A | N/A | No | No |
| **Collision change** | Minor | Yes | N/A | None | N/A | N/A | None | Yes |
| **Timing risk** | HIGH | MEDIUM | N/A | LOW | N/A | N/A | LOW | MEDIUM |
| **Complexity** | HIGH | MEDIUM | N/A | LOW | N/A | N/A | LOW | MEDIUM |
| **Viable** | NO | YES | NO | YES | NO | NO | YES | YES |

---

## Top 3 Recommended Alternatives

### Alternative A: Orb Mini-Loop with CTRLPF (Family 8) -- RECOMMENDED

**Shape**: True diamond (2-4-4-2 pixel rows)
**Visual**:
```
.XX.     row 0: CTRLPF narrow (2px), ENABL on
XXXX     row 1: CTRLPF wide (4px), ENABL on
XXXX     row 2: CTRLPF wide (4px), ENABL on
.XX.     row 3: CTRLPF narrow (2px), ENABL on
```

**Kernel impact**: +12 cycles worst case (54 -> 66). Slack 10. Acceptable.
**RAM**: +2 bytes (orb_row_idx, orb_delay).
**ROM**: +80-120 bytes (mini-loop, lookup tables).
**Event table**: Ball events removed from BuildEvents (saves 2 events).
**Collision**: Ball hit box changes per row (narrower at tips). Gameplay
impact: the ball is harder to hit at the tips, easier in the middle.
**Risk**: MEDIUM -- adaptive delay complexity, collision shape change.

**Expected post-implementation metrics**:
- ROM: ~1900-1930 / 4096 bytes
- RAM: 83 / 128 bytes
- Kernel worst: 66 / 76 cycles (slack 10)
- Frame: 262 scanlines (unchanged)

### Alternative B: Ball + Color Gradient (Family 7) -- SIMPLEST

**Shape**: Rectangular (4x4) with luminance gradient
**Visual**:
```
XXXX     row 0: $0E (bright)
XXXX     row 1: $0C (medium)
XXXX     row 2: $0A (dim)
XXXX     row 3: $08 (dark)
```

**Kernel impact**: -4 cycles (ball events removed from table). Worst 50.
**RAM**: +5 bytes (orb_row_idx + 4-byte color table).
**ROM**: +30-50 bytes.
**Event table**: Ball events removed (saves 2 events).
**Collision**: No change -- ball remains 4x4 rectangular.
**Risk**: LOW.

**Expected post-implementation metrics**:
- ROM: ~1840-1860 / 4096 bytes
- RAM: 86 / 128 bytes
- Kernel worst: 50 / 76 cycles (slack 26)
- Frame: 262 scanlines (unchanged)

### Alternative C: CTRLPF Width Changes with Mini-Loop (Family 2) -- MIDDLE GROUND

**Shape**: Diamond (2-4-4-2) with simpler implementation than Family 8
**Visual**: Same as Alternative A.

**Kernel impact**: +8 cycles (54 -> 62). Slack 14.
**RAM**: +2 bytes.
**ROM**: +80-120 bytes.
**Event table**: Ball events removed.
**Collision**: Same as Alternative A.
**Risk**: MEDIUM -- but without RESBL alignment, the ball's horizontal
position shifts based on ball_x (see Family 2 analysis).

**Expected post-implementation metrics**:
- ROM: ~1890-1930 / 4096 bytes
- RAM: 83 / 128 bytes
- Kernel worst: 62 / 76 cycles (slack 14)
- Frame: 262 scanlines (unchanged)

---

## Recommendation

**Primary recommendation: Alternative A (Family 8 -- Orb Mini-Loop with CTRLPF)**

Rationale:
1. Produces a **true diamond shape** (not just shading).
2. The kernel worst case (66 cycles) is within the ≤70 danger bound.
3. RAM cost (+2 bytes) is minimal. ROM cost (+80-120 bytes) is acceptable
   (2544 bytes free).
4. The ball events are removed from the event table, freeing 2 slots.
5. The collision shape change is a **feature** -- the ball is harder to hit
   at the tips, which adds gameplay depth.

**Fallback: Alternative B (Family 7 -- Ball + Color Gradient)**

If the adaptive delay complexity of Alternative A is judged too risky,
Alternative B provides visual improvement with minimal risk. The ball remains
rectangular but the luminance gradient adds depth.

---

## Known Limitations

1. **Collision shape change**: Both Alternative A and C change the ball's hit
   box per row. This is a gameplay change that must be documented and tested.
2. **Adaptive delay**: Alternative A requires computing a per-frame delay
   for RESBL alignment. This adds VBLANK cost and ROM.
3. **Horizontal offset**: Alternative C (simpler mini-loop) accepts a fixed
   horizontal offset that varies with ball_x. This may be visually
   unacceptable for extreme ball positions.
4. **Color gradient**: Alternative B does not change the ball's shape, only
   its shading. It is not a "rounded" ball in the geometric sense.
5. **All approaches**: The Atari 2600 TIA Ball is fundamentally a horizontal
   line. True roundness (curved edges) is impossible. The diamond shape is
   the best approximation at this resolution.

## Tests

No tests were added because no code was modified.

## Next Logical Steps

1. Prototype Alternative A (orb mini-loop with CTRLPF) in a test ROM.
2. Validate kernel timing (66 cycles worst case) on the deterministic
   emulator.
3. Validate collision semantics with the new ball shape.
4. Validate frame timing (262 scanlines) with the orb mini-loop.
5. If successful, implement in the main game and document.
