# Change: Larger players (Round 7 visual)

## Objective

Increase the visual size of both players (P0 and P1) by approximately 50%
while preserving timing, missiles, collisions, and all quality gates. The
players remain simple rectangular paddles; no character art is introduced.

## Old player dimensions

* Height: 12 scanlines (`PLAYER_HEIGHT = 12`)
* Width: 4 pixels (`PADDLE_BITS = %00111100`)
* Vertical range: 0..172 (`PLAYER_Y_MAX = KERNEL_SCANLINES - PLAYER_HEIGHT - 1`)
* Missile spawn offset: 4 rows below player top

## New player dimensions

* Height: 18 scanlines (`PLAYER_HEIGHT = 18`, +50%)
* Width: 4 pixels (unchanged, `PADDLE_BITS = %00111100`)
* Vertical range: 0..166 (`PLAYER_Y_MAX = 185 - 18 - 1`)
* Missile spawn offset: 7 rows below player top (centered on 18-row paddle)

## Technique chosen

Height increase via `PLAYER_HEIGHT` constant only. This is the safest
approach because:

1. `PLAYER_HEIGHT` is the single source of truth for paddle height;
2. `PLAYER_Y_MAX` derives automatically from it;
3. The event table builder uses `PLAYER_HEIGHT` for ON/OFF row calculation;
4. No code changes are needed - only the constant value changes.

Width was evaluated separately (see NUSIZ analysis below) and intentionally
left at 4 pixels.

## NUSIZ analysis

The NUSIZ0/NUSIZ1 registers control both player size and missile size:

```
NUSIZ bits 5:4 = missile size (00=1px, 01=2px, 10=4px, 11=8px)
NUSIZ bits 3:1 = player size (000=8x, 001=4x, 010=2x, 100=1x, 101=normal)
NUSIZ bits 7,0 = copy count
```

Currently `NUSIZ0 = NUSIZ1 = %00010000` (missile 2px, player normal, 1 copy).

Setting bits 3:1 to %101 would double the player width to 8 pixels (200%
increase), which is too much. Setting to %010 would make the player 2x
normal width (still 4 pixels with PADDLE_BITS, no visual change). Setting to
%001 would make the player half width (2 pixels), reducing it.

To achieve ~50% width increase (6 pixels), no single NUSIZ configuration
provides the exact value. The closest option would be setting bits 3:1 to
%101 (double width = 8 pixels, +100%), which is too wide.

**Decision: width increase via NUSIZ is deferred.** The height-only increase
achieves the ~50% overall size goal. A future round can explore wider players
through a combination of NUSIZ configuration and adjusted PADDLE_BITS pattern
if needed.

## Missile impact

`MISSILE_SPAWN_OFFSET` changed from 4 to 7 to keep the missile spawning at
the vertical center of the taller (18-row) paddle:

* Before: spawn at player_y + 4 (center of 12-row paddle)
* After: spawn at player_y + 7 (center of 18-row paddle)

Missile size, speed, trajectory, one-press-one-shot behavior, and collision
are all unchanged. The missile spawn adjustment is minimal and documented.

## Collision impact

TIA collision latches are pixel-based: a larger player naturally increases the
collision area. This is the expected behavior:

* Ball x P0 / Ball x P1: larger overlap area, rebound unchanged
* M0 x P1 / M1 x P0: larger overlap area, HP damage unchanged
* No software bounding boxes needed

The wider collision area may cause the ball to remain in contact for more
consecutive frames (the "pianinho" effect documented in Round 7). This is
observed and documented, not debounced.

## Vertical bounds

* `PLAYER_Y_MIN` = 0 (unchanged)
* `PLAYER_Y_MAX` = 166 (was 172)
* Players remain fully visible at both top and bottom of the arena
* Initial positions (P0=48, P1=128) remain within bounds

## Event table

The taller player affects:

* Player ON row: unchanged (player_y)
* Player OFF row: player_y + 18 (was player_y + 12)

The event table builder already handles variable-height objects via the
`PLAYER_HEIGHT` constant. The ON/OFF row calculation in `BuildEvents` uses
`ADC #PLAYER_HEIGHT` which now adds 18 instead of 12.

No new event-table coincidences were introduced. The existing same-row merge
and bump logic handles all cases correctly (verified by 261 tests).

## Timing impact

Before (Round 7 baseline):
- Frame scanlines: 262
- Kernel worst case: 54 / 76 cycles
- Kernel slack: 22 cycles
- VBLANK worst work: 4528 cycles
- VBLANK margin: 336 cycles

After:
- Frame scanlines: 262 (unchanged)
- Kernel worst case: 54 / 76 cycles (unchanged)
- Kernel slack: 22 cycles (unchanged)
- VBLANK worst work: 4528 cycles (unchanged)
- VBLANK margin: 336 cycles (unchanged)

Timing is unchanged because only constants were modified. No code paths
were altered.

## Memory impact

Before:
- ROM: 1808 bytes
- RAM: 81 bytes

After:
- ROM: 1808 bytes (unchanged - constants only)
- RAM: 81 bytes (unchanged - no new variables)

## Tests

Executed: `python tools/test.py` - **261 tests, all PASS** (was 261).

Tests updated to reflect new PLAYER_HEIGHT = 18:

* `tests/test_timing.py` - `test_player_bounds_valid`: height 12 -> 18,
  PLAYER_Y_MAX 172 -> 166
* `tests/test_events.py` - `scene()` function: player height 12 -> 18 in
  the objects dictionary
* `tests/test_events.py` - expected row assertions updated for all tests
  where player OFF rows changed (sorted emission, fire-on-rows, same-row
  merge, non-ball merge, ball-on-floor)
* `tests/test_rom.py` - `PLAYER_HEIGHT` constant 12 -> 18

Quality gates: ROM 1808 <= 4096, RAM 81 <= 128, frame 262 scanlines, kernel
54 <= 76. `python tools/benchmark.py` PASS. `python tools/regression.py`
PASS.

## Known limitations

* Width remains at 4 pixels. The NUSIZ register does not provide a clean
  ~50% width increase option; the closest is double-width (8px, +100%). A
  future round may combine NUSIZ with an adjusted PADDLE_BITS pattern.
* The taller player increases the ball contact area, which may cause more
  consecutive contact frames (pianinho). This is documented, not debounced.
* RAM 81 of 128; unchanged this round.

## Next logical steps

* Consider width increase via NUSIZ + adjusted PADDLE_BITS in a future round.
* Evaluate whether the larger collision area affects gameplay balance.
* Consider player character art (wizards) now that the paddle is larger.
