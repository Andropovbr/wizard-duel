# Change: Ball write-slot ordering (1-scanline vertical shift)

## Objective

Fix a visual artifact reported on `round-5-basic-hp`: the Ball shows a small
vertical displacement (roughly one scanline) at certain scanlines. The
displacement is not a bottom stretch and not frame shake. Fix on the current
branch only (no new branch, no merge to main), with no new gameplay: the Ball
must keep constant height (`BALL_HEIGHT = 4`) at every X position and
regardless of which other objects share its rows.

## Symptom

* The Ball appears shifted down by one scanline at certain rows, most often
  when it is on the left side of the arena (reported around `ball_x` 15..27).
* The offset appears and disappears as the ball moves, and only affects the
  ball (the reported cases were the ball sharing a row with P0 at x=16).

## Reproduction

The reported frames were reproduced with a model-based sweep over the real
ROM's event-builder semantics: all 16,956 combinations of `ball_x` (0..156)
x scenario (ball alone; +P0; +P1; +M0; +M1; +M0+M1; forced shared rows for
ball ON and OFF). A gameplay simulation over 2,000 frames confirmed the
frequency: the ball occupies the **second write** of a shared row in 88
frames (4.4%), at `ball_x` values both below and above 63.

Instrumenting the deterministic emulator gave the exact write cycles inside
an event scanline:

| Write slot      | Landing cycle | Beam-model gate |
| --------------- | ------------- | --------------- |
| First (double)  | 30            | x >= 21         |
| Second (double) | 44            | x >= 63         |
| Single          | 33            | x >= 30         |

## Root cause

A double entry fires two writes on the same scanline but at different times:
the first lands at CPU cycle 30 and the second at cycle 44. A TIA write only
applies to the current scanline if it completes before the beam passes the
object's X; otherwise it applies one scanline later. The second write is
~42-49 pixels behind the first, so an object in the second slot is exposed
whenever its X is below the second gate (x < 63 on the documented beam
model).

Before Round 8 a same-row merge kept generation order: the existing event
became the first write and the new event the second. `BuildEvents` generates
events in the order P0, P1, Ball, M0, M1, so a ball event merging into a
player or missile single was always written **second**. Since the ball's X
spans the whole arena (0..156), whenever the ball shared a row and sat left
of the second gate its ON/OFF fired one scanline late, shifting the whole
ball down one line (height stayed 4, position moved).

## Policy evaluation (rejected approaches)

A quantitative comparison of three scheduling policies was run over the same
16,956-combination sweep:

| Policy | Ball failures (of 16956) | Notes |
| ------ | ------------------------ | ----- |
| Insert order (pre-fix) | 4957 | ball takes the second slot on shared rows |
| X-deadline ordering | 4429 | pure deadline ordering does not fix the report: P0 (x=16) is always left of the ball for `ball_x > 16`, so the ball still lands second on shared P0 rows |
| Ball-first (adopted) | 2890 | height changes nearly eliminated; residual failures are the ball-alone `x < 30` band and the co-object taking the second slot |

Pure deadline ordering was rejected because it cannot fix the reported
P0-collision frames without a full kernel restructure, at a real ROM cost.
Ball-first gives the ball the earliest write (cycle 30) in every double and
the only other write it can get is a single (cycle 33), so its worst case
drops from the second gate (63) to the first/single gates (21/30).

## Fix

`InsertEvent` (`.mergeSingle`, src/main.asm) now swaps the merged ball event
into the **first** write: after storing reg2/val2 (the new event) and
reg1/val1 (the existing single), if the new register is `EV_REG_ENABL` the
two (reg, val) pairs are exchanged, with the single flag cleared off the
register that becomes reg2. The swap is safe by construction: reg1 of a
merge can never already be ENABL (a merge only happens into a single entry,
and `ball_y != ball_y + 4`). The co-object then takes the second write.

## Added

* `tests/test_event_collision.py` - `TestBallWriteSlotInvariant` (3 tests)
  driving the REAL ROM's `BuildEvents` across every forced ball/player and
  ball/missile row collision plus a full-arena ball sweep, asserting no
  double entry ever carries ENABL in the second slot and every table stays
  delta-0-free.
* `tests/test_events.py` - `TestBallBeamModel` (2 tests): a model-level beam
  regression (documented beam model + measured write cycles) asserting ENABL
  never occupies the second slot across the scenario matrix and that the
  ball's rendered height is exactly `BALL_HEIGHT` for every `x >= 30` (above
  the single-write gate) regardless of which objects share its rows.
* `tests/test_events.py` - `test_non_ball_merge_keeps_generation_order`
  (guards that only the ball is ordered into reg1).

## Changed

* `src/main.asm`, `InsertEvent` `.mergeSingle`: ball-first swap (+~40 bytes)
  and updated comments. `BuildEvents` and kernel comments document the new
  write-slot rule.
* `tests/test_events.py`: the Python `insert()` model implements the same
  swap; `test_same_row_events_merge` now asserts Ball ON is the first write
  and P1 ON the second.
* `docs/en/architecture.md` and `docs/pt-BR/arquitetura.md`: Round 8 section
  on ball write-slot ordering.
* `docs/en/timing.md` and `docs/pt-BR/timing.md`: corrected the write-time
  table (previous text claimed first/second writes during cycles 30..33 /
  44..47 with gates x>=30/x>=72 and stated P0 at x=16 was "far outside" those
  bands, which contradicts x>=30). The corrected, emulator-measured values
  are single=33 (gate 30), first=30 (gate 21), second=44 (gate 63), with the
  model's conservatism noted (P0 at x=16 renders correctly in Round 3 with
  cycle-33 single writes, below the model's x>=30 gate).

## Technical Reasoning

The second write's gate (63) is the widest exposure on the object set, and
the ball is the only object whose X can reach it. Giving ENABL the first
write reduces the ball's worst-case gate from 63 to 21 (first slot) or 30
(single), the smallest values the current kernel structure can produce. The
swap runs in VBLANK (InsertEvent), so the visible kernel is untouched and its
cycle budget is unchanged. The co-object that inherits the second slot is
P0 in the reported frames (P1 is fixed at x=136, above the second gate); its
edge shifts in those rare shared rows on the documented model, trading a
small, localized paddle artifact for the reported whole-ball shift. The
definitive fix (writes early enough for every X, including the leftmost
ball positions) requires restructuring the kernel's write slot, which is out
of scope for this round.

## Timing Impact

Before:
- Frame scanlines: 262
- VBLANK worst work: 4485 cycles, margin ~379
- Kernel worst path: 65/76 cycles, slack 11

After:
- Frame scanlines: exactly 262 (all test frames)
- VBLANK worst work: 4486 cycles (+1, the swap's extra branch on the merge
  path), margin ~378 (still well inside the T=77 expiry ~4864)
- Kernel worst path: 65/76 cycles, slack 11 (kernel untouched)

## Memory Impact

Before:
- ROM: 1296 bytes
- RAM: 51 bytes

After:
- ROM: 1552 bytes (+256: ~40 bytes of swap code plus ~216 bytes of required
  page-alignment padding - the event-building code now crosses the `$F500`
  boundary, so the `ALIGN 256` before the fine-adjust table pads a full page;
  the alignment is a deliberate timing requirement, see PosObject)
- RAM: 51 bytes (no change)

## Tests

Added: 5 tests (3 ROM write-slot, 2 model beam), 1 test updated
(`test_same_row_events_merge`), 1 added (`test_non_ball_merge_keeps_generation_order`).
Executed: `python tools/test.py` - 207 tests, all PASS. Quality gates
(ROM <= 4096, RAM <= 128) PASS. `python tools/benchmark.py` PASS (262
scanlines, kernel 65/76 slack 11, VBLANK margin 378). `python
tools/regression.py` PASS with one warning (ROM +256 B vs origin/main,
expected alignment padding). All new tests were verified to FAIL against the
pre-fix ROM (3 failures) before the fix was applied.

## Known Limitations

* Per the documented (conservative) beam model, the ball-alone single write
  still shifts for `ball_x < 30` and the first-write slot for `ball_x < 21`.
  The model is ~14 pixels conservative (Round 3's P0 at x=16 renders
  correctly under cycle-33 single writes), so the real residual band is
  likely much smaller; it cannot be narrowed in this environment because no
  pixel-level screenshot tooling is available (Stella snapshots do not fire
  headless and the debugger is GUI-only). Manual Stella verification steps
  are documented in the final report.
* The co-object inheriting the second slot is exposed for `x < 63` on the
  model; P0 (x=16) is the only fixed-X member below that gate, so rare
  shared rows shift a paddle edge instead of the ball.

## Next Logical Steps

* Pixel-verify the residual bands in the Stella debugger on a graphical
  session; if the real second-write gate is materially smaller than 63, the
  co-object residual may be unobservable.
* If the ball-alone left-wall band proves visible on hardware, restructure
  the kernel write slot (write earlier per scanline) rather than adding more
  builder heuristics.