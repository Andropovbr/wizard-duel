"""Ball x Player collision RESPONSE validation (Round 7).

Runs the assembled ROM on the deterministic 6502 emulator (tools/emu6502.py)
and exercises the real ApplyBallRebound assembly that runs at overscan init,
right after ProcessCollisions.  The response is the minimal collision steer:

    Ball x P0  -> ball_dx = DIR_RIGHT  (steer the ball away to the right)
    Ball x P1  -> ball_dx = DIR_LEFT   (steer the ball away to the left)
    no contact -> ball_dx unchanged
    both       -> P1 wins (DIR_LEFT); physically unreachable with the current
                  arena geometry, but defined and tested for determinism
    ball_dy    -> never touched
    HP, hit_flags, m_active -> never touched: a ball contact is NOT a hit

There is NO debounce/immunity: the rebound is re-applied on every frame the
contact is recorded.  Because every re-steer pushes the ball in the SAME
direction, a multi-frame overlap keeps pushing it away (self-limiting): the
contact clears as soon as the ball moves off the paddle.  The reverse-bounce
pattern (ball arriving from the wrong side) is intentionally NOT corrected in
this round; it is observed in Stella and handled at the game-rule level.

Cycle/anchor contract (see ApplyBallRebound in main.asm): the branchless body
is a fixed 27 cycles (+ 6 JSR + 6 RTS), the first overscan WSYNC stays
anchored (kernel-last -> first overscan WSYNC landing = 380 cycles, loop
count 5), and every frame stays at exactly 19912 cycles = 262 scanlines.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from common import ROM_PATH, require_build
from emu6502 import Cpu, load_rom
from test_collision import CollisionHarness, HIT_P0, HIT_P1
from test_timing import read_constants

C = read_constants()
CONTACT_P0 = C["CONTACT_P0"]      # %00000001
CONTACT_P1 = C["CONTACT_P1"]      # %00000010
DIR_LEFT = C["DIR_LEFT"]          # $FF (-1)
DIR_RIGHT = C["DIR_RIGHT"]        # 1
START_HP = C["PLAYER_START_HP"]


class ReboundHarness(CollisionHarness):
    """CollisionHarness plus direct access to the ball step variables."""

    def set_ball_dx(self, dx):
        self.cpu.ram[self._ram("ball_dx")] = dx & 0xFF

    def set_ball_dy(self, dy):
        self.cpu.ram[self._ram("ball_dy")] = dy & 0xFF

    def ball_dx(self):
        return self.cpu.ram[self._ram("ball_dx")]

    def ball_dy(self):
        return self.cpu.ram[self._ram("ball_dy")]

    def park_ball(self):
        """Put the ball mid-arena so UpdateBall cannot hit an edge bounce
        during the test frame (edge bounces would fight the rebound)."""
        from test_collision import _sym
        s = _sym()
        self.cpu.ram[s["ball_x"] - 0x80] = 80
        self.cpu.ram[s["ball_y"] - 0x80] = 90


class TestReboundP0(unittest.TestCase):
    def setUp(self):
        self.h = ReboundHarness()
        self.h.boot_sync()
        self.h.park_ball()

    def test_p0_contact_steers_right_when_coming_right(self):
        self.h.set_ball_dx(DIR_RIGHT)
        self.h.set_collisions(ball_p0=True)
        self.h.run_frame()
        self.assertEqual(self.h.ball_dx(), DIR_RIGHT,
                         "Ball x P0 must set ball_dx = DIR_RIGHT")

    def test_p0_contact_steers_right_when_coming_left(self):
        self.h.set_ball_dx(DIR_LEFT)
        self.h.set_collisions(ball_p0=True)
        self.h.run_frame()
        self.assertEqual(self.h.ball_dx(), DIR_RIGHT,
                         "Ball x P0 must steer the ball right even when "
                         "approaching from the left (the reverse-bounce case "
                         "is intentionally not suppressed in this round)")

    def test_p0_contact_does_not_touch_ball_dy(self):
        self.h.set_ball_dx(DIR_LEFT)
        self.h.set_ball_dy(DIR_LEFT)
        self.h.set_collisions(ball_p0=True)
        self.h.run_frame()
        self.assertEqual(self.h.ball_dx(), DIR_RIGHT,
                         "the rebound must still steer the ball right")
        self.assertEqual(self.h.ball_dy(), DIR_LEFT,
                         "the rebound must never touch ball_dy")


class TestReboundP1(unittest.TestCase):
    def setUp(self):
        self.h = ReboundHarness()
        self.h.boot_sync()
        self.h.park_ball()

    def test_p1_contact_steers_left_when_coming_left(self):
        self.h.set_ball_dx(DIR_LEFT)
        self.h.set_collisions(ball_p1=True)
        self.h.run_frame()
        self.assertEqual(self.h.ball_dx(), DIR_LEFT,
                         "Ball x P1 must set ball_dx = DIR_LEFT")

    def test_p1_contact_steers_left_when_coming_right(self):
        self.h.set_ball_dx(DIR_RIGHT)
        self.h.set_collisions(ball_p1=True)
        self.h.run_frame()
        self.assertEqual(self.h.ball_dx(), DIR_LEFT,
                         "Ball x P1 must steer the ball left even when "
                         "approaching from the right")

    def test_p1_contact_does_not_touch_ball_dy(self):
        self.h.set_ball_dx(DIR_RIGHT)
        self.h.set_ball_dy(DIR_RIGHT)
        self.h.set_collisions(ball_p1=True)
        self.h.run_frame()
        self.assertEqual(self.h.ball_dx(), DIR_LEFT)
        self.assertEqual(self.h.ball_dy(), DIR_RIGHT,
                         "the rebound must never touch ball_dy")


class TestBothContactP1Wins(unittest.TestCase):
    def setUp(self):
        self.h = ReboundHarness()
        self.h.boot_sync()
        self.h.park_ball()

    def test_both_contacts_steer_left(self):
        # Physically unreachable with the current arena geometry, but the
        # table defines a deterministic outcome that must not corrupt state.
        self.h.set_ball_dx(DIR_RIGHT)
        self.h.set_collisions(ball_p0=True, ball_p1=True)
        self.h.run_frame()
        self.assertEqual(self.h.ball_dx(), DIR_LEFT,
                         "when both contacts are recorded, P1 wins (DIR_LEFT)")


class TestNoContact(unittest.TestCase):
    def setUp(self):
        self.h = ReboundHarness()
        self.h.boot_sync()
        self.h.park_ball()

    def test_no_contact_keeps_direction_right(self):
        self.h.set_ball_dx(DIR_RIGHT)
        self.h.run_frame()
        self.assertEqual(self.h.ball_dx(), DIR_RIGHT,
                         "without a contact the rebound must not change dx")

    def test_no_contact_keeps_direction_left(self):
        self.h.set_ball_dx(DIR_LEFT)
        self.h.run_frame()
        self.assertEqual(self.h.ball_dx(), DIR_LEFT,
                         "without a contact the rebound must not change dx")


class TestContactSideEffects(unittest.TestCase):
    """A ball contact is a rebound ONLY: no damage, no missile change, no
    hit_flags change."""

    def setUp(self):
        self.h = ReboundHarness()
        self.h.boot_sync()
        self.h.park_ball()

    def test_contact_does_not_damage_players(self):
        self.h.set_ball_dx(DIR_RIGHT)
        self.h.set_collisions(ball_p0=True, ball_p1=True)
        self.h.run_frame()
        self.assertEqual(self.h.cpu.ram[self.h._ram("p0_hp")], START_HP,
                         "ball contact must not cost P0 HP")
        self.assertEqual(self.h.cpu.ram[self.h._ram("p1_hp")], START_HP,
                         "ball contact must not cost P1 HP")

    def test_contact_does_not_set_hit_flags(self):
        self.h.set_collisions(ball_p0=True, ball_p1=True)
        self.h.run_frame()
        self.assertEqual(self.h.state()["hit_flags"], 0,
                         "ball contact is not a missile hit")

    def test_contact_does_not_touch_flying_missiles(self):
        self.h.fire_m0()
        self.h.fire_m1()
        self.h.set_collisions(ball_p0=True, ball_p1=True)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["m0"], 1, "a ball contact must not deactivate M0")
        self.assertEqual(s["m1"], 1, "a ball contact must not deactivate M1")

    def test_contact_does_not_remove_the_ball(self):
        self.h.set_collisions(ball_p0=True)
        self.h.run_frame()
        self.assertTrue(self.h.state()["ball_y"] >= 0,
                        "the ball object is never removed by a contact")


class TestConsecutiveContacts(unittest.TestCase):
    """Repeated per-frame contacts must not corrupt state: the ball is
    re-steered the same way every frame and the direction stays coherent."""

    def setUp(self):
        self.h = ReboundHarness()
        self.h.boot_sync()
        self.h.park_ball()

    def test_multi_frame_p0_contact_stays_right(self):
        self.h.set_ball_dx(DIR_LEFT)
        for _ in range(8):
            self.h.set_collisions(ball_p0=True)
            self.h.run_frame()
            self.assertEqual(self.h.ball_dx(), DIR_RIGHT,
                             "every contact frame must re-steer the ball right")
            self.assertEqual(
                self.h.cpu.ram[self.h._ram("p0_hp")], START_HP,
                "consecutive contacts must never damage P0")

    def test_contact_ends_cleanly(self):
        self.h.set_ball_dx(DIR_LEFT)
        for _ in range(4):
            self.h.set_collisions(ball_p0=True)
            self.h.run_frame()
        self.assertEqual(self.h.ball_dx(), DIR_RIGHT)
        # overlap ends: the rebound must stop steering (dx keeps DIR_RIGHT
        # from the last contact; it is only changed by a NEW contact)
        self.h.set_collisions()            # no contact this frame
        self.h.run_frame()
        self.assertEqual(self.h.ball_dx(), DIR_RIGHT,
                         "after the overlap ends, dx must keep the last rebound")
        self.assertEqual(self.h.state()["ball_contact_flags"], 0,
                         "the contact record must clear when the overlap ends")


class TestMissileCollisionStillWorks(unittest.TestCase):
    """Round 4/5 behavior must survive the new rebound pass: missile hits are
    still processed in the same overscan, right after the ball rebound."""

    def setUp(self):
        self.h = ReboundHarness()
        self.h.boot_sync()
        self.h.park_ball()
        self.h.fire_m0()

    def test_missile_hit_and_ball_contact_same_frame(self):
        self.h.set_ball_dx(DIR_LEFT)
        self.h.set_collisions(m0_p1=True, ball_p0=True)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["hit_flags"], HIT_P1,
                         "M0 -> P1 must still set the P1 hit flag")
        self.assertEqual(s["m0"], 0, "M0 must still deactivate on its hit")
        self.assertEqual(self.h.ball_dx(), DIR_RIGHT,
                         "the ball rebound must still be applied")
        self.assertEqual(self.h.cpu.ram[self.h._ram("p1_hp")], START_HP - 1,
                         "P1 must lose the HP from the missile hit")


class TestReboundFrameTiming(unittest.TestCase):
    """The fixed-cost rebound must not disturb the 262-scanline frame."""

    @classmethod
    def setUpClass(cls):
        require_build()
        cls.rom = load_rom(ROM_PATH)
        from common import parse_symbols
        cls.sym = parse_symbols()
        cls.sof = cls.sym["StartOfFrame"]

    def _frame_cycles(self, h):
        start = h.cpu.cycles
        at_sof = h.cpu.pc == self.sof
        count = 0
        while count < 2:
            h.cpu.step()
            if h.cpu.pc == self.sof:
                count += 1
                if (at_sof and count == 1) or count == 2:
                    return h.cpu.cycles - start
        raise AssertionError("frame did not terminate")

    def test_contact_stress_keeps_262_scanlines(self):
        h = ReboundHarness()
        h.boot_sync()
        h.park_ball()
        h.fire_m0()
        h.fire_m1()
        for i in range(100):
            press = (i % 2 == 0)
            h.set_buttons(press, not press)
            h.set_collisions(ball_p0=True, ball_p1=True)
            h.set_ball_dx(DIR_RIGHT if press else DIR_LEFT)
            h.cpu.ram[h._ram("p0_hp")] = 3
            h.cpu.ram[h._ram("p1_hp")] = 3
            cycles = self._frame_cycles(h)
            self.assertEqual(cycles, 19912,
                             f"frame {i} ran {cycles} cycles "
                             f"({cycles / 76:.0f} scanlines), expected 262")


if __name__ == "__main__":
    unittest.main()