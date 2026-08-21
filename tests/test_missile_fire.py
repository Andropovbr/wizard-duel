"""Missile fire-input validation (one press = one shot).

Runs the assembled ROM on the deterministic 6502 emulator (tools/emu6502.py)
and exercises the real UpdateMissiles assembly with controlled INPT4/INPT5
states.  The emulator models the real hardware boot behavior where the TIA
INPT latches read the fire lines as pressed for the first frames after RESET,
so these tests verify that a boot-time reading can never look like a fire.

Expected semantics (independent per player):

  * boot with FIRE released: no automatic shot
  * boot with FIRE held: no automatic shot; a release+press is required
  * released -> pressed while the missile is inactive: one shot
  * button held: no repeat fire
  * pressed -> released: only rearms the input
  * a new released -> pressed fires again once the missile has despawned
  * a missile despawning while FIRE is still held does NOT auto-respawn
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from common import ROM_PATH, require_build
from emu6502 import Cpu, load_rom


def _sym():
    from common import parse_symbols
    return parse_symbols()


class MissileFireHarness:
    """Drives the ROM frame-by-frame with controlled fire-button states."""

    def __init__(self, boot_artifact=True):
        require_build()
        self.rom = load_rom(ROM_PATH)
        self.sym = _sym()
        self.cpu = Cpu(self.rom)
        self.cpu.reset()
        # Release SELECT and RESET on the console switches (SWCHB riot[2]).
        # Bit 1 = SELECT (active low), bit 0 = RESET (active low).
        # 0x03 = both released (bits 1+0 set).
        self.cpu.riot[2] = 0x03
        if boot_artifact:
            # Real hardware/Stella read the fire lines as pressed on the first
            # frames after reset (INPT latch state).
            self.cpu.inpt[4] = 0x00
            self.cpu.inpt[5] = 0x00
            self.set_buttons(False, False)

    def _ram(self, name):
        return self.sym[name] - 0x80

    def set_buttons(self, p0, p1):
        """Set both fire buttons for the NEXT frames (True = pressed)."""
        self.cpu.inpt[4] = 0x00 if p0 else 0xFF
        self.cpu.inpt[5] = 0x00 if p1 else 0xFF

    def run_frame(self):
        """Run exactly one frame (the one currently being entered)."""
        sof = self.sym["StartOfFrame"]
        at_sof = self.cpu.pc == sof
        count = 0
        start = self.cpu.steps
        while self.cpu.steps < start + 500000:
            self.cpu.step()
            if self.cpu.pc == sof:
                count += 1
                if (at_sof and count == 1) or count == 2:
                    return

    def state(self):
        m = self.cpu.ram
        return {
            "m0": m[self._ram("m_active")] & 0x01,          # M0_BIT
            "m1": (m[self._ram("m_active")] >> 1) & 0x01,   # M1_BIT
            "m0_x": m[self._ram("m0_x")],
            "m1_x": m[self._ram("m1_x")],
            "fire_prev": m[self._ram("fire_prev")],
            "fire_sync": (m[self._ram("fire_prev")] >> 7) & 0x01,  # FIRE_SYNC
        }

    def boot_sync(self):
        """Run the boot-sync frame and enter STATE_PLAYING via InitGame.

        Frame 0: Reset handler runs (clears RAM, game_state=0), frame runs
        in menu mode (UpdateMissiles skipped).
        Then simulates a RESET rising edge which triggers InitGame:
        restores p1_hp, clears fire_prev, sets game_state=1.
        Frame 1: first full playing frame; UpdateMissiles syncs fire_prev
        with the released button state (FIRE_SYNC set, no spawn).
        """
        self.set_buttons(False, False)
        self.run_frame()                        # frame 0: menu mode
        # Simulate RESET rising edge to trigger InitGame (which sets
        # p1_hp, clears fire_prev, and transitions to STATE_PLAYING).
        reset_bit = self.cpu.riot[2] & 0x01     # current RESET state (bit 0)
        self.cpu.ram[self._ram("reset_prev")] = reset_bit
        self.cpu.riot[2] = 0x00                  # press RESET
        self.run_frame()                        # frame 1: InitGame + sync
        self.cpu.riot[2] = 0x03                  # release RESET


class TestBoot(unittest.TestCase):
    def _enter_playing(self, h):
        """Simulate a RESET rising edge to trigger InitGame after the boot frame."""
        reset_bit = h.cpu.riot[2] & 0x01  # bit 0 = RESET
        h.cpu.ram[h._ram("reset_prev")] = reset_bit
        h.cpu.riot[2] = 0x00
        h.run_frame()
        h.cpu.riot[2] = 0x03

    def test_boot_with_released_buttons_no_missiles(self):
        # Real boot: the latches read pressed on frame 1, then released.  The
        # first-frame sync must prevent any automatic shot.
        h = MissileFireHarness(boot_artifact=True)
        h.set_buttons(False, False)
        h.run_frame()          # sync frame (latch artifact = pressed)
        self._enter_playing(h) # RESET -> InitGame + first playing frame
        s = h.state()
        self.assertEqual(s["m0"], 0)
        self.assertEqual(s["m1"], 0)
        self.assertEqual(s["fire_sync"], 1)

    def test_boot_clean_released_buttons_no_missiles(self):
        # Even if INPT reads released from the very first frame, no shot.
        h = MissileFireHarness(boot_artifact=False)
        h.set_buttons(False, False)
        h.run_frame()
        self._enter_playing(h)
        s = h.state()
        self.assertEqual(s["m0"], 0)
        self.assertEqual(s["m1"], 0)
        self.assertEqual(s["fire_sync"], 1)

    def test_boot_with_buttons_held_no_auto_fire(self):
        h = MissileFireHarness(boot_artifact=True)
        h.set_buttons(True, True)      # genuinely held at boot
        h.run_frame()                   # frame 0: Reset runs, menu mode
        self._enter_playing(h)          # RESET -> InitGame + sync frame
        for _ in range(6):
            h.run_frame()
            s = h.state()
            self.assertEqual(s["m0"], 0)
            self.assertEqual(s["m1"], 0)
        # release then press -> fires (no auto fire just because of boot)
        h.set_buttons(False, False)
        h.run_frame()
        h.set_buttons(True, True)
        h.run_frame()
        s = h.state()
        self.assertEqual(s["m0"], 1)
        self.assertEqual(s["m1"], 1)

    def test_no_missiles_without_any_input(self):
        # Never touch the buttons; nothing may fire.
        h = MissileFireHarness(boot_artifact=True)
        h.boot_sync()
        for _ in range(10):
            h.run_frame()
            s = h.state()
            self.assertEqual(s["m0"], 0)
            self.assertEqual(s["m1"], 0)


class TestEdgeDetection(unittest.TestCase):
    def setUp(self):
        self.h = MissileFireHarness(boot_artifact=True)
        self.h.boot_sync()

    def test_released_to_pressed_p0_spawns_m0(self):
        self.h.set_buttons(True, False)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["m0"], 1, "M0 must spawn on a P0 press")
        self.assertEqual(s["m1"], 0, "P0 press must not affect M1")
        # spawn lands at M0_X_INIT then moves: x should be 20 after one frame
        self.assertEqual(s["m0_x"], 20)

    def test_released_to_pressed_p1_spawns_m1(self):
        self.h.set_buttons(False, True)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["m1"], 1, "M1 must spawn on a P1 press")
        self.assertEqual(s["m0"], 0, "P1 press must not affect M0")

    def test_holding_button_no_repeat_fire(self):
        self.h.set_buttons(True, False)
        self.h.run_frame()
        self.assertEqual(self.h.state()["m0"], 1)
        x_after_spawn = self.h.state()["m0_x"]
        # keep holding for several frames: no second missile, position just moves
        for _ in range(5):
            self.h.run_frame()
            s = self.h.state()
            self.assertEqual(s["m0"], 1)
            self.assertGreater(s["m0_x"], x_after_spawn)
        self.assertEqual(self.h.state()["m0_x"], x_after_spawn + 5 * 2)

    def test_release_just_rearms(self):
        self.h.set_buttons(True, False)
        self.h.run_frame()
        self.assertEqual(self.h.state()["m0"], 1)
        self.h.set_buttons(False, False)
        self.h.run_frame()             # release: rearm, no new spawn
        s = self.h.state()
        self.assertEqual(s["m0"], 1, "release must not spawn or despawn")

    def test_both_pressed_simultaneously(self):
        self.h.set_buttons(True, True)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["m0"], 1)
        self.assertEqual(s["m1"], 1)

    def test_players_are_independent(self):
        # P0 pressed, then released, then P1 pressed.
        self.h.set_buttons(True, False)
        self.h.run_frame()
        self.assertEqual(self.h.state()["m0"], 1)
        self.assertEqual(self.h.state()["m1"], 0)
        self.h.set_buttons(False, False)
        self.h.run_frame()
        self.h.set_buttons(False, True)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["m0"], 1)
        self.assertEqual(s["m1"], 1)


class TestMissileActive(unittest.TestCase):
    def setUp(self):
        self.h = MissileFireHarness(boot_artifact=True)
        self.h.boot_sync()

    def test_press_while_missile_active_does_not_respawn(self):
        self.h.set_buttons(True, False)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["m0"], 1)
        spawned_x = s["m0_x"]
        # release and press again while M0 is still flying
        self.h.set_buttons(False, False)
        self.h.run_frame()
        self.h.set_buttons(True, False)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["m0"], 1, "missile must stay active")
        self.assertGreater(s["m0_x"], spawned_x,
                           "an existing missile must not be reset/re-spawned")

    def test_second_press_after_despawn_fires_again(self):
        self.h.set_buttons(True, False)
        self.h.run_frame()
        self.assertEqual(self.h.state()["m0"], 1)
        # let M0 fly off the right edge and despawn (70+ frames)
        for _ in range(80):
            self.h.run_frame()
        self.assertEqual(self.h.state()["m0"], 0)
        # release + press -> a brand new missile
        self.h.set_buttons(False, False)
        self.h.run_frame()
        self.h.set_buttons(True, False)
        self.h.run_frame()
        self.assertEqual(self.h.state()["m0"], 1)

    def test_despawn_while_held_does_not_auto_respawn(self):
        self.h.set_buttons(True, False)
        self.h.run_frame()
        self.assertEqual(self.h.state()["m0"], 1)
        # push M0 to the edge so it despawns while the button stays held
        self.h.cpu.ram[self.h._ram("m0_x")] = 156
        for _ in range(3):             # 156 -> 158 -> 160 (despawn)
            self.h.run_frame()
        self.assertEqual(self.h.state()["m0"], 0)
        # keep holding: it must NOT auto-respawn
        for _ in range(6):
            self.h.run_frame()
            self.assertEqual(self.h.state()["m0"], 0,
                             "despawn while held must not auto-fire")
        # release + press -> fires again
        self.h.set_buttons(False, False)
        self.h.run_frame()
        self.h.set_buttons(True, False)
        self.h.run_frame()
        self.assertEqual(self.h.state()["m0"], 1)


if __name__ == "__main__":
    unittest.main()
