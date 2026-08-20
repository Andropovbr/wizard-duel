# Change: Event-table same-row bump fix (vertical stretch)

## Objective

Fix a serious visual bug reported on `round-5-basic-hp`: with both players
alive, when a missile visually crossed the Ball, Player(s), Ball and/or
Missile were vertically stretched to the bottom edge of the screen, as if a
render register had been enabled and its OFF event never happened. Fix on
the current branch only (no new branch, no merge to main), with no new
gameplay: the Ball must not logically interact with missiles; a visual
overlap is simply ignored.

## Symptom

* Both players alive and visible, one missile active; when the missile
  visually crossed/hit the Ball, Player(s), Ball and/or Missile became
  vertically stretched to the bottom edge of the screen.
* With only one player alive/visible the problem did not appear in the
  reported scenario.

## Reproduction

Reproduced deterministically on the real ROM (emulator driving `BuildEvents`
directly). With `P0Y=88, P1Y=50, ball_y=96, m0_y=96, m1_y=100` (M1 inactive),
the OFF rows coincide: P0 OFF, Ball OFF and M0 OFF all fall on row 100. The
event builder produced a table with a **delta-0** entry at row 100 (M0 OFF),
so the missile stayed enabled from row 96 to the bottom of the screen.

Investigation also confirmed the one-dead-player variant reproduces the same
root cause (`hp1=0` still yields a delta-0 M0 OFF), so the real invariant is
*any three events coinciding on a row where the first two already merged into
a double*, not strictly "both players alive". The realistic in-game trigger
is both players alive at the same row, both missiles flying, and the ball
crossing the missile rows.

## Root cause

`InsertEvent` merges two same-row events into a double entry (5 bytes, two
writes) so no scanline ever needs more than two writes. A third event on a
row that already holds a double is bumped to row+1 (`INC evRow`) and the scan
continues. The bug was in `.insertSingle` (src/main.asm): when the scan
finished (terminator reached, or a later entry with a bigger row), it stored
the **original stacked row** from the stack instead of the effective
(possibly bumped) `evRow`. Two table entries therefore landed on the same
absolute row. `ConvertDeltas` computed `delta = row - prevRow = 0` for the
second one, and in the kernel `DEC evCnt` wrapped `0 -> $FF`, so that entry
could never fire: the OFF event was lost and the register stayed enabled to
the kernel end (overscan init clears it, but the object was drawn all the way
to the bottom edge).

The Python model in `tests/test_events.py` was correct (it uses the bumped
row), which is why the model tests passed while the real ROM was broken.

## Fix

`.insertSingle` now pops and discards the original stacked row and stores
`evRow` (the effective, possibly bumped row) in the table. The non-bump path
is unaffected (`evRow` equals the stacked row there); the merge path was
already correct. The table stays strictly sorted, so no delta-0 entry can
exist in any valid state.

Rejected alternative: updating the stacked row in place on every bump via
stack-pointer tricks. More complex and slower for no benefit, since only
`.insertSingle` consumes the stacked row.

## Added

* `tests/test_event_collision.py` (18 tests):
  * reproduce-first tests for the exact reported combinations (both-alive
    and one-dead), asserting a valid, strictly-increasing table;
  * semantic validation of `evTbl` after `BuildEvents` on the real ROM: no
    delta-0, strictly increasing entry rows, per-register ON-then-OFF
    alternation with correct enable values, valid single terminator, and
    decoded deltas mapping back to the same absolute rows as the validated
    Python model;
  * stretched-object tests that run the actual kernel to KERNEL_SCANLINES
    while tracking GRP0/GRP1/ENABL/ENAM0/ENAM1 and assert each register
    turns off exactly at its OFF event row;
  * the six required scenarios (P0+P1+Ball; +M0; +M1; +M0+M1; P0 dead;
    P1 dead) at colliding rows;
  * boundary rows near 0, 1, KERNEL_SCANLINES-2 and KERNEL_SCANLINES-1.
* `tests/test_frame_timing.py`:
  * `run_frame(inject_at=..., inject_fn=...)` so tests can force game state
    exactly when the CPU reaches BuildEvents (after VBLANK movement);
  * `test_no_stretched_objects_when_missiles_cross_ball`: 60 real frames
    with the 3-way collision state injected at BuildEvents each frame, all
    exactly 19912 cycles = 262 scanlines and with a delta-0-free table.

## Changed

* `src/main.asm`, `.insertSingle`: store the effective `evRow` instead of the
  original stacked row (+2 emitted bytes, absorbed by the ALIGN padding).
* `docs/en/architecture.md`, `docs/en/timing.md`, `docs/pt-BR/arquitetura.md`,
  `docs/pt-BR/timing.md`: Round 7 sections documenting the same-row collision
  policy, the root cause and the fix.

## Technical Reasoning

The bump policy is deliberate: a table entry never holds three writes, which
would break the 76-cycle kernel budget. The bug was that the bump advanced
`evRow` for the *scan* but the *insert* used the stale stacked row. Storing
`evRow` restores the intended invariant (strictly increasing entry rows =>
positive deltas => every event fires exactly once). This runs in VBLANK, so
the visible kernel is untouched and its timing is unchanged.

## Timing Impact

Before:
- Frame scanlines: 262 (stretched objects were a visual artifact, not a
  frame-length bug)
- VBLANK worst work: 4455 cycles
- VBLANK margin: 409 cycles
- Kernel worst path: 65/76 cycles, slack 11

After:
- Frame scanlines: exactly 262, all 60 runtime frames
- VBLANK worst work: 4485 cycles (+30, one extra zero-page `LDA evRow` per
  `insertSingle` along the worst path)
- VBLANK margin: 379 cycles (still well inside the T=77 expiry ~4864)
- Kernel worst path: 65/76 cycles, slack 11 (kernel untouched)

## Memory Impact

Before:
- ROM: 1296 bytes
- RAM: 51 bytes

After:
- ROM: 1296 bytes (the +2 emitted bytes land before the `ALIGN 256` page
  boundary that precedes `fineAdjustBegin`, so the reported high-water mark
  is unchanged)
- RAM: 51 bytes (no change)

## Tests

Added: `tests/test_event_collision.py` (18 tests), plus
`test_no_stretched_objects_when_missiles_cross_ball` in
`tests/test_frame_timing.py`.
Executed: `python tools/test.py` - 201 tests, all PASS. Quality gates
(ROM <= 4096, RAM <= 128) PASS. `python tools/benchmark.py` and
`python tools/regression.py` PASS (ROM unchanged vs baseline, RAM +2,
kernel slack unchanged). Both new tests were verified to FAIL against the
pre-fix ROM (regression coverage confirmed).

## Known Limitations

The exact pixel rendering is validated in Stella on a local graphical
session; the deterministic suite validates the event table semantics and the
kernel register writes instead. In this session Stella launched the ROM
headless with exit code 0 and rendered continuously under Xvfb (sustained
frame output, no crash); pixel-level screenshots were not captured because no
snapshot/screenshot tool is available in the CI environment. The one-dead
variant can still produce the same root cause in principle (any three events
on a row), but it is much rarer in practice since a dead player contributes
no events.

## Next Logical Steps

Consider a brute-force search over all valid object positions asserting no
delta-0 table (the current sweep covers a targeted grid). Keep the
delta-0 regression tests alive as new gameplay is added so a future event
generator cannot silently reintroduce the invariant violation.