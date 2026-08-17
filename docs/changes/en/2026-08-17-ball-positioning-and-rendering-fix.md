# Change: Ball rendering completion and horizontal positioning fix

## Objective

Complete the Round 2 ball so it is a proper 4x4 square and, crucially, make
it render at exactly its requested horizontal position (`ball_x`) moving
continuously 1 pixel per frame. The prior committed state only used the
coarse 15-pixel positioning: the fine adjustment (`HMP0/HMP1/HMBL` + `HMOVE`)
was being written but never took effect, so the rendered ball jumped in
15-pixel steps every 15 frames instead of gliding 1 pixel per frame.

## Root cause

Two independent defects were found and fixed.

### 1. `HMOVE` did not immediately follow a `WSYNC`

The Stella Programmer's Guide requires:

> The `HMOVE` command must immediately follow a `WSYNC` (Wait for SYNC) to
> insure the HMOVE operation occurs during horizontal blanking.

The code wrote `HMOVE` right after the `LDA INTIM / BNE` VBLANK polling loop
exited, i.e. in the middle of the last VBLANK scanline, not after a `WSYNC`.
Measured behavior: the fine offsets were never applied. With the ball frozen
at every `ball_x` 0..16, `ball_x` 0..13 rendered at 2 color clocks and
`ball_x` 14..16 at 14; the paddles rendered at the raw coarse grid
(`PLAYER1_X` 15..29 all rendered at position 15). The 1 px/frame
"verification" from the earlier round was based on sparse 0.09 s sampling and
missed the 15-pixel jumps.

Fix: `STA WSYNC` is now executed right before `STA HMOVE` so the movement
acts during the horizontal blanking of the last VBLANK line (line 40).
`VBLANK_TIMER_VALUE` went from 44 to 43 so the polling loop expires one line
earlier (line 39) and the extra `WSYNC` still lands the kernel on line 41,
keeping the frame at exactly 262 scanlines.

### 2. The routine renders at `P - 7` (q >= 1) / `P - 4` (q = 0)

Once fine movement worked, the absolute position was still off: the shared
PosObject routine renders a player at

    15*q + (s - 7)    for q >= 1
    3 + (s - 7)       for q = 0

where the divide loop runs `q + 1` subtractions and `s = P mod 15` indexes
the page-aligned fine-adjust table (values +7..-7). The q = 0 base is 3
instead of 0 because the shortest divide path strokes `RESP` before TIA
cycle 23 (a hardware quirk). The ball additionally renders 1 pixel left of a
player for the same input.

The compensation previously used (`ball_x + 1`) could not cancel an offset
that is different for q = 0 and q >= 1. `PositionBall` now passes
`ball_x + 8` (or `ball_x + 5` when the sum is below 15) and
`PositionPlayers` passes `X + 7` (or `X + 4`), which cancels both offsets and
the ball's 1-pixel-left shift for every valid position.

## Added / Changed

- `WaitVBlank`: `STA WSYNC` before `STA HMOVE` on the last VBLANK line.
- `VBLANK_TIMER_VALUE = 43` (was 44) in `src/constants.inc`.
- `PositionBall`: compensation `ball_x + 8` / `ball_x + 5` (branch in
  VBLANK; `PosObject` re-syncs with its own `WSYNC`, so the branch timing is
  irrelevant).
- `PositionPlayers`: compensation `X + 7` / `X + 4` for both players.
- 4x4 square ball completion: `BALL_HEIGHT = 4`, `BALL_SIZE_CTRLPF =
  %00100000` (4 color clocks; the committed value `%00010000` was 2),
  `BALL_Y_MAX = KERNEL_SCANLINES - BALL_HEIGHT - 1`, and the kernel ball
  block rewritten from `CMP ball_y / BNE` to
  `SEC / SBC ball_y / CMP #BALL_HEIGHT / BCS` so `ENABL` is written on
  `BALL_HEIGHT` consecutive scanlines.
- `tests/test_positioning.py` rewritten: the model now matches the measured
  hardware behavior (coarse `15*q`/`3`, fine `s - 7`, ball `-1`, and the
  compensation in both callers) and asserts rendered == requested for every
  `P` / `ball_x`, plus exactly 1 pixel of motion per frame across every
  coarse/fine boundary. One test was added for the measured offsets.
- `docs/en/timing.md`, `docs/en/architecture.md`, `docs/pt-BR/timing.md`,
  `docs/pt-BR/arquitetura.md`, `docs/en/build.md`, `docs/pt-BR/build.md`,
  `docs/en/benchmarks.md`, `docs/pt-BR/benchmarks.md`: timer 43, HMOVE-after-
  WSYNC, the 4x4 ball kernel accounting, and the positioning compensation.

## Validation

The empirical mapping was measured by freezing the ball (`ball_x`/`ball_y`
written every frame) and the paddles, building and snapshotting Stella in a
graphical session, and reading the rendered color-clock columns:

- ball `ball_x` 0, 3, 6, 7, 8, 13, 14, 15, 22, 28, 29, 30, 45, 60, 100, 150,
  156: rendered left color clock == `ball_x` in every case, including the
  coarse/fine boundaries 6->7, 13->14 and 28->29 (no jump, no pause).
- paddles `PLAYER1_X` 7, 8, 13, 14, 15, 16, 22, 29, 30, 45, 150: rendered
  bit 7 == `PLAYER1_X` in every case.

Measurement hygiene: a unique frozen `ball_y` was derived from `ball_x` so a
stale window capture was immediately detectable, and leftover Stella
processes were killed with `pkill -9 -x stella` (a leaked `-snapsavedir`
instance with the ROM path later in its command line had contaminated
earlier captures).

## Timing Impact

Before (committed Round 2, 1-scanline ball):
- Frame scanlines: 262
- Kernel worst/best: 71 / 57 cycles (slack 5)
- Ball block: 15 on the ball's line, 13 otherwise
- `GRP0`/`GRP1`/`ENABL` at ~cycle 24/47/63

After (4x4 ball + positioning fix):
- Frame scanlines: 262 (unchanged)
- Kernel worst/best: 74 / 61 cycles (slack **2**)
- Ball block: 18 on a ball row, 17 otherwise
- `GRP0`/`GRP1`/`ENABL` at ~cycle 26/49/67
- `VBLANK_TIMER_VALUE` 43, `OVERSCAN_TIMER_VALUE` 37

The slack dropped from 5 to 2 cycles: the 4x4 ball costs three more cycles
per line than the 1-scanline version. This is the deliberate cost of a
visible 4x4 object and is well within the 76-cycle budget.

## Memory Impact

Before:
- ROM: 528 bytes
- RAM: 7 bytes

After:
- ROM: 528 bytes (compensation + ball block still fit the page padding)
- RAM: 7 bytes

## Tests

- `tests/test_positioning.py`: rewritten model + added offset test.
- Full suite: **106 tests pass**; quality gates pass (ROM 528/4096,
  RAM 7/128, 262 scanlines, worst 74/76, slack 2). Benchmark and regression
  rerun green.

## Known Limitations

- The q = 0 coarse base of 3 (RESP strobe before TIA cycle 23) is a hardware
  quirk of the divide-loop routine; it is handled by the caller-side
  compensation rather than by changing the shared `PosObject`, which keeps
  the routine identical to the reference.
- Absolute position verification is manual (frozen-frame screenshots); the
  automated suite validates the same mapping through the interpreter model.