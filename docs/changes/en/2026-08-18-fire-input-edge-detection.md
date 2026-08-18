# Change: Fix fire input - one press = one shot

## Objective

Fix the Round 3 missile trigger logic so that exactly one shot is fired per
button press, with no automatic shot at boot and no re-fire while holding or
while a missile is still active.

## Root cause

Two independent bugs in `UpdateMissiles`:

1. **Boot false fire.** On real hardware (and in Stella) the TIA INPT4/INPT5
   latches read the fire lines as pressed (bit 7 = 0) for the first frames
   after RESET.  `fire_prev` is cleared to 0 by Reset's RAM zeroing, so the
   first frame's `UpdateMissiles` saw "current pressed + previously not
   pressed" and treated the boot-time latch state as a rising edge, firing
   both M0 and M1 without any button press.  After that, `fire_prev` was
   stuck at "pressed", so the next real press produced no edge and firing
   became unreliable until a full release.
2. **No active-missile guard.** The spawn logic only checked the edge; a
   rising edge while the missile was still flying re-spawned it (reset its
   position) instead of being ignored.

## Fire semantics before / after

Before:
- boot: both missiles fired automatically
- press: unreliable (no edge until release, and a press while active reset
  the flying missile)

After (independent per player):
- boot with FIRE released: no shot
- boot with FIRE held: no automatic shot; release + press required
- released -> pressed while the missile is inactive: one shot
- button held: no repeat fire
- pressed -> released: only rearms the input
- a new released -> pressed fires again once the missile has despawned
- a missile despawning while FIRE is still held does NOT auto-respawn

## Implementation

* `UpdateMissiles` samples INPT4/INPT5 into independent bits of `tempA`
  (bit 0 = P0, bit 1 = P1) and keeps the existing rising-edge test
  (`pressed now` and `not pressed last frame`).
* Added the `fire_sync` flag (RAM `$F9`).  On the first call after Reset it
  is 0, so `UpdateMissiles` adopts the real button state into `fire_prev`
  and skips spawning entirely, then sets `fire_sync`.  This synchronizes the
  edge detector with the actual buttons, so the boot-time INPT reading can
  never look like a rising edge.
* Added an active-missile guard: a rising edge spawns only when
  `m0_active`/`m1_active` is 0.  A press while the missile is flying neither
  spawns a second one nor resets the existing one, and it does not consume
  the edge state incorrectly (the press is still recorded in `fire_prev`).

## Boot behavior

`fire_sync` is cleared by Reset (along with all RAM).  On the first frame
`UpdateMissiles` only synchronizes, so:

- boot with FIRE released -> no shot (the latch artifact is absorbed);
- boot with FIRE held -> no shot; the player must release and press again.

## Tests

Added `tools/emu6502.py` (a deterministic 6502 emulator with WSYNC/timer
modeling and controllable INPT4/INPT5 reads) and `tests/test_missile_fire.py`
(13 tests) covering:

- boot released (with and without the latch artifact) -> no missiles
- boot held -> no auto fire, release + press fires
- released -> pressed P0/P1 -> each missile spawns exactly once
- holding -> no repeat fire
- release -> only rearms
- second press after despawn -> fires again
- despawn while held -> no auto-respawn
- P0/P1 independence
- both pressed simultaneously -> both fire once
- no input at all -> no missiles

Updated the RAM budget test (121 -> 122 bytes for `fire_sync`).  Full suite:
131 tests pass.

## Timing / memory

ROM unchanged at 1296/4096 bytes.  RAM 121 -> 122/128 bytes (one byte for
`fire_sync`).  The visible kernel is untouched: worst case 69/76 cycles,
frame exactly 262 scanlines (verified over 30+ frames), ball/paddle
rendering unchanged.

## Known limitations

None new.  The edge detection now matches the documented one-press/one-shot
contract.
