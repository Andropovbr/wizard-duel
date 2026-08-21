# Change: Small Pong-Style Ball

## Objective

Replace the 4x4 ball with a small 1x2 ball inspired by classic Atari 2600
games (Pong, Video Olympics). The rounded-orb approach explored on the
`round-8-rounded-ball` branch proved that a diamond shape required
disproportionate complexity and kernel timing cost (CTRLPF per-row changes,
mini-loop, 16-cycle kernel penalty). The 2x2 candidate was tested first but
appeared slightly wide; the final choice is 1x2 (1 color clock × 2 scanlines)
using the native TIA ball width.

## Added

- None.

## Changed

- `BALL_WIDTH`: 4 → 1 (1 color clock wide)
- `BALL_HEIGHT`: 4 → 2 (2 scanlines tall)
- `BALL_SIZE_CTRLPF`: `%00100000` (4 clocks) → `%00000000` (1 clock)
- `BALL_X_MAX`: 156 → 159 (160 - BALL_WIDTH)
- `BALL_Y_MAX`: 181 → 183 (KERNEL_SCANLINES - BALL_HEIGHT)
- Updated `test_events.py` Python model: `scene()` now reads `BALL_HEIGHT`
  from the ROM symbol table instead of hardcoding 4.
- Updated hardcoded expected event rows in 6 tests to match the new 2-row
  ball OFF position.
- Updated `test_ball.py`: `test_ball_is_small_2_by_2`, bounce tests use
  `BALL_X_MAX` instead of hardcoded 156.

## Removed

- None.

## Technical Reasoning

The ball is a TIA Ball object. Its width is set by CTRLPF D5:D4:
  - `%00` = 1 clock
  - `%01` = 2 clocks  ← chosen
  - `%10` = 4 clocks  ← previous
  - `%11` = 8 clocks

A 2x2 ball (2 color clocks × 2 scanlines) is the smallest size that
remains clearly visible as an intentional dot rather than a sub-pixel
artifact. The 2-scanline height ensures vertical overlap between
consecutive frames at 1 px/frame motion, avoiding stroboscopic effects.

The ball remains part of the normal event table (ON at ball_y, OFF at
ball_y+2). No mini-loop, no per-row CTRLPF, no special kernel path.
This keeps the table-direct kernel fully intact.

## Timing Impact

Before (4x4 ball):
- Frame: 262 scanlines
- Kernel worst: 54/76 cycles
- Kernel slack: 22

After (2x2 ball):
- Frame: 262 scanlines
- Kernel worst: 54/76 cycles
- Kernel slack: 22

No timing change: the ball uses the same event-driven mechanism; only
CTRLPF constants differ.

## Memory Impact

Before:
- ROM: 1808 bytes
- RAM: 81 bytes

After:
- ROM: 1808 bytes
- RAM: 81 bytes

No change in ROM or RAM usage.

## Tests

- `test_ball_is_small_1_by_2`: validates WIDTH=1, HEIGHT=2, CTRLPF=$00
- `test_ball_bounds_within_visible_area`: validates BALL_X_MAX=159
- `test_bounces_at_right_edge`: uses BALL_X_MAX instead of 156
- `test_bounce_at_bottom_right_corner`: uses BALL_X_MAX instead of 156
- `test_ball_events_are_height_apart`: validates HEIGHT=2
- `test_sorted_emission_preserves_rows`: updated row list (144 added)
- `test_events_fire_on_their_rows`: updated row list
- `test_same_row_events_merge`: updated row list
- `test_non_ball_merge_keeps_scan_order`: updated row list
- `test_dead_player_and_inactive_missiles_contribute_nothing`: updated
- `test_ball_on_floor_drops_off_event`: updated (OFF at 183 now kept)
- All 261 tests pass.

## Known Limitations

- The 2x2 ball has a smaller collision area than the 4x4 ball.
  This is expected and acceptable — TIA collision is pixel-based.

## Next Logical Steps

- Visual validation in Stella (2x2 vs 2x3 comparison)
- Gameplay tuning if the smaller ball feels too hard to hit
