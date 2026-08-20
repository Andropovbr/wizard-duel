# Change: Ball x Player collision contact record (Round 6)

## Objective

Add ball x player collision detection on branch `round-6-ball-player-collision`
(on top of Round 11, the table-direct kernel fix). When the TIA latches a
Ball x P0 or Ball x P1 overlap during the visible kernel, the overscan
collision pass must record it in a game-readable byte so a later round can
decide what ball contact *does*. This round only *reports* the contact: it
must not damage, stop the ball, change missiles, or alter any gameplay state.
The pass must stay fixed-cost and branchless so the 262-scanline frame is
unchanged, and the feature must be validated against the real ROM on the
deterministic emulator.

## Hardware: the TIA collision latches

Two registers report ball overlaps (verified against the Stella source, the
reference emulator):

| Register | Read address | Bit | Meaning |
| -------- | ------------ | --- | ------- |
| `CXP0FB` | `$02` | D6 (`%01000000`) | P0 x Ball |
| `CXP1FB` | `$03` | D6 (`%01000000`) | P1 x Ball |
| both     |             | D7 | P x Playfield (ignored) |

`CXCLR` (`$2C`, write) clears every collision latch. Latches are set by the
beam during the visible kernel and persist until the ROM clears them, so the
overscan read-then-clear contract is: read both registers, then write
`CXCLR`. The D7 player x playfield bits are deliberately ignored because the
playfield is never displayed (there is no background playfield in this game).

## Collision lifecycle

`ball_contact_flags` is a **per-frame report**, exactly like `hit_flags`:

* frame N renders the overlap -> the TIA latches the bit during the kernel;
* the overscan of frame N runs `ProcessCollisions`, which packs the latches
  into `ball_contact_flags` and writes `CXCLR`;
* so a contact rendered in frame N is readable from the start of frame N+1
  and never repeats (the byte is rewritten to zero the next overscan).

There is **no debounce** this round: an overlap that lasts K consecutive
frames is reported in all K frames (measured, see Tests). The flag is
information only - no velocity rebound, no damage, no missile change, no
state transition is attached to it.

## Added

* `src/constants.inc` - `CXP0FB = $02`, `CXP1FB = $03`,
  `BALL_HIT_P0 = %01000000` / `BALL_HIT_P1 = %01000000` (the D6 latch bits),
  `CONTACT_P0 = %00000001` / `CONTACT_P1 = %00000010` (the flags byte's bits),
  and an updated TIA collision register comment block.
* `src/main.asm` - the Round 6 header bullet and the ball contact block inside
  `ProcessCollisions`, placed **before** the `STA CXCLR`:
  read `CXP0FB`, extract D6 with a double-`ASL` carry trick, accumulate into
  `ball_contact_flags`; repeat for `CXP1FB` (shifted left one bit so it packs
  as bit 1). Fixed cost: 33 cycles (14 + 19). `ProcessCollisions` total is now
  117 cycles (was 84), still branchless. VARS: `ball_contact_flags DS 1` at
  `$8E`; the RAM comment now reports 81 bytes ($80-$D0).
* `tests/test_ball_contact.py` - the Round 6 acceptance suite (see Tests):
  per-player contact, no-contact/stale-clear, playfield-bit rejection,
  simultaneous contact, contact + missile hit in the same frame,
  dead-player no-contact (the rendering gate), latch lifecycle / CXCLR
  ordering / contact streaks, and a 500-frame max-stress frame-timing run.
* `tests/test_collision.py` - `CollisionHarness.set_collisions` extended with
  `ball_p0`/`ball_p1` (injects `cpu.cxp0fb`/`cpu.cxp1fb`), `state()` now
  includes `ball_contact_flags` and the two latches, constants
  `BALLP_P0 = 0x40` / `BALLP_P1 = 0x40`, and the latch table documented in the
  module docstring.
* `tools/emu6502.py` - the emulator now models `CXP0FB`/`CXP1FB` as
  read-returning latches that persist until the ROM writes `CXCLR` (which
  clears all four collision latches), mirroring the real TIA contract.

## Changed

* `tests/test_memory.py` and `tests/test_ball.py` - RAM assertions updated
  80 -> 81 and their comments explain the +1 byte is `ball_contact_flags`.
* `tools/regression.py` - `PROJECT_RAM_BUDGET` 80 -> 81, with the rationale
  documented at the constant (see Technical Reasoning for the alternatives
  that were investigated and rejected).
* Docs (EN + PT-BR): `docs/en/memory-map.md` / `docs/pt-BR/mapa-de-memoria.md`
  (81-byte layout, `ball_contact_flags` row, corrected `newActiveTbl` address
  `$F290` -> `$F2A0`, updated ROM/RAM prose), `docs/en/timing.md` /
  `docs/pt-BR/timing.md` (overscan passages now measured: first overscan
  `WSYNC` lands at region cycle 304 for every collision state; 500-frame
  max-stress re-validation; runtime validation status), `docs/en/architecture.md`
  / `docs/pt-BR/arquitetura.md` (collision + ball contact section, 117-cycle
  pass, RAM map), `docs/en/benchmarks.md` / `docs/pt-BR/benchmarks.md`
  (81-byte RAM budget thresholds, Round 6 metric block), and
  `docs/benchmarks/latest.md` / `history.csv` (RAM 81, ROM 1808).

## Technical Reasoning

**Why a separate byte** instead of reusing spare bits? Every candidate was
investigated and rejected:

* `fire_prev` and `m_active` spare bits: both are rewritten every frame
  (`UpdateMissiles` in VBLANK, `m_active` via `newActiveTbl` in the
  collision pass), so a contact stored there would be clobbered before it
  could be read;
* `hit_flags`: mixing ball contact into the missile-hit byte would make the
  two collision *classes* indistinguishable to game logic, and the Round 5
  HP/death logic reads `hit_flags` directly;
* packing `p0_hp`/`p1_hp`: a 2-bit-per-player HP field refactor of tested
  Round 5 logic to save one byte - rejected as an unjustified risk;
* aliasing `nullDelta` with `evRow`: `ConvertDeltas` writes `nullDelta` and
  then uses `evRow` in the same loop, so their lifetimes overlap.

A new byte is the correct cost: **RAM 81 of 128** (47 free). `PROJECT_RAM_BUDGET`
moved 80 -> 81 so CI still gates on a real limit rather than the stale one.

**Why the branchless double-ASL**: extracting D6 (`%01000000`) into bit 0
with two `ASL`s moves the carry into the accumulator through `ADC #0`, and
the whole per-latch sequence (`LDA $02 / ASL / ASL / LDA #0 / ADC #0`) is a
fixed 14 cycles; the CXP1FB sequence (`... / ASL / ORA`) is 19. No `BPL`/`BMI`
branch means no timing variation, so the fixed-cost property of
`ProcessCollisions` is preserved and the WSYNC-counted overscan stays exact.

**Why no HP gate in `ProcessCollisions`**: a dead player is not rendered
(`BuildEvents` skips its GRP events), so the TIA never latches a ball x
dead-player overlap. The rendering gate already prevents dead-player contacts
without a byte-costly HP check in the collision pass.

**ROM unchanged (1808 bytes)**: the 24 bytes of added code were absorbed by
existing `ALIGN` slack before `newActiveTbl` and `ProcessHitEffects`, so the
high-water mark did not move. `ProcessHitEffects` stayed at `$F300`.

## Timing Impact

Before:
- Frame scanlines: 262 (Round 11, table-direct kernel)
- `ProcessCollisions`: 84 cycles
- First overscan `WSYNC` boundary: region cycle 304 (measured, all paths)

After:
- Frame scanlines: exactly 262 / 19912 cycles for every collision state
  (measured over 500 consecutive max-stress frames with both missile latches
  AND both ball latches asserted every frame)
- `ProcessCollisions`: 117 cycles (+33, fixed-cost branchless ball contact)
- First overscan `WSYNC` boundary: still region cycle 304 for all five
  measured states (no collision, both missile hits, both ball contacts, all
  collisions, both players dead) - the overscan region remains exactly 10
  lines
- Kernel worst case: unchanged 54/76 (kernel untouched this round)
- VBLANK: unchanged (timer 77, work 4528, margin 336)

## Memory Impact

Before:
- ROM: 1808 bytes
- RAM: 80 bytes ($80-$CF, 48 free)

After:
- ROM: 1808 bytes (unchanged - ALIGN slack absorbed the growth)
- RAM: 81 bytes ($80-$D0, 47 free; +1 = `ball_contact_flags`)

## Tests

Executed: `python tools/test.py` - **233 tests, all PASS** (was 211).
Added: `tests/test_ball_contact.py` (22 tests):

* Ball x P0 -> `CONTACT_P0`; Ball x P1 -> `CONTACT_P1`; never cross-set.
* No contact -> 0; a stale 0xFF byte is deterministically reset; the
  P x Playfield D7 bits are ignored (never masquerade as contact).
* Simultaneous Ball x P0 + Ball x P1 -> both bits.
* Ball contact + M0 x P1 hit in the same frame: `hit_flags` and
  `ball_contact_flags` are independent, the scoring missile still
  deactivates, and a contact never deactivates a missile.
* Dead player: not rendered (no GRP0 events) and never produces contact.
* Latch lifecycle: contact recorded once, cleared next frame; `CXCLR`
  clears `CXP0FB`/`CXP1FB`; latches persist until the ROM clears them;
  a contact streak (4 frames) tracks the injected geometry exactly, and the
  measured max streak equals the injected run length.
* 500-frame max-stress: every frame = 19912 cycles (262 scanlines) with both
  missile + both ball latches asserted, alternating fire, HP kept topped up.

Quality gates: ROM 1808 <= 4096, RAM 81 <= 128, frame 262 scanlines, kernel
54 <= 76. `python tools/benchmark.py` PASS (latest.md + history.csv
refreshed). `python tools/regression.py` PASS (2 soft warnings vs the stale
Round 1 persisted baseline; the origin/main comparison after commit will be
RAM +1 with no hard failure). Stella validation: `stella -rominfo` loads the
ROM as 4K NTSC (MD5 `1dc4839d390acba1d7677b65dd07a243`); Stella 6.7.1 has no
headless `-frames` option, so per-frame stability is validated by the
deterministic emulator (`test_ball_contact.py` 500-frame run).

## Known Limitations

* `ball_contact_flags` is a per-frame *report*: no debounce, no edge
  detection, no gameplay effect yet. A later round decides what contact does
  (damage, ball rebound, etc.) by reading the flag.
* The contact record is global (one bit per player) - it does not carry any
  spatial information (where the ball hit, angle). Spatial data would need
  the ball position read the same frame.
* RAM is 81 bytes; 47 remain. Each new gameplay byte moves closer to the 128
  hardware limit and to the 81-byte CI gate.

## Next Logical Steps

* Decide what ball contact *does* in game terms (damage is the obvious first
  candidate, reusing the `hit_flags`/`ProcessHitEffects` pattern).
* If contact needs spatial data, investigate reading the ball position at
  contact time (VBLANK capture of the flagged frame) instead of per-frame.
* Re-run the max-stress timing suite and regression comparison after
  committing, so the origin/main baseline comparison uses the real Round 11
  metrics (ROM 1808 / RAM 80) rather than the stale Round 1 baseline.