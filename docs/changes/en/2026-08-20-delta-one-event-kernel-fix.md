# Change: Delta=1 event kernel fix (table-direct apply, Round 11)

## Objective

Fix the last remaining frame-stability bug on `round-5-basic-hp`: when two
events land on **consecutive** display rows (delta 1), the Round 10
two-phase pending kernel dropped the second event's OFF write, leaving the
object enabled past its bottom edge. The fix must make the visible kernel
input-independent for every valid event table (no data-dependent branching),
keep the frame at exactly 262 scanlines, and be validated against the real
ROM on the deterministic emulator. No new gameplay.

## Root cause

The Round 10 kernel was a deferred two-phase pipeline: it *decoded* the next
entry on an event line, staged the writes in `pendReg1/2` / `pendVal1/2`, and
only *applied* them on the following line. When the next event was on the
very next row (`delta = 1`), the decode on line N staged writes that were
then immediately overwritten by the decode on line N+1 - the first event's
writes never reached the TIA and its OFF (or ON) was silently dropped.

This was different from the Round 7 delta-0 bug (same-row double bump): the
table was strictly sorted with no delta-0 entries, yet a delta-1 pair still
lost one event's writes.

## Fix

The kernel now applies the table **directly on every scanline** instead of
staging writes:

* every entry is a uniform 5 bytes `[delta, reg1, val1, reg2, val2]`
  (`reg2 = 0` marks a single write);
* the apply block reads the last-decoded entry through `Y-5` and writes both
  registers unconditionally at the top of every line - before any countdown -
  so an event on the very next row (delta 1) applies its writes on its own
  first display line;
* the marker sentinel is the entry's delta byte (`$FF`, `EV_MARKER_VAL`),
  read after loading `evCnt`; the marker path ends the kernel at cycle 46;
* the first five table bytes are a dummy entry (both registers 0, AUDV0) so
  pre-first-event lines apply harmlessly; real entries start at offset 5.

Timing is now constant regardless of how many writes an entry holds or which
objects fired: non-event 38 cycles, event 54, marker 46, worst case 54/76
(slack 22).

## Added

* `tests/test_event_collision.py` - Round 11 rewrite: table-read/priming
  model for the direct-apply kernel, byte-for-byte ROM-vs-model comparison
  walks, five-way same-row collision stress, and the new
  `test_five_way_bottom_collision_drops_last_off` pinning the documented
  builder limitation (see Known Limitations).
* `tests/test_frame_timing.py` - re-validates frame stability: 80 stressed
  frames at 19912 cycles = 262 scanlines, and the delta-0/priming walk
  through the real event table.
* Dummy-entry and `EV_MARKER_ROW` back-scan coverage in `test_events.py`.

## Changed

* `src/main.asm` - `KernelLoop` rewritten as table-direct apply (no pending
  registers, no single/double dispatch); `BuildEvents`/`AppendEvent`/`ShiftBy5`/
  `ConvertDeltas` rewritten for uniform 5-byte entries (no `ShiftBy2`/
  `ShiftBy3`); VARS relayout (`evTbl` $90-$CB 60 bytes, `evRow` $CC,
  `tempCount` $CD, `tblLen` $CE, `nullDelta` $CF; `pendReg*`/`pendVal*`
  removed).
* `src/constants.inc` - `EV_TBL_SIZE` 31 -> 60, `ENTRY0` 5, marker constants,
  priming helpers.
* `tests/test_timing.py` - budgets 38/54/46; `LDX evTbl-4,Y` emits `0xB6`
  (LDX zp,Y, 4 cycles), added to the emulator walker's opcode table.
* `tools/emu6502.py` - `0xBE` (LDX abs,Y) added as harmless future-proofing;
  the kernel's `evTbl-4,Y` assembles to `0xB6` which was already handled.
* `tests/test_events.py`, `test_ball.py`, `test_memory.py`, `test_rom.py`,
  `test_collision.py`, `test_hp.py`, `test_regression.py` - updated for the
  uniform table, new symbols and the 80-byte RAM layout (stale-rewrite rule).
* `tools/regression.py` - `PROJECT_RAM_BUDGET` 64 -> 80 (justified by the
  table-direct fix; exceeds the old 79-byte "soft" target by exactly the
  1 byte needed to make `EV_TBL_SIZE` 60 land on an even boundary).
* `tools/benchmark.py` - removed the obsolete `two_write` parameter.
* Docs: `docs/en/timing.md`, `docs/pt-BR/timing.md` (kernel section rewritten
  for 38/54/46 and table-direct apply; `OVERSCAN_LOOP_COUNT` 7 -> 6),
  `docs/en/architecture.md`, `docs/pt-BR/arquitetura.md` (uniform entry
  format, slot rule, RAM map), `docs/en/memory-map.md`,
  `docs/pt-BR/mapa-de-memoria.md` (80 bytes, current symbol addresses),
  `docs/en/benchmarks.md`, `docs/pt-BR/benchmarks.md` (Round 11 state),
  `docs/en/event-kernel-timing-analysis.md`,
  `docs/pt-BR/analise-timing-kernel-eventos.md` (resolution section).
* `docs/benchmarks/latest.md` / `history.csv` - refreshed by
  `tools/benchmark.py`.

## Technical Reasoning

The old pending pipeline made the apply **conditional on the previous line's
decode**, which is exactly what a delta-1 pair breaks: the second decode
destroys the first's staged writes before they apply. Applying unconditionally
at line start removes the dependency between the apply and the countdown, so
no two consecutive entries can interfere. The uniform 5-byte entry is the
price: every event (single or merged double) costs 5 bytes, the table grows
to 60 bytes (`dummy 5 + 10 entries + marker 5`), and the countdown priming
needs a `nullDelta` byte for the common case where the first event is not on
line 0. In exchange the kernel has zero data-dependent branches, so the
263-scanline class of bug is structurally unreachable.

DASM detail: `LDX evTbl-4,Y` assembles to **0xB6** (LDX zero-page,Y, 4
cycles), not 0xBE (LDX abs,Y) - the effective address is `($8C+Y)&$FF` and Y
never exceeds 55 (max table offset $C3), so the zero-page indexing never
wraps. The emulator already handled 0xB6; 0xBE was added only for
defensive completeness.

## Timing Impact

Before (Round 10):
- Frame scanlines: 262 normally, but 263 for delta-1 pairs (the bug)
- Kernel worst path: 65/76 cycles, slack 11 (variable-size pending decode)
- VBLANK work: 4486 cycles, margin ~378

After (Round 11):
- Frame scanlines: exactly 262 for every input (80 stressed frames, all
  19912 cycles)
- Kernel worst path: 54/76 cycles, slack 22 (constant for all inputs)
- Kernel best path: 38 cycles (non-event)
- Marker line: 46 cycles
- VBLANK work: 4528 cycles, margin 336 (still well inside T=77 expiry ~4864)
- Overscan: 6 WSYNC writes, 10 lines (kernel end moved from K+174 to K+236)

## Memory Impact

Before:
- ROM: 1552 bytes
- RAM: 51 bytes

After:
- ROM: 1808 bytes (+256; offset-aware builder + slot-ordering rules; ROM is
  only 44% of the 4096 limit)
- RAM: 80 bytes (+29; the uniform 60-byte table is the price of the
  input-independent kernel; 48 bytes remain)

## Tests

Executed: `python tools/test.py` - **211 tests, all PASS** (discovered with
`python3 -m unittest discover -s tests`). Quality gates: ROM 1808 <= 4096,
RAM 80 <= 128, frame 262 scanlines, kernel 54 <= 76. `python
tools/benchmark.py` PASS (latest.md + history.csv refreshed).
`python tools/regression.py` PASS with 2 soft warnings (ROM +512 B, RAM
+31 B vs the origin/main Round 8 baseline; both expected, documented above).
Stella validation: `stella -rominfo` exits 0 (Cart MD5
7e8d44bb9494f1c0ff254aa05d7ac67d, 4K NTSC); an xvfb-run smoke run exits 0.
Stella 6.7.1 has no headless `-frames` option, so per-frame stability is
validated by the deterministic emulator in `test_frame_timing.py`.
Repro scenes verified on the emulator: p0=88,p1=50,by=51 -> GRP1 renders rows
50-62 (was invisible before the fix); p0=88,p1=50,by=96,m0y=96,m1y=100,
m0act=True -> ENABL/ENAM0 OFF applies at row 100 (was stuck ON).

## Known Limitations

* **Five-way same-row bottom collision** (pinned by
  `test_five_way_bottom_collision_drops_last_off`): with p0=p1=171, by=179,
  m0y=m1y=183 all active, the builder's bump chain (183 -> 184 -> 185) drops
  P1's OFF, leaving GRP1 enabled through line 184. The overscan init clears
  it at line 185+, so the artifact is at most one scanline at the very bottom
  of the screen, outside the arena. Both the ROM and the Python model agree
  on the emitted table; fixing it would require rejecting the 5th event (out
  of scope).
* The dummy entry makes the pre-first-event apply write AUDV0 every line;
  harmless with the screen enabled.
* RAM is now 80 bytes (up from 79 in the analysis prediction); 48 bytes
  remain, still adequate for the current scope.
* The analysis documents' originally projected kernel numbers (62/58 rest)
  assumed a fall-through instead of the JMP; the implemented 54/46 path is
  slightly larger but structurally identical.

## Next Logical Steps

* If the one-line bottom-collision artifact proves visible, reject the 5th
  same-row event in `AppendEvent` instead of bumping past the last safe row.
* Re-examine the 80-byte RAM budget against future gameplay; each additional
  object costs up to 10 table bytes.
* Re-validate the write-slot guarantee on real hardware once a pixel-level
  capture path is available.