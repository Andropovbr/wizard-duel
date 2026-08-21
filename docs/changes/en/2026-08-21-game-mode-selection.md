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
  (4 bytes, $91-$94)
- `HandleInput` routine: edge-detects SELECT (toggles mode in menu) and
  RESET (menu → playing, playing → menu)
- `InitGame` routine: reinitializes all gameplay state, restores all
  colors (COLUP0, COLUP1, COLUPF), HP, positions, clears missiles/flags,
  transitions to STATE_PLAYING
- VBLANK game_state gate: menu mode skips UpdatePlayers/UpdateBall/
  UpdateMissiles
- Menu visual: both paddles visible and frozen, ball hidden (COLUPF set
  to BACKGR_COLOR), P0 colored red (DUEL) or blue (SCORE)
- Explicit initialization of `select_prev` and `reset_prev` to released
  state (SELECT_BIT|RESET_BIT) in Reset handler to ensure correct
  edge detection on first press
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
- `p1_hp=0` hack in menu visual (HP is no longer used as a visual
  mechanism)

## Technical Reasoning

### Switch Edge Detection Fix

SWCHB bits are active-low: 0 = pressed, 1 = released. After RAM clear,
`select_prev` and `reset_prev` were 0, which the code interpreted as
"already pressed". The first real press therefore never produced a
rising edge (0 AND mask = 0 → "still held").

Fix: initialize both to `SELECT_BIT|RESET_BIT` (= 0x0C, both released)
in the Reset handler after the RAM clear loop.

### Menu Visual

The previous implementation hid P1 by setting `p1_hp=0`, which caused
`ProcessHitEffects` to permanently lock P1's fire input via the
dead-player fire lock. The new approach keeps both paddles visible
(both HP at 3), hides the ball by matching COLUPF to the background
color, and changes P0's color to indicate the selected mode.

### InitGame Restoration

`InitGame` now restores all visual registers: COLUP0 (PLAYER1_COLOR),
COLUP1 (PLAYER2_COLOR), COLUPF (BALL_COLOR). After RESET, the game
looks and behaves exactly as it did before the menu was introduced.

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
- Game mode is preserved across menu ↔ playing transitions

## Next Logical Steps

- Implement SCORE mode gameplay differences
- Add title screen text or animation
- Consider sound effects for SELECT/RESET feedback
