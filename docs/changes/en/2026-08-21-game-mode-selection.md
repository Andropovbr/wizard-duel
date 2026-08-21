# Change: Initial Game Mode Selection Infrastructure

## Objective

Implement the initial game mode selection infrastructure: a state machine
(STATE_MENU / STATE_PLAYING), SELECT button toggles between DUEL and SCORE
modes, RESET starts the game, and a low-cost visual indicator shows the
selected mode on the title screen.

## Added

- `STATE_MENU` (0) and `STATE_PLAYING` (1) constants in `constants.inc`
- `MODE_DUEL` (0) and `MODE_SCORE` (1) constants in `constants.inc`
- `SELECT_BIT` and `RESET_BIT` switch definitions in `constants.inc`
- `game_state`, `game_mode`, `select_prev`, `reset_prev` RAM variables
  (4 bytes, $81-$84)
- `HandleInput` routine: edge-detects SELECT (toggles mode in menu) and
  RESET (menu → playing, playing → menu)
- `InitGame` routine: reinitializes all gameplay state, restores HP,
  clears missiles/flags, transitions to STATE_PLAYING
- VBLANK game_state gate: menu mode skips UpdatePlayers/UpdateBall/
  UpdateMissiles, sets P0 color indicator, sets p1_hp=0 to hide P1
- Menu visual: P0 colored red (DUEL) or blue (SCORE), P1 hidden
- `fire_prev` cleared in InitGame to prevent stale dead-player fire lock
- Test harness boot_sync: simulates RESET rising edge via InitGame
  to properly enter STATE_PLAYING with full HP
- Educational change log entries (EN + PT-BR)

## Changed

- `test_ball.py` RAM assertion: 81 → 85 bytes
- `test_memory.py` RAM assertion: already 85 bytes (from previous round)
- `test_missile_fire.py` MissileFireHarness: added riot[2] init,
  boot_sync() method with proper RESET simulation
- `test_missile_fire.py` TestBoot: added `_enter_playing()` helper
- `test_missile_fire.py` TestEdgeDetection/TestMissileActive setUp:
  uses boot_sync() for proper state setup
- `test_frame_timing.py` test_missiles_actually_fire_and_despawn:
  uses RESET simulation pattern
- `test_hp.py` TestInitialHp setUp: uses boot_sync() only (no
  redundant RESET)

## Removed

- Redundant `game_state=1` direct writes in test setUp methods
  (replaced by proper RESET simulation via InitGame)

## Technical Reasoning

### Atari 2600 RESET Is a Readable Switch

On the Atari 2600, RESET is NOT a hardware reset — it is a readable
switch (SWCHB bit 2). Only power-on clears RAM via the Reset vector.
This means `game_state` defaults to 0 (STATE_MENU) from the RAM clear,
and RESET must be edge-detected to transition between states.

### Dead-Player Fire Lock Interaction

`ProcessHitEffects` runs unconditionally during overscan. When `p1_hp=0`
(set by menu visual to hide P1), it ORs `FIRE_P1` into `fire_prev`,
permanently locking P1's fire input. This is correct behavior for dead
players during gameplay, but in menu mode it caused P1 to never fire
after transitioning to STATE_PLAYING.

Fix: `InitGame` clears `fire_prev` when entering playing state, and
test harnesses simulate the RESET rising edge to trigger `InitGame`
rather than setting `game_state` directly.

### Game State Gate

The VBLANK section checks `game_state` after `HandleInput` returns.
If STATE_MENU: skips gameplay updates, sets visual indicator.
If STATE_PLAYING: runs full gameplay pipeline (UpdatePlayers, UpdateBall,
UpdateMissiles). This keeps the kernel structure unchanged and the
scanline timing identical.

## Timing Impact

Before:
- Frame scanlines: 262
- Critical path: unchanged

After:
- Frame scanlines: 262
- Critical path: unchanged

The game_state check adds 3 cycles (LDA) + 2/3 cycles (BEQ) to the
VBLANK path, which is well within the VBLANK timing budget.

## Memory Impact

Before:
- ROM: 2064 bytes
- RAM: 81 bytes

After:
- ROM: 2064 bytes
- RAM: 85 bytes (+4: game_state, game_mode, select_prev, reset_prev)

## Tests

- 261 tests pass
- All quality gates pass (ROM ≤ 4096, RAM ≤ 128, 262 scanlines)
- New test patterns: RESET simulation via rising edge for proper
  InitGame transition in test harnesses

## Known Limitations

- SELECT only works in STATE_MENU (by design)
- No visual feedback yet for mode selection beyond P0 color
- Game mode is preserved across menu ↔ playing transitions

## Next Logical Steps

- Add visual indication for DUEL vs SCORE (e.g., different background
  color, text, or icon)
- Implement SCORE mode gameplay differences
- Add title screen text or animation
- Consider sound effects for SELECT/RESET feedback
