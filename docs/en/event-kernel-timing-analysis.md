# Event Kernel Timing Analysis: the 263-scanline double-event bug

Status: RESOLVED - the delta=1 fix (Round 11) implements the recommended
Option A (table-direct apply); see section 14 for the final numbers.

Date: 2026-08-20

Companion Portuguese document: `docs/pt-BR/analise-timing-kernel-eventos.md`.

## Summary

A **double event** (two register writes on one scanline) makes the visible
kernel overrun its 76-cycle budget. The double path costs **77 CPU cycles**
after the `WSYNC` (the event-line "rest" is 73 cycles). Any event line whose
rest exceeds 71 cycles pushes the frame from 262 to 263 scanlines. The bug
reproduces on the assembled ROM with a deterministic emulator, is caught by
the existing regression suite, and has two candidate fixes analysed at the end
of this document.

---

## 1. Exact reproduced Ball artifact scenario

Deterministic injection, applied to RAM just before `BuildEvents` runs (the
same technique as `tests/test_frame_timing.py`):

| Variable | Value |
| --- | --- |
| `P0Y` | 88 |
| `P1Y` | 50 |
| `ball_y` | 88 |
| `m0_y`, `m1_y` | 88 |
| `m_active` | 0 |
| `p0_hp`, `p1_hp` | 3 |

Resulting event table (bytes, after `ConvertDeltas`):

```
offset  delta  reg1    val1  reg2  val2    meaning
  0      50     0x82    60           -     P1 ON      (single)
  3      12     0x82     0           -     P1 OFF     (single)
  6      26     0x01    60     0x05    2   P0 ON + Ball ON   (DOUBLE)
 11       4     0x85     0           -     Ball OFF   (single)
 14       8     0x81     0           -     P0 OFF     (single)
 17      85     0x7F     0           -     marker     (single)
```

`reg1 = 0x01` = `EV_REG_GRP0` (P0 sprite ON, value `PADDLE_BITS` 60);
`reg2 = 0x05` = `EV_REG_ENABL` (ball ON, value `BALL_ENABLE` 2). The double
fires on **line 87** of the kernel.

Measured on the deterministic emulator (`tools/emu6502.py`):

* the double event line runs **121** cycles (WSYNC step 48 + rest 73);
* the following line runs **107** cycles (WSYNC step 79 + rest 28);
* the pair consumes **228 cycles = 3 scanlines** instead of 2;
* every frame in this state runs **19988 cycles = 263 scanlines** (baseline
  is 19912 = 262), repeated across 6 consecutive injected frames.

## 2. Exact event combination that triggers the problematic path

Any **two events merged onto one scanline** (a 5-byte "double" entry): the
kernel must apply both writes AND decode the next entry on the same line.
Reproduced combinations:

* P0 ON + Ball ON (the manual injection above);
* P1 ON + Ball OFF on row 127, which occurs **naturally** under the collision
  stress in `test_vblank_never_overruns_with_realistic_branch_timing`
  (frame 24: 19988 cycles = 263 scanlines, double entry
  `(row 127, reg1=GRP1, val1=60, reg2=ENABL, val2=0)`).

The `InsertEvent` merge logic (generation order: existing event keeps write 1,
new event takes write 2) is what creates doubles. Any same-row merge of two
objects produces one.

## 3. Cycle-by-cycle proof of the current kernel path

Kernel disassembly (`$F100`-`$F15F`), with real 6502 costs. The `rest` is all
instructions between the `STA WSYNC` completion and the next `STA WSYNC`.

Double event line:

```
$F100  STA WSYNC            4     (WSYNC adds alignment; not part of rest)
$F102  LDX pendReg1         3
$F104  LDA pendVal1         3
$F106  STA $1A,X            4     write 1
$F108  LDX pendReg2         3
$F10A  LDA pendVal2         3
$F10C  STA $1A,X            4     write 2
$F10E  DEC evCnt            5
$F110  BNE $F100            2     not taken (evCnt hit 0)
$F112  LDA evTbl+1,Y        4     reg1 | EV_SINGLE_FLAG
$F115  BMI $F134            2     not taken (double: no single flag)
$F117  STA pendReg1         3
$F119  LDA evTbl+2,Y        4     val1
$F11C  STA pendVal1         3
$F11E  LDA evTbl+3,Y        4     reg2
$F121  STA pendReg2         3
$F123  LDA evTbl+4,Y        4     val2
$F126  STA pendVal2         3
$F128  TYA                  2
$F129  ADC #5               2
$F12B  TAY                  2     advance to next entry
$F12C  LDA evTbl,Y          4     next delta
$F12F  STA evCnt            3     reload countdown
$F131  JMP $F100            3     back to WSYNC
       ---------------------------------
       rest = 73 cycles      (path = 73 + 4 = 77 cycles)
```

Single event line (same front; BMI taken at `$F115`):

```
... front (STA..BNE)        20+5+2
$F112  LDA evTbl+1,Y        4
$F115  BMI $F134            3     taken
$F134  AND #$7F             2
$F136  CMP #$7F             2
$F138  BEQ $F151            2     not taken (not the marker)
$F13A  STA pendReg1         3
$F13C  LDA evTbl+2,Y        4
$F13F  STA pendVal1         3
$F141  LDA #0               2
$F143  STA pendReg2         3
$F145  TYA / ADC #3 / TAY   6     advance by 3
$F149  LDA evTbl,Y          4
$F14C  STA evCnt            3
$F14E  JMP $F100            3
       ---------------------------------
       rest = 71 cycles      (path = 75 cycles)
```

Non-event line:

```
$F100  STA WSYNC            4
$F102..$F10C write block   20
$F10E  DEC evCnt            5
$F110  BNE $F100            3     taken
       ---------------------------------
       rest = 28 cycles      (path = 32 cycles)
```

Emulator-confirmed line totals (with the WSYNC alignment):

| Line | WSYNC step | rest | total |
| --- | --- | --- | --- |
| non-event | 48 | 28 | 76 |
| single event | 48 | 71 | 119 |
| double event | 48 | 73 | 121 |
| line after single | 5 | 28 | 33 |
| line after double | 79 | 28 | 107 |

## 4. Why the current path reaches 77 cycles

Every piece of the double path is at its 6502 floor:

* writes: 2 x (LDX zp 3 + LDA zp 3 + STA zp,X 4) = 20 - minimal;
* countdown: DEC zp 5 + BNE 2 = 7 - minimal;
* flag test: LDA abs,Y 4 + BMI 2 = 6 - minimal;
* decode stores: 4 x (LDA abs,Y 4 + STA zp 3) = 28, and reg1 reuses the flag
  test load - minimal;
* advance: TYA/ADC #5/TAY = 6 (see section 6 - minimal);
* reload: LDA abs,Y 4 + STA zp 3 = 7 - minimal;
* closing JMP: 3.

The event line must apply 2 writes, decode the next entry (reg1/val1/reg2/val2
+ advance + reload) and restart the scanline, all inside one 76-cycle line.
The decode alone is 46 cycles (flag 6 + stores 28 + advance 6 + reload 7,
minus the front which is shared). Nothing in the path can be shortened without
changing the architecture (sections 6 and 8).

## 5. Why that causes the observed Ball artifact

Frame stability condition. Kernel lines run at a fixed phase: a line's rest `r`
modulo 76 determines the phase of the next line. A line is *safe* if `r <= 71`
(after a rest-72 or rest-73 line the frame slips):

* `r <= 71`: the event line (48 + r) plus the compensating next line always
  sum to **152 = exactly 2 scanlines** (48+r + 104-r = 152). The phase
  returns to steady state and the frame stays 262.
* `r = 72`: the next `WSYNC` write lands exactly on a 76-boundary (rem 0) and
  the model adds a full extra line; the pair becomes 228 cycles = 3 scanlines.
* `r = 73`: the pair is 121 + 107 = 228 cycles = 3 scanlines (measured).

The double event has `r = 73`, so the pair consumes 3 scanlines and every
frame becomes 263 scanlines. The Ball artifact is the *whole-frame* vertical
shift (one extra scanline pushes every object down one line for that frame).
Because a double can involve the ball (P0+Ball ON, P1+Ball OFF), the artifact
is commonly seen on the ball, but it is not ball-specific: **any** same-row
merge of any two objects triggers it.

Note: the ball's horizontal position does **not** enter the kernel path - the
kernel is built purely from rows. X only matters for the write-vs-beam timing
(Round 8/9, section 9), which the current kernel satisfies.

## 6. Why the previously proposed `nextPtr` optimization is impossible

The plan was to extend each table entry with a "next entry pointer" byte so
the kernel could advance with a 4-cycle `LDY evTbl+5,Y` (or `+3`) instead of
the 6-cycle `TYA / ADC #5 / TAY`.

The 6502 has **no `LDY abs,Y` addressing mode**. The `abs,Y` modes exist only
for `ADC, AND, CMP, EOR, LDA, LDX, ORA, SBC, STA` (verified against the
opcode matrix). The valid substitutes all cost the same 6 cycles as the
current advance:

* `LDA evTbl+5,Y` (4) + `TAY` (2) = 6;
* or keep `LDA evTbl+5,Y` in A and use it as the delta directly = 4 + 3 (STA
  evCnt) = 7, which is *more* than the current 6 + 7.

So the `nextPtr` format saves **zero** cycles and was abandoned.

## 7. All realistic alternatives investigated

For the current architecture the required reduction is **2 cycles** (rest 73
must become <= 71):

1. **Restructure the double tail.** Flag test (6), stores (28), advance (6),
   reload (7) are all at their 6502 floor; `DEC evCnt`/`BNE` (7) is minimal.
   No single instruction can be removed or shortened.
2. **`nextPtr` table format.** Invalid: no `LDY abs,Y` (section 6).
3. **Avoid RAM state / heuristics to save one cycle.** The pending-write
   scheme is itself the speed mechanism (writes are 10 cycles each because the
   values sit in zero page); loading from the table instead costs 14 each
   (section 10). There is no cheaper arrangement.
4. **Eliminate the closing `JMP` by code layout** (discovered in this
   analysis). The decode block can be placed immediately before
   `KernelLoop`, so the countdown `BNE` (taken for non-event lines) jumps to
   the WSYNC and the "not taken" path falls *into* the decode, whose reload
   then falls *through* into the WSYNC. This removes the 3-cycle `JMP`:
   double rest 73 -> **70**, single rest 71 -> **68**. Both are <= 71, so the
   frame returns to 262 with **no RAM change** and the write timing
   untouched. Margin: the double path has only **1 cycle** of headroom below
   the 71 bound (and 2 below the 76 budget).
5. **Split the decode across two lines (prefetch).** Load half the next entry
   on the line where `evCnt == 2` and half where `evCnt == 1`, so the event
   line itself only applies writes. The prefetch lines would run at rest
   ~43 and ~58 (both <= 71). Rejected as too complex: the kernel must test
   `evCnt` against 1 and 2 every line (extra CMP/BNE pairs), must still know
   whether the *next* entry is single or double (variable-size format keeps
   the flag tests), and the builder is untouched only if the format stays
   variable - the gain over option 4 is marginal.

Option 4 is viable and is the "smaller change" candidate; option 1 with the
table-direct format is the large-but-durable candidate. Both are costed in
section 14.

## 8. Proposed architecture A: uniform 5-byte table-direct kernel

### Old event representation

Two variable-size formats, distinguished by bit 7 of the reg1 byte:

```
single (3 bytes): [delta, reg1|EV_SINGLE_FLAG, val1]
double (5 bytes): [delta, reg1, val1, reg2, val2]
marker  (3 bytes):[delta, EV_MARKER_REG, val]
```

The kernel copies an entry into four zero-page pending registers on the
previous event line, then applies them at the start of each scanline. The
decode cost is what overruns the budget.

### New event representation

One uniform format for every entry (including the marker):

```
entry (5 bytes): [delta, reg1, val1, reg2, val2]
marker (5 bytes):[delta, 0, $FF, 0, 0]   val1 = $FF is the end sentinel
null   (5 bytes):[delta, 0, 0, 0, 0]     padding/prime entry at Y = 0
```

* singles set `reg2 = 0, val2 = 0` (a benign write to `$1A`, the reserved
  TIA byte `EV_WRITE_BASE + 0`);
* the marker is detected by `val1 == $FF` (the decode reads `evTbl+2,Y`);
  its reg/val bytes are 0 so its own writes are benign;
* `EV_SINGLE_FLAG`, `EV_MARKER_REG`, `EV_MARKER_INDEX` are deleted.

Table layout: `[null] + up to EV_MAX_EVENTS entries + [marker]`.

### Old kernel flow

```
WSYNC -> apply pendingReg1/val1 -> apply pendingReg2/val2
      -> DEC evCnt -> BNE WSYNC
      -> (evCnt == 0) LDA evTbl+1,Y -> BMI single
           double: STA pendReg1/val1/reg2/val2 (4 loads), TYA/ADC#5/TAY,
                   LDA evTbl,Y, STA evCnt, JMP
           single: AND#7F, CMP#7F, BEQ marker-end, STA pendReg1/val1,
                   pendReg2=0, TYA/ADC#3/TAY, reload, JMP
```

### New kernel flow

Every line reads its writes straight from the current table entry (Y never
changes except on event lines):

```
WSYNC
LDA evTbl+1,Y / TAX / LDA evTbl+2,Y / STA $1A,X    write 1 (14 cycles)
LDA evTbl+3,Y / TAX / LDA evTbl+4,Y / STA $1A,X    write 2 (14 cycles)
DEC evCnt -> BNE WSYNC                                (countdown)
(evCnt == 0) LDA evTbl+2,Y / CMP #$FF / BEQ marker    marker test
             TYA / CLC / ADC #5 / TAY                 advance (always +5)
             LDA evTbl,Y / STA evCnt                  reload delta
             fall through into WSYNC (no JMP)
```

No pending registers, no single/double distinction, no data-dependent
branching on the kernel path.

### Kernel cycle counts

| Line | cycles | rest | vs 71 bound |
| --- | --- | --- | --- |
| no event | 40 | 36 | 35 under |
| single event | 62 | 58 | 13 under |
| double event | 62 | 58 | 13 under |
| marker line | 48 | 44 | - |

Worst-case kernel path: **62 / 76 cycles** (slack 14). The event-line rest 58
pairs with the following line to exactly 152 cycles = 2 scanlines, so the
frame is 262 for every input. The cost is constant because the write block
and decode read fixed offsets - no branch depends on which objects fired, how
many writes the entry holds, the deltas, or the rows.

### BuildEvents changes

* `InsertEvent`: inserts a uniform 5-byte entry; same-row merge just fills
  `reg2/val2` at `+3/+4` (no shift, the entry is already 5 bytes wide);
  three-on-a-row bump logic unchanged; the single/double branching is
  deleted. A same-row merge writes generation order by default.
* `ConvertDeltas`: advances by 5 unconditionally (no flag test); marker delta
  = `KERNEL_SCANLINES - prevRow`.
* Priming: `Y = 0` points at the null entry; `evCnt = evTbl+5` (first real
  delta). A delta-0 prime sets `Y = 5`, `evCnt = evTbl+10`.

### Frame / stability proof for all inputs

Stability requires every event line's rest <= 71. In this kernel the event
rest is a **constant 58** regardless of:

* which two objects merged (reg1/reg2 = any of GRP0/GRP1/ENAM0/ENAM1/ENABL);
* the write values;
* the deltas (rows);
* the ball's X position (X never appears in the kernel; it only affects the
  RESBL horizontal position set in VBLANK).

There is no input that can make the event line exceed 62 cycles, so the
condition that produced rest 73 (and the 263-scanline frame) is structurally
unreachable. In particular, **every valid Ball X position (0..156) is safe**:
the kernel timing does not depend on X, and the write-timing guarantee for X
is covered separately below.

### Write timing and the horizontal guarantee

The Round 8/9 guarantee is "a write completes before the beam passes the
object's X on the target line" (beam model: pixel `p` at cycle `~(p+69)/3`;
pixel 0 at ~cycle 23). In this kernel:

* write 1 completes at **cycle 14** (gate covers all x >= -27, i.e. all x);
* write 2 completes at **cycle 28** (gate covers x >= 15).

P0 (x=16), P1 (x=136) and M0 (x >= 18) always satisfy the second gate, but
the ball (x 0..156) and M1 (x down to 2) can fall below 15. The builder must
therefore guarantee the ball and M1 never occupy slot 2. Two small rules in
`InsertEvent`:

* insert the ball and M1 events **before** the players and M0 (they naturally
  take slot 1 on a merge);
* never merge the ball with M1 (both have x < 15 reachable) - bump the M1
  event to row+1, reusing the existing three-on-a-row mechanism.

With these rules every second write targets P0/P1/M0 (x >= 15), so the
horizontal guarantee holds for all objects at all positions. Cost: a few
extra VBLANK instructions; the kernel is untouched.

### RAM breakdown (before / after)

Before (56 bytes used, $80-$B7):

```
$80-$81 P0Y/P1Y            $82-$83 p0_hp/p1_hp
$84-$87 ball_x/y/dx/dy     $88-$8B m0_x/m0_y/m1_x/m1_y
$8C m_active  $8D hit_flags  $8E fire_prev  $8F evCnt
$90 pendReg1 $91 pendVal1 $92 pendReg2 $93 pendVal2
$94-$B4 evTbl (33 bytes)   $B5 evRow  $B6 tempCount  $B7 tblLen
```

After (79 bytes used, $80-$CF):

```
$80-$8F unchanged (game state + evCnt)         16 bytes
$90-$93 freed (pending registers removed)       -4 bytes
$94-$CF evTbl = 5 + 10*5 + 5 = 60 bytes        +27 bytes
$B5-$B7 builder scratch unchanged               3 bytes
```

**Net: 56 - 4 + 27 = 79 bytes used, 49 available.**

### Why the increase is exactly 23 bytes

* the table grows 33 -> 60 (+27): null entry (5) + 10 uniform entries (50) +
  marker (5), versus 30 + 3 for the old worst case. In the worst case a
  single-only table is now 5 + 30 + 5 = 40 (was 33); a full table is 60;
* the four pending registers are deleted (-4);
* net +23.

### Can any of the 23 bytes be reused?

* The 4 freed pending bytes are genuinely dead (the kernel no longer needs
  them) and are reclaimed by the growth.
* The table is written during VBLANK (BuildEvents) and read during the
  display, so it must persist across the whole frame; it cannot overlap game
  state (which is read during VBLANK) or the builder scratch
  (`evRow`/`tempCount`/`tblLen`, which are live during the build).
* `tblLen`/`evRow`/`tempCount` could theoretically share bytes with the table
  after the build, but they are in the middle of a frame walk and the kernel
  needs the table intact - no safe overlap exists.

So **79 bytes is the true steady-state requirement**, not a conservative
allocation. The only way to shrink it is to reduce `EV_MAX_EVENTS` (each
entry costs 5 bytes): at 9 events the table is 55 bytes and RAM 74. Ten is
the natural cap (5 objects x ON/OFF = 10 distinct-row events; ON/OFF can
never share a row because every object is >= 2 pixels tall).

### Can the table be placed/reused differently?

The kernel reads entries with `LDA abs,Y` (16-bit base) and writes with
`STA $1A,X` (zero page), so the table could live anywhere in the address
space - but the only writable RAM on the 2600 is RIOT $80-$FF (128 bytes)
plus the stack page. The stack is live during VBLANK (JSRs), so the table
cannot use it. There is no alternative placement that avoids the +23.

### ROM estimate (before / after)

* Current ROM: 1552 / 4096 bytes (37.9%).
* The new kernel loses the single/double decode branching and the pending
  stores (saves ~10 bytes) but the write block grows (18 vs 12 bytes);
* BuildEvents loses the size branching in InsertEvent/ConvertDeltas (~15
  bytes saved) and gains the slot-ordering rules (~10 bytes);
* estimated result is **roughly neutral: 1530-1590 bytes** (well inside the
  4096 limit; not a constraint either way).

### VBLANK cost (before / after)

VBLANK code (movement, missiles, positioning, the build) is unchanged by the
kernel rewrite. `BuildEvents` gets slightly *cheaper* (no single/double size
branching, always-advance-by-5) plus the slot-ordering checks. Measured
current worst-case VBLANK work is ~4867 cycles against a timer expiry of
(77*64) = 4928 (margin ~61 cycles under the real limit; the conservative
"(77-1)*64 = 4864" formula is just a safety convention). Expected delta: a
few cycles either way - **not a driver of this change**.

### Expected impact on future gameplay RAM

49 bytes remain (of 128) with the table-direct design. For the current scope
(players, ball, two missiles, HP, hit flags) that is comfortable: roughly
10-20 additional bytes would absorb more objects or state. ROM headroom is
2544 bytes. The binding resource after this change is RAM, and it remains
adequate.

## 9. Does the table-direct design eliminate the Ball artifact for all valid Ball X positions?

Yes, for three independent reasons:

1. **Kernel cost is input-independent.** The event path is a constant 62
   cycles (rest 58) for every possible event table. The bug condition (rest
   73) is unreachable because no branch in the kernel depends on object data.
2. **Frame math is position-independent.** Any event line (rest 58) plus its
   following line sums to exactly 152 cycles = 2 scanlines, so the frame is
   262 regardless of the rows involved. X positions never enter the kernel.
3. **The horizontal (write-vs-beam) guarantee is preserved** by the builder
   slot-ordering rules (section 8), so no object - including the ball at any
   x in 0..156 - is written after its gate.

The one caveat is the second-write gate at cycle 28, which the ordering rules
are specifically designed to handle; without them, a ball/M1 in slot 2 at
x < 15 would reintroduce a horizontal artifact. This is the single most
important implementation detail to get right.

## 10. Is 79/128 the true steady-state requirement?

Yes. There is no temporary/builder memory whose lifetime does not overlap the
table:

* the table is live from BuildEvents (VBLANK) through the last kernel line;
* `evRow`, `tempCount`, `tblLen` are live *during* the build, when the table
  is being written - no overlap;
* the pending registers are deleted entirely;
* the four freed bytes are reclaimed by the table growth.

The only lever is `EV_MAX_EVENTS` (5 bytes per entry) - 79 is the true
requirement at the current 10-event cap.

## 11. Comparison of the two viable fixes

| Metric | Current (broken) | Option 4: JMP removal | Option A: table-direct |
| --- | --- | --- | --- |
| Double event rest | 73 | **70** | **58** |
| Single event rest | 71 | 68 | 58 |
| Worst kernel path | 77 | 74 | 62 |
| Kernel slack (76 - worst) | -1 (over) | 2 | 14 |
| Headroom below 71 bound | -2 (over) | 1 | 13 |
| Frame scanlines | 263 (bug) | 262 | 262 |
| RAM used / available | 56 / 72 | 56 / 72 | 79 / 49 |
| ROM (estimate) | 1552 | ~1550 | ~1530-1590 |
| Second write cycle | 23 | 23 | 28 |
| Builder changes | - | none | uniform format + slot rules |
| Tests needing changes | - | test_timing budget only | event model, timing, frame tests |
| Horizontal guarantee | all x | all x | all x *with* slot rules |

## 12. Recommendation

Weighing **kernel timing headroom for future features** against **RAM
headroom for future gameplay** (and not optimising solely for the current
bug):

* Option A (table-direct): the kernel worst case drops from 77 to a **constant
  62**, leaving 13 cycles of headroom below the danger bound and 14 below the
  76 budget. The constant, branch-free cost means *this class of bug cannot
  return* when gameplay grows (more objects, effects, per-line changes). Cost:
  +23 bytes RAM (49 free - still comfortable for the game's scope), a builder
  slot-ordering rule to preserve the horizontal guarantee, and a larger test
  overhaul.
* Option 4 (JMP removal): the smallest possible fix. Zero RAM, write timing
  untouched, all-x guarantee preserved. But the double event sits **1 cycle**
  from the 71-cycle danger bound - any future change that adds a single cycle
  to the event path (even one instruction on every line) silently re-breaks
  the frame and forces another kernel redesign.

**Recommendation: Option A (table-direct).** Kernel timing headroom is the
binding constraint: the kernel is the hardest subsystem to change and it has
already produced this bug once. The 1-cycle margin of the smaller fix is below
the project's own "timing correctness first" bar (AGENTS.md) for a codebase
whose gameplay is explicitly expected to evolve. 49 bytes of free RAM remains
adequate for the foreseeable scope, and ROM (2544 free) is not a constraint.

Fallback: if RAM conservation is judged more important than kernel headroom,
Option 4 is a sound immediate fix (rest 70) that should be paired with a
regression test asserting the double path stays <= 71 cycles.

## 13. Known limitations / notes

* The marker sentinel `val1 = $FF` reserves $FF as an impossible write value;
  if future gameplay needs to write $FF to a TIA register, the sentinel
  location must move (e.g., to `reg1 = $FF`, which is safe because the write
  block never writes `$1A + $FF`).
* The table-direct kernel writes a benign $FF to TIA $1A on the marker line
  (reserved register, harmless).
* All figures in this document come from the deterministic emulator
  (`tools/emu6502.py`) and the assembled listing; they have not been
  re-validated on Stella/hardware.

## 14. Resolution (Round 11, delta=1 fix): what was actually built

Option A was implemented with a small refinement over the sketch in section 8.
The analysis above assumed the event line would *fall through* into the next
`WSYNC` (saving the JMP). The implementation instead keeps a uniform
`JMP KernelLoop` at the end of every path (`.applyOnly`), which keeps the loop
structure fixed and lets the marker test reuse the same entry format. The
consequences:

* the apply block reads the last-decoded entry through `Y-5` (Y always points
  one entry past it), so **the apply runs unconditionally on every line** -
  this is the delta=1 fix: two events on consecutive rows (delta 1) can no
  longer collide, because the apply happens before the countdown, not after a
  deferred pending pipeline;
* the marker's sentinel moved to the entry's **delta byte** (`$FF`), read with
  `CMP #EV_MARKER_VAL` after loading `evCnt`; the marker path ends the kernel
  at the line's cycle 46;
* the null entry at offset 0 is a **dummy** (delta byte `$FF`, regs all zero),
  so the pre-first-event apply writes only AUDV0; real entries start at
  offset 5;
* measured kernel budgets (listing + emulator): **non-event 38, event 54,
  marker 46**, worst case 54/76 (slack 22, up from the analysis's predicted 62
  worst because the JMP adds 3 cycles to every path);
* write 1 completes at cycle **15** (safe for all x), write 2 at cycle **27**
  (safe for x >= 13 per the conservative beam model; the builder's slot rule
  requires x >= 15);
* RAM: the dummy adds 5 bytes over the analysis's null entry, and the pending
  registers are gone: **80 bytes used, 48 free** (analysis predicted 79/49);
* ROM: **1808 / 4096 bytes** (the analysis predicted ~1530-1590; the actual
  build is larger because the offset-aware builder and slot-ordering rules cost
  more than estimated, still far inside the limit).

The regression tests in `tests/test_event_collision.py`, `test_events.py` and
`test_frame_timing.py` validate the implemented kernel against the Python
model byte-for-byte and run the real kernel on the emulator for the exact
delta=1 scenes that were broken before.