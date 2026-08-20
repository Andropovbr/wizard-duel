# Change: Ball x Player minimal rebound (Round 7)

## Objective

Give the Round 6 ball x player contact record a gameplay *response* on branch
`round-6-ball-player-collision`: when the TIA latches a Ball x P0 overlap, the
ball must be steered right; on Ball x P1, steered left; `ball_dy` unchanged;
no damage, no HP, no missile change, no ball removal, no debounce, no
power-ups. The response must be a fixed-cost, branchless pass in overscan so
the 262-scanline frame is unchanged, validated against the real ROM on the
deterministic emulator, and the repeated-contact "pianinho" behaviour must be
observed and documented rather than silently fixed.

## Added

* `src/main.asm` - `ApplyBallRebound` (JSR'd from `OverscanWait` immediately
  after `ProcessCollisions`, before `ProcessHitEffects`): reads
  `ball_contact_flags`, derives a table index
  `(old_dx_slot * 4) | contact_flags` with a single `ROL`, looks up the new
  `ball_dx` in `reboundTbl`. Branchless body: 27 cycles including `RTS`
  (JSR 6 + body 27 + RTS 6 = 39 fixed cycles added to the overscan epilogue).
  Ball x P0 -> `DIR_RIGHT` ($01), Ball x P1 -> `DIR_LEFT` ($FF), both
  players -> `DIR_LEFT` (P1 precedence), no contact -> `ball_dx` unchanged.
  VARS row updated in the RAM comment.
* `src/main.asm` - `reboundTbl`: 16-byte-aligned 8-entry table at `$F2D0`.
  Index layout (slots in source order: dx slot 0 = `DIR_LEFT`, slot 1 =
  `DIR_RIGHT`; flag bit 0 = `CONTACT_P0`, bit 1 = `CONTACT_P1`):
  `[no-op] [->RIGHT] [->LEFT] [->LEFT]` for the left-moving slot, and
  `[no-op] [no-op] [->LEFT] [->LEFT]` for the right-moving slot. The
  ball-into-paddle face (dx R + P0, dx L + P1) is the one meaningful rebound;
  the wrong-side cases (dx L + P0, dx R + P1) are deliberately no-ops so a
  ball that tunneled in from the rear keeps its direction instead of being
  re-steered into the paddle every frame (see Known Limitations).
* `src/constants.inc` - `OVERSCAN_LOOP_COUNT = 5` (was 6) with a Round 7
  comment block explaining why the loop count dropped (see Technical
  Reasoning).
* `tests/test_ball_rebound.py` - the Round 7 acceptance suite (17 tests):
  per-player steer for both incoming directions, `ball_dy` untouched,
  no-contact unchanged, both-players contact -> `DIR_LEFT`, no side effects on
  HP / `hit_flags` / missiles / ball removal, consecutive-contact coherence
  (contact streak re-steers the same direction every frame), clean exit after
  contact, missile-hit + ball-contact in the same frame, and a 100-frame
  max-stress run asserting 19912 cycles / 262 scanlines every frame.
* `tools/common.py` - `probe_stella` hardened so the Windows 11 / Stella 7.0
  check works: explicit utf-8/replace decoding, a Windows-only retry that
  redirects stderr to a temp file via `cmd.exe /c`, and a final fallback that
  accepts a PE executable (`MZ` magic) with exit 0 when console capture is
  empty (Stella on Windows is a GUI-subsystem app; `-help` goes to the console
  via WriteConsole, which does not appear on the pipe).

## Changed

* `src/main.asm` - `OverscanWait` epilogue comment: the first overscan `WSYNC`
  now lands at region cycle 380 (was 304) after the `ApplyBallRebound` JSR;
  loop count 5; landing window ~K+306..K+326 stays inside the
  `(K+304, K+380]` slot on every path.
* `src/main.asm` - header Round 7 bullet; `ProcessHitEffects` comment updated
  (B in [60,80] emulator / [62,80] real hardware, margins >= 20 cycles).
* Docs (EN + PT-BR): `docs/en/timing.md` / `docs/pt-BR/timing.md` (overscan
  loop count 6 -> 5, first `WSYNC` landing 304 -> 380, the 39-cycle rebound
  explanation in both overscan passages), `docs/en/memory-map.md` /
  `docs/pt-BR/mapa-de-memoria.md` (`ApplyBallRebound` at `$F2B0`,
  `reboundTbl` at `$F2D0`), `docs/en/architecture.md` /
  `docs/pt-BR/arquitetura.md` (ball no longer "does not interact with
  players": contact + horizontal steer now documented), and
  `docs/benchmarks/latest.md` / `history.csv` (overscan loop 6 -> 5).
* `tools/benchmark.py`-generated files refreshed by `python tools/benchmark.py`.

## Removed

* The 8 cycles of `ALIGN 16` slack between `newActiveTbl` (`$F2A0`) and
  `ProcessHitEffects` (`$F300`) - absorbed by the new `ApplyBallRebound`
  routine and `reboundTbl`. Nothing was deleted: the gap was unused padding.

## Technical Reasoning

**Why branchless + table-driven**: the overscan region is WSYNC-counted, not
timer-based (a variable-cost `ProcessHitEffects` runs between the kernel and
the wait). Every cycle added before the first overscan `WSYNC` shifts its
landing boundary. A branchy rebound (BNE/BPL) would vary the cost on the
contact path and break the fixed landing. Indexing a table with
`(old_dx_slot * 4) | contact_flags` turns the whole decision into one
ROL + LDA: deterministic, 27 cycles, no branches.

**Why OVERSCAN_LOOP_COUNT 6 -> 5**: Round 6 measured the first overscan
`WSYNC` at region cycle 304 (overscan scanline 4). Round 7's fixed 39 cycles
pushed it out of the `(K+228, K+304]` write slot; measured post-stall landing
is now region cycle 380 = overscan scanline 5. Dropping the loop from 6 to 5
countdown WSYNCs re-anchors the sequence so the region still sums to exactly
10 lines and the `JMP` + VSYNC preamble still aligns the next frame's first
VSYNC `WSYNC` to 760 cycles after the kernel's last line. Frame stays exactly
19912 cycles = 262 scanlines, verified over 100 max-stress frames and
cross-checked with dedicated overscan-landing instrumentation.

**ROM high-water unchanged (1808)**: the ~39 bytes of new code plus alignment
fitted into the previously-empty `$FF` gap between `newActiveTbl` and
`ProcessHitEffects`; no symbol moved and the ROM top did not grow.

**RAM unchanged (81)**: the rebound consumes the existing
`ball_contact_flags` byte; `reboundTbl` lives in ROM. No new variable.

**The "pianinho" observation (documented, not fixed)**: at 1 px/frame the ball
takes 2-5 consecutive frames to exit a paddle overlap, and each of those frames
latches the contact again. Because the rebound is not velocity-bouncing (no
reflect), the first contact frame sets the exit direction and every later frame
re-applies the same direction - so the paddle emits a short self-limiting
tick-tick-tick burst, never an infinite oscillation and never a reverse flip.
Deterministic emulator runs captured exact frame sequences, e.g. a rightward
hit on the P1 left face: contact frames 5-7 (bx 136, 135, 134; dx -> L after
frame 5), no contact from frame 8 -> a 3-tap burst; a shallow graze produced 5
consecutive contact frames. Stella headless launch under xvfb ran the ROM
stably for 10 s; the ROM is recognized as 4K NTSC. Per the project's directive
the pianinho is left as-is and recorded here for future rounds.

## Timing Impact

Before:
- Frame scanlines: 262 / 19912 cycles (Round 6)
- Overscan loop count: 6
- First overscan `WSYNC` boundary: region cycle 304 = overscan scanline 4

After:
- Frame scanlines: exactly 262 / 19912 cycles for every collision state
  (measured over 100 consecutive max-stress frames)
- Overscan loop count: 5
- First overscan `WSYNC` boundary: region cycle 380 = overscan scanline 5
  (all five measured states)
- Overscan epilogue added cost: 39 fixed cycles (JSR 6 + body 27 + RTS 6)
- Kernel worst case: unchanged 54/76 (kernel untouched this round)
- VBLANK: unchanged (timer 77, work 4528, margin 336)

## Memory Impact

Before:
- ROM: 1808 bytes
- RAM: 81 bytes ($80-$D0)

After:
- ROM: 1808 bytes (unchanged - padding gap absorbed the growth)
- RAM: 81 bytes (unchanged - no new variable)

## Tests

Executed: `python tools/test.py` - **250 tests, all PASS** (was 233).
Added: `tests/test_ball_rebound.py` (17 tests):

* Ball x P0 -> `ball_dx = DIR_RIGHT`; Ball x P1 -> `ball_dx = DIR_LEFT`,
  for both incoming directions.
* `ball_dy` untouched by any rebound.
* No contact -> `ball_dx` unchanged.
* Simultaneous P0 + P1 contact -> `DIR_LEFT` (P1 precedence).
* No side effects: HP, `hit_flags`, missile state and `m_active` unchanged;
  the ball is never removed.
* Consecutive-contact coherence: a 4-frame contact streak re-steers the same
  direction every frame (the pianinho burst), then a clean exit once the ball
  leaves the overlap.
* Missile hit + ball contact in the same frame: `ProcessHitEffects` and
  `ApplyBallRebound` both apply, independently.
* 100-frame max-stress: every frame = 19912 cycles (262 scanlines) with both
  missile + both ball latches asserted.

Quality gates: ROM 1808 <= 4096, RAM 81 <= 128, frame 262 scanlines, kernel
54 <= 76. `python tools/benchmark.py` PASS (latest.md + history.csv refreshed,
overscan loop 6 -> 5). `python tools/regression.py` PASS vs origin/main.
Stella validation: `stella -rominfo` loads the ROM as 4K NTSC; 10 s headless
launch under xvfb stable (exit 124 = killed by timeout, i.e. ran without
crashing). Per-frame stability is validated by the deterministic emulator.

## Known Limitations

* No velocity bounce: the rebound is a horizontal *steer* (`ball_dx` set to
  LEFT/RIGHT), not a reflect. A ball entering a paddle from the rear (wrong
  side) is a deliberate no-op and keeps its direction, so it passes through.
* The pianinho (2-5 consecutive contact frames on the same paddle as the ball
  exits the overlap) is intentionally not debounced; it is harmless, self-
  limiting and now documented with exact frame sequences.
* No damage on ball contact yet - this round only steers the ball.
* RAM 81 of 128; each new gameplay byte moves closer to the 128-byte hardware
  limit and the 81-byte CI gate.

## Next Logical Steps

* Decide whether ball contact should also deal damage (reusing the
  `hit_flags`/`ProcessHitEffects` pattern) or whether the steer alone defines
  the Round 8 behaviour.
* If a wrong-side pass-through matters, detect the incoming direction before
  applying the rebound (spatial or directional contact data).
* Re-run the max-stress timing suite and regression comparison after commit so
  the origin/main baseline uses the real Round 7 metrics (ROM 1808 / RAM 81).