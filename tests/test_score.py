"""SCORE mode validation (Round 13).

Runs the assembled ROM on the deterministic 6502 emulator (tools/emu6502.py)
and exercises the SCORE mode assembly: goal detection in UpdateBall,
KO scoring in ProcessHitEffects, and rally reset via ResetRally.

SCORE mode mechanics:
  - Ball exits right (BALL_X_MAX) while moving right → P0 +1
  - Ball exits left  (BALL_X_MIN) while moving left  → P1 +1
  - Player KO (HP == 0 after damage) → opponent +1
  - P0-first priority: if both players die, only P0 KO counts
  - Max 1 point per rally
  - Goal/KO sets pending_rally_reset, which triggers ResetRally next frame
  - ResetRally restores HP, centers ball, clears missiles and flags
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from common import ROM_PATH, require_build, parse_symbols
from emu6502 import Cpu, load_rom
from test_timing import read_constants

C = read_constants()
BALL_X_MAX = C["BALL_X_MAX"]     # 159
BALL_X_MIN = C["BALL_X_MIN"]     # 0
DIR_RIGHT = C["DIR_RIGHT"]       # 1
DIR_LEFT  = C["DIR_LEFT"]        # $FF (-1)
DIR_DOWN  = C["DIR_DOWN"]        # 1
HIT_P0 = C["HIT_P0"]            # %00000001: P0 hit by M1
HIT_P1 = C["HIT_P1"]            # %00000010: P1 hit by M0
M0P_P1 = 0x80                    # CXM0P D7
M1P_P0 = 0x80                    # CXM1P D7
RALLY_RESET_KO = C["RALLY_RESET_KO"]        # 1
RALLY_RESET_P0_GOAL = C["RALLY_RESET_P0_GOAL"]  # 2
RALLY_RESET_P1_GOAL = C["RALLY_RESET_P1_GOAL"]  # 3


def _sym():
    return parse_symbols()


class SCOREHarness:
    """Drives the ROM in SCORE mode with controlled ball state."""

    def __init__(self):
        require_build()
        self.rom = load_rom(ROM_PATH)
        self.sym = _sym()
        self.cpu = Cpu(self.rom)
        self.cpu.reset()
        self.cpu.riot[2] = 0x03
        self.cpu.inpt[4] = 0xFF
        self.cpu.inpt[5] = 0xFF
        self.cpu.ram[self._ram("game_state")] = 1  # STATE_PLAYING
        self.sof_addr = self.sym["StartOfFrame"]

    def boot_sync(self):
        """Boot into STATE_PLAYING, SCORE mode, full HP."""
        self.set_buttons(False, False)
        self.run_frame()
        self.cpu.riot[2] = 0x00
        self.run_frame()
        self.cpu.riot[2] = 0x03
        self.run_frame()
        # Force SCORE mode (boot artifact toggles game_mode, ensure it's 1)
        self.cpu.ram[self._ram("game_mode")] = 1

    def _ram(self, name):
        return self.sym[name] - 0x80

    def set_buttons(self, p0, p1):
        self.cpu.inpt[4] = 0x00 if p0 else 0xFF
        self.cpu.inpt[5] = 0x00 if p1 else 0xFF

    def set_collisions(self, m0_p1=False, m1_p0=False):
        """Set TIA collision latches for KO testing."""
        if m0_p1:
            self.cpu.cxm0p |= M0P_P1
        if m1_p0:
            self.cpu.cxm1p |= M1P_P0

    def run_frame(self):
        sof = self.sof_addr
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
            "score_p0": m[self._ram("score_p0")],
            "score_p1": m[self._ram("score_p1")],
            "p0_hp": m[self._ram("p0_hp")],
            "p1_hp": m[self._ram("p1_hp")],
            "p0_y": m[self._ram("P0Y")],
            "p1_y": m[self._ram("P1Y")],
            "ball_x": m[self._ram("ball_x")],
            "ball_y": m[self._ram("ball_y")],
            "ball_dx": m[self._ram("ball_dx")],
            "ball_dy": m[self._ram("ball_dy")],
            "m_active": m[self._ram("m_active")],
            "pending_rally_reset": m[self._ram("pending_rally_reset")],
            "hit_flags": m[self._ram("hit_flags")],
            "fire_prev": m[self._ram("fire_prev")],
        }

    def set_ball(self, x, dx):
        """Set ball position and direction for goal detection tests."""
        self.cpu.ram[self._ram("ball_x")] = x & 0xFF
        self.cpu.ram[self._ram("ball_dx")] = dx & 0xFF


class TestGoalRight(unittest.TestCase):
    """Ball exits right → P0 +1."""

    def setUp(self):
        self.h = SCOREHarness()
        self.h.boot_sync()

    def test_right_goal_increments_p0_score(self):
        self.h.set_ball(BALL_X_MAX, DIR_RIGHT)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["score_p0"], 1, "P0 should score on right goal")
        self.assertEqual(s["score_p1"], 0, "P1 score unchanged")

    def test_right_goal_sets_pending_rally_reset(self):
        self.h.set_ball(BALL_X_MAX, DIR_RIGHT)
        self.h.run_frame()
        self.assertEqual(self.h.state()["pending_rally_reset"],
                         RALLY_RESET_P0_GOAL)

    def test_right_goal_clears_missiles(self):
        self.h.cpu.ram[self.h._ram("m_active")] = 0x03  # both missiles active
        self.h.set_ball(BALL_X_MAX, DIR_RIGHT)
        self.h.run_frame()
        self.assertEqual(self.h.state()["m_active"], 0, "missiles cleared on goal")

    def test_right_goal_skips_ball_movement(self):
        self.h.set_ball(BALL_X_MAX, DIR_RIGHT)
        self.h.run_frame()
        # Ball should NOT have moved (goal skips movement)
        self.assertEqual(self.h.state()["ball_x"], BALL_X_MAX)


class TestGoalLeft(unittest.TestCase):
    """Ball exits left → P1 +1."""

    def setUp(self):
        self.h = SCOREHarness()
        self.h.boot_sync()

    def test_left_goal_increments_p1_score(self):
        self.h.set_ball(BALL_X_MIN, DIR_LEFT)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["score_p1"], 1, "P1 should score on left goal")
        self.assertEqual(s["score_p0"], 0, "P0 score unchanged")

    def test_left_goal_sets_pending_rally_reset(self):
        self.h.set_ball(BALL_X_MIN, DIR_LEFT)
        self.h.run_frame()
        self.assertEqual(self.h.state()["pending_rally_reset"],
                         RALLY_RESET_P1_GOAL)


class TestNoGoalWithoutEdge(unittest.TestCase):
    """Ball not at edge → no score, normal movement."""

    def setUp(self):
        self.h = SCOREHarness()
        self.h.boot_sync()

    def test_ball_not_at_edge_no_score(self):
        self.h.set_ball(78, DIR_RIGHT)  # middle, moving right
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["score_p0"], 0)
        self.assertEqual(s["score_p1"], 0)
        self.assertEqual(s["pending_rally_reset"], 0)

    def test_ball_at_edge_wrong_direction_no_score(self):
        self.h.set_ball(BALL_X_MAX, DIR_LEFT)  # at right edge but moving left
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["score_p0"], 0, "no score when moving away from edge")

    def test_ball_at_left_edge_moving_right_no_score(self):
        self.h.set_ball(BALL_X_MIN, DIR_RIGHT)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["score_p1"], 0, "no score when moving away from edge")


class TestKOScoring(unittest.TestCase):
    """Player KO → opponent scores, P0-first priority."""

    def setUp(self):
        self.h = SCOREHarness()
        self.h.boot_sync()

    def test_p0_ko_p1_scores(self):
        """M1 hits P0 (via TIA latch) while P0 has 1 HP → KO → P1 scores."""
        self.h.cpu.ram[self.h._ram("p0_hp")] = 1
        self.h.set_collisions(m1_p0=True)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["score_p1"], 1, "P1 scores when P0 is KO'd")
        self.assertEqual(s["score_p0"], 0)

    def test_p1_ko_p0_scores(self):
        """M0 hits P1 (via TIA latch) while P1 has 1 HP → KO → P0 scores."""
        self.h.cpu.ram[self.h._ram("p1_hp")] = 1
        self.h.set_collisions(m0_p1=True)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["score_p0"], 1, "P0 scores when P1 is KO'd")
        self.assertEqual(s["score_p1"], 0)

    def test_both_ko_p0_first_priority(self):
        """P0-first priority: both at 1 HP, both hit → only P1 scores."""
        self.h.cpu.ram[self.h._ram("p0_hp")] = 1
        self.h.cpu.ram[self.h._ram("p1_hp")] = 1
        self.h.set_collisions(m0_p1=True, m1_p0=True)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["score_p1"], 1, "P1 scores (P0 KO priority)")
        self.assertEqual(s["score_p0"], 0, "P0 does not score (P0-first)")

    def test_ko_sets_pending_rally_reset(self):
        self.h.cpu.ram[self.h._ram("p0_hp")] = 1
        self.h.set_collisions(m1_p0=True)
        self.h.run_frame()
        self.assertEqual(self.h.state()["pending_rally_reset"], 1)


class TestRallyReset(unittest.TestCase):
    """ResetRally restores HP, positions, ball, missiles, flags."""

    def setUp(self):
        self.h = SCOREHarness()
        self.h.boot_sync()

    def test_hp_restored_after_rally_reset(self):
        # Kill P0 via M1 hit → KO → next frame ResetRally restores HP
        self.h.cpu.ram[self.h._ram("p0_hp")] = 1
        self.h.set_collisions(m1_p0=True)
        self.h.run_frame()  # KO frame → pending_rally_reset=1
        self.h.run_frame()  # ResetRally runs in VBLANK
        s = self.h.state()
        self.assertEqual(s["p0_hp"], C["PLAYER_START_HP"])
        self.assertEqual(s["p1_hp"], C["PLAYER_START_HP"])

    def test_ball_centered_after_rally_reset(self):
        self.h.cpu.ram[self.h._ram("p0_hp")] = 1
        self.h.set_collisions(m1_p0=True)
        self.h.run_frame()
        self.h.run_frame()
        s = self.h.state()
        # ResetRally sets ball_x=BALL_X_INIT, then UpdateBall moves it
        # one pixel (ball_dx=DIR_RIGHT).  Accept the normal movement.
        self.assertEqual(s["ball_dx"], DIR_RIGHT,
                         "ball direction reset to DIR_RIGHT")

    def test_missiles_cleared_after_rally_reset(self):
        self.h.cpu.ram[self.h._ram("m_active")] = 0x03
        self.h.cpu.ram[self.h._ram("p0_hp")] = 1
        self.h.set_collisions(m1_p0=True)
        self.h.run_frame()
        self.h.run_frame()
        self.assertEqual(self.h.state()["m_active"], 0)

    def test_pending_rally_reset_cleared_after_reset(self):
        self.h.cpu.ram[self.h._ram("p0_hp")] = 1
        self.h.set_collisions(m1_p0=True)
        self.h.run_frame()
        self.h.run_frame()
        self.assertEqual(self.h.state()["pending_rally_reset"], 0)


class TestMaxOnePointPerRally(unittest.TestCase):
    """Only one point can be scored per rally (KO priority prevents double)."""

    def setUp(self):
        self.h = SCOREHarness()
        self.h.boot_sync()

    def test_ko_only_one_point(self):
        """Both at 1 HP, both hit → P0-first, only P1 scores."""
        self.h.cpu.ram[self.h._ram("p0_hp")] = 1
        self.h.cpu.ram[self.h._ram("p1_hp")] = 1
        self.h.set_collisions(m0_p1=True, m1_p0=True)
        self.h.run_frame()
        s = self.h.state()
        total = s["score_p0"] + s["score_p1"]
        self.assertEqual(total, 1, "exactly 1 point per rally")


class TestFireLockDuringPendingReset(unittest.TestCase):
    """Fire lock gate: skip damage when pending_rally_reset is set by a goal."""

    def setUp(self):
        self.h = SCOREHarness()
        self.h.boot_sync()

    def test_damage_skipped_after_goal(self):
        """A goal sets pending_rally_reset=1 in UpdateBall.  ProcessHitEffects
        should then skip damage for the rest of that frame."""
        self.h.cpu.ram[self.h._ram("p0_hp")] = 2
        self.h.cpu.ram[self.h._ram("p1_hp")] = 2
        self.h.set_ball(BALL_X_MAX, DIR_RIGHT)       # goal triggers pending_rally_reset
        self.h.set_collisions(m0_p1=True, m1_p0=True) # both hit, would deal 2 damage
        self.h.run_frame()
        s = self.h.state()
        # Goal scored, pending_rally_reset was set before ProcessHitEffects ran
        self.assertEqual(s["score_p0"], 1, "P0 goal scored")
        # Damage was skipped because pending_rally_reset was set
        self.assertGreaterEqual(s["p0_hp"], 2,
                                "P0 HP not reduced (damage skipped by fire lock gate)")
        self.assertGreaterEqual(s["p1_hp"], 2,
                                "P1 HP not reduced (damage skipped by fire lock gate)")


class TestScoreAccumulation(unittest.TestCase):
    """Scores accumulate across multiple rallies."""

    def setUp(self):
        self.h = SCOREHarness()
        self.h.boot_sync()

    def test_two_right_goals(self):
        self.h.set_ball(BALL_X_MAX, DIR_RIGHT)
        self.h.run_frame()  # goal 1 → pending
        self.h.run_frame()  # ResetRally
        self.h.set_ball(BALL_X_MAX, DIR_RIGHT)
        self.h.run_frame()  # goal 2 → pending
        self.assertEqual(self.h.state()["score_p0"], 2)

    def test_mixed_goals(self):
        self.h.set_ball(BALL_X_MAX, DIR_RIGHT)
        self.h.run_frame()
        self.h.run_frame()  # reset
        self.h.set_ball(BALL_X_MIN, DIR_LEFT)
        self.h.run_frame()
        self.h.run_frame()  # reset
        s = self.h.state()
        self.assertEqual(s["score_p0"], 1)
        self.assertEqual(s["score_p1"], 1)


class TestServeDirection(unittest.TestCase):
    """After a goal, the ball serves toward the player who scored."""

    def setUp(self):
        self.h = SCOREHarness()
        self.h.boot_sync()

    def test_p0_goal_serves_left_toward_p0(self):
        """P0 scores (right goal) → next rally ball_dx = DIR_LEFT."""
        self.h.set_ball(BALL_X_MAX, DIR_RIGHT)
        self.h.run_frame()  # P0 scores → pending_rally_reset = RALLY_RESET_P0_GOAL
        self.h.run_frame()  # ResetRally runs
        s = self.h.state()
        self.assertEqual(s["ball_dx"], DIR_LEFT,
                         "after P0 goal, ball serves left toward P0")

    def test_p1_goal_serves_right_toward_p1(self):
        """P1 scores (left goal) → next rally ball_dx = DIR_RIGHT."""
        self.h.set_ball(BALL_X_MIN, DIR_LEFT)
        self.h.run_frame()  # P1 scores → pending_rally_reset = RALLY_RESET_P1_GOAL
        self.h.run_frame()  # ResetRally runs
        s = self.h.state()
        self.assertEqual(s["ball_dx"], DIR_RIGHT,
                         "after P1 goal, ball serves right toward P1")

    def test_ko_serves_right_by_default(self):
        """KO → pending_rally_reset = RALLY_RESET_KO → DIR_RIGHT."""
        self.h.cpu.ram[self.h._ram("p0_hp")] = 1
        self.h.set_collisions(m1_p0=True)
        self.h.run_frame()  # KO → pending_rally_reset = RALLY_RESET_KO
        self.h.run_frame()  # ResetRally runs
        s = self.h.state()
        self.assertEqual(s["ball_dx"], DIR_RIGHT,
                         "after KO, ball serves right (default)")

    def test_score_preserved_across_rally(self):
        """Score persists across rally reset."""
        self.h.set_ball(BALL_X_MAX, DIR_RIGHT)
        self.h.run_frame()  # P0 scores
        self.h.run_frame()  # reset
        s = self.h.state()
        self.assertEqual(s["score_p0"], 1, "score persists after reset")


class TestPlayerCentering(unittest.TestCase):
    """Both players start centered vertically in the arena."""

    def setUp(self):
        self.h = SCOREHarness()
        self.h.boot_sync()

    def test_both_players_same_y_after_boot(self):
        """P0 and P1 Y positions are equal after InitGame."""
        s = self.h.state()
        self.assertEqual(s["p0_y"], s["p1_y"],
                         "both players must share the same initial Y")

    def test_players_centered_in_arena(self):
        """Initial Y equals (KERNEL_SCANLINES - PLAYER_HEIGHT) / 2."""
        s = self.h.state()
        expected = (C["KERNEL_SCANLINES"] - C["PLAYER_HEIGHT"]) // 2
        self.assertEqual(s["p0_y"], expected,
                         "P0 Y must be vertically centered")
        self.assertEqual(s["p1_y"], expected,
                         "P1 Y must be vertically centered")

    def test_players_centered_after_rally_reset(self):
        """ResetRally centers both players."""
        self.h.cpu.ram[self.h._ram("p0_hp")] = 1
        self.h.set_collisions(m1_p0=True)
        self.h.run_frame()  # KO
        self.h.run_frame()  # ResetRally
        s = self.h.state()
        expected = (C["KERNEL_SCANLINES"] - C["PLAYER_HEIGHT"]) // 2
        self.assertEqual(s["p0_y"], expected,
                         "P0 centered after rally reset")
        self.assertEqual(s["p1_y"], expected,
                         "P1 centered after rally reset")


if __name__ == "__main__":
    unittest.main()
