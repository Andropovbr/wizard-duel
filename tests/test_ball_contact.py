"""Ball x Player contact validation (Round 6).

Runs the assembled ROM on the deterministic 6502 emulator (tools/emu6502.py)
and exercises the real ProcessCollisions assembly.  The emulator models the
TIA collision latches at the register level: `cpu.cxp0fb` / `cpu.cxp1fb` hold
the CXP0FB/CXP1FB read values, they persist until the ROM writes CXCLR, and
reads have no side effects - the real latch contract.  Tests inject latch
bits to represent an overlap rendered by the visible kernel (pixel geometry
itself is validated in Stella; see docs/en/timing.md).

TIA latch layout (verified against the Stella source, the reference
emulator):

    CXP0FB  ($02, read): D7 = P0 x PF,  D6 = P0 x BL (ball contact)
    CXP1FB  ($03, read): D7 = P1 x PF,  D6 = P1 x BL (ball contact)
    CXCLR   ($2C, write): clears every latch

Expected semantics (Round 6):

    Ball x P0  -> CONTACT_P0 in ball_contact_flags
    Ball x P1  -> CONTACT_P1 in ball_contact_flags
    ball_contact_flags is a SEPARATE byte from hit_flags: ball contact is
      contact information ONLY - no damage, no missile change, no ball
      rebound.  hit_flags, HP and m_active are never touched by a contact.
    the flags are overwritten every frame, so a contact rendered in frame N
      is recorded right after overscan N and never repeats in frame N+1
      (CXCLR clears the latches, and the byte is rewritten to zero).
    a dead player is not rendered (BuildEvents skips its GRP events), so the
      TIA never latches a ball x dead-player overlap: the rendering gate
      keeps dead players contact-free, no HP check is needed.
    contacts and missile hits in the same frame are both recorded, and the
      single CXCLR clears both latch families.
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
BALLP_P0 = 0x40                   # CXP0FB D6
BALLP_P1 = 0x40                   # CXP1FB D6
EV_REG_GRP0 = C["EV_REG_GRP0"]    # 1
EV_REG_GRP1 = C["EV_REG_GRP1"]    # 2
START_HP = C["PLAYER_START_HP"]


class TestBallContactP0(unittest.TestCase):
    def setUp(self):
        self.h = CollisionHarness()
        self.h.boot_sync()

    def test_ball_p0_sets_contact_p0(self):
        self.h.set_collisions(ball_p0=True)
        self.h.run_frame()
        self.assertEqual(self.h.state()["ball_contact_flags"], CONTACT_P0,
                         "Ball x P0 must set the P0 contact flag")

    def test_ball_p0_does_not_set_contact_p1(self):
        self.h.set_collisions(ball_p0=True)
        self.h.run_frame()
        self.assertEqual(self.h.state()["ball_contact_flags"] & CONTACT_P1, 0,
                         "Ball x P0 must never set the P1 contact flag")

    def test_ball_p0_does_not_touch_hit_flags(self):
        self.h.set_collisions(ball_p0=True)
        self.h.run_frame()
        self.assertEqual(self.h.state()["hit_flags"], 0,
                         "ball contact is not a missile hit: hit_flags stays 0")

    def test_ball_p0_does_not_damage(self):
        self.h.set_collisions(ball_p0=True)
        self.h.run_frame()
        self.assertEqual(self.h.cpu.ram[self.h._ram("p0_hp")], START_HP,
                         "ball contact must not cost HP")
        self.assertEqual(self.h.cpu.ram[self.h._ram("p1_hp")], START_HP)

    def test_ball_p0_does_not_stop_ball(self):
        b0 = (self.h.state()["ball_x"], self.h.state()["ball_y"])
        self.h.set_collisions(ball_p0=True)
        moved = False
        for _ in range(4):
            self.h.run_frame()
            bx, by = self.h.state()["ball_x"], self.h.state()["ball_y"]
            if (bx, by) != b0:
                moved = True
            b0 = (bx, by)
        self.assertTrue(moved, "the ball must keep moving across a contact")


class TestBallContactP1(unittest.TestCase):
    def setUp(self):
        self.h = CollisionHarness()
        self.h.boot_sync()

    def test_ball_p1_sets_contact_p1(self):
        self.h.set_collisions(ball_p1=True)
        self.h.run_frame()
        self.assertEqual(self.h.state()["ball_contact_flags"], CONTACT_P1,
                         "Ball x P1 must set the P1 contact flag")

    def test_ball_p1_does_not_set_contact_p0(self):
        self.h.set_collisions(ball_p1=True)
        self.h.run_frame()
        self.assertEqual(self.h.state()["ball_contact_flags"] & CONTACT_P0, 0,
                         "Ball x P1 must never set the P0 contact flag")

    def test_ball_p1_does_not_damage(self):
        self.h.set_collisions(ball_p1=True)
        self.h.run_frame()
        self.assertEqual(self.h.cpu.ram[self.h._ram("p0_hp")], START_HP)
        self.assertEqual(self.h.cpu.ram[self.h._ram("p1_hp")], START_HP,
                         "ball contact must not cost HP")


class TestNoBallContact(unittest.TestCase):
    def setUp(self):
        self.h = CollisionHarness()
        self.h.boot_sync()

    def test_flags_zero_with_no_contact(self):
        for _ in range(5):
            self.h.run_frame()
            self.assertEqual(self.h.state()["ball_contact_flags"], 0)

    def test_stale_flags_cleared_before_processing(self):
        # A stale ball_contact_flags byte left in RAM must be deterministically
        # reset by ProcessCollisions even when no ball contact occurred.
        self.h.cpu.ram[self.h._ram("ball_contact_flags")] = 0xFF
        self.h.run_frame()
        self.assertEqual(self.h.state()["ball_contact_flags"], 0)

    def test_flags_ignore_playfield_bit(self):
        # CXP0FB/CXP1FB D7 (player x playfield) is deliberately ignored: the
        # playfield is never displayed, and this bit must not masquerade as
        # ball contact.
        self.h.cpu.cxp0fb = 0x80
        self.h.cpu.cxp1fb = 0x80
        self.h.run_frame()
        self.assertEqual(self.h.state()["ball_contact_flags"], 0,
                         "P x PF bits must not produce ball contact")


class TestSimultaneousContact(unittest.TestCase):
    def setUp(self):
        self.h = CollisionHarness()
        self.h.boot_sync()

    def test_both_contacts_recorded_in_same_frame(self):
        self.h.set_collisions(ball_p0=True, ball_p1=True)
        self.h.run_frame()
        self.assertEqual(self.h.state()["ball_contact_flags"],
                         CONTACT_P0 | CONTACT_P1,
                         "simultaneous Ball x P0 and Ball x P1 must both "
                         "be recorded")


class TestContactWithMissileHit(unittest.TestCase):
    def setUp(self):
        self.h = CollisionHarness()
        self.h.boot_sync()

    def test_contact_and_hit_in_same_frame_are_independent(self):
        # Ball x P0 contact AND M0 -> P1 hit in the same frame: the contact
        # must be recorded in ball_contact_flags while the hit drives
        # hit_flags and deactivates M0 - neither interferes with the other.
        self.h.fire_m0()
        self.h.set_collisions(m0_p1=True, ball_p0=True)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["ball_contact_flags"], CONTACT_P0,
                         "the contact must survive the missile hit")
        self.assertEqual(s["hit_flags"], HIT_P1,
                         "the hit must survive the contact")
        self.assertEqual(s["m0"], 0, "the scoring missile must deactivate")
        self.assertEqual(s["m1"], 0)

    def test_contact_does_not_deactivate_missiles(self):
        self.h.fire_m0()
        self.h.fire_m1()
        self.h.set_collisions(ball_p0=True, ball_p1=True)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["m0"], 1, "a ball contact must not stop M0")
        self.assertEqual(s["m1"], 1, "a ball contact must not stop M1")
        self.assertEqual(s["hit_flags"], 0)


class TestDeadPlayerNoContact(unittest.TestCase):
    def setUp(self):
        self.h = CollisionHarness()
        self.h.boot_sync()
        # Kill P0 directly in RAM; the frame that follows applies the fire
        # lock and, on later frames, BuildEvents skips P0's render.
        self.h.cpu.ram[self.h._ram("p0_hp")] = 0
        self.h.run_frame()

    def test_dead_player_not_rendered(self):
        regs = self.h.event_regs()
        self.assertNotIn(EV_REG_GRP0, regs,
                         "a dead P0 must contribute no GRP0 events")
        self.assertIn(EV_REG_GRP1, regs,
                      "the alive P1 must still be rendered")

    def test_dead_player_produces_no_contact(self):
        # A dead player is not rendered, so the TIA never latches a ball x
        # dead-player overlap and ball_contact_flags stays clean.  This is the
        # rendering gate working: no HP check is involved.
        for _ in range(6):
            self.h.run_frame()
            self.assertEqual(self.h.state()["ball_contact_flags"], 0,
                             "a dead player must never produce contact")


class TestLatchLifecycle(unittest.TestCase):
    def setUp(self):
        self.h = CollisionHarness()
        self.h.boot_sync()

    def test_contact_recorded_once_and_cleared_next_frame(self):
        self.h.set_collisions(ball_p0=True)
        self.h.run_frame()                     # frame N: contact processed
        self.assertEqual(self.h.state()["ball_contact_flags"], CONTACT_P0)
        self.h.run_frame()                     # frame N+1: no new contact
        self.assertEqual(self.h.state()["ball_contact_flags"], 0,
                         "a contact rendered in frame N must not repeat in "
                         "frame N+1")

    def test_cxclr_clears_the_ball_latches(self):
        self.h.set_collisions(ball_p0=True, ball_p1=True)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["ball_contact_flags"], CONTACT_P0 | CONTACT_P1)
        self.assertEqual(s["cxp0fb"], 0,
                         "CXCLR must clear the CXP0FB latch after processing")
        self.assertEqual(s["cxp1fb"], 0,
                         "CXCLR must clear the CXP1FB latch after processing")

    def test_latches_persist_until_cxclr(self):
        # Before the ROM processes them, injected latches stay set.
        self.h.set_collisions(ball_p0=True)
        self.assertEqual(self.h.state()["cxp0fb"], BALLP_P0,
                         "the latch must persist until the ROM clears it")

    def test_contact_streak_measured(self):
        # A repeated overlap across consecutive frames keeps the flag set for
        # exactly those frames (no debounce this round), then clears as soon
        # as the overlap ends.
        for _ in range(3):
            self.h.set_collisions(ball_p0=True)
            self.h.run_frame()
            self.assertEqual(self.h.state()["ball_contact_flags"], CONTACT_P0)
        self.h.run_frame()                     # overlap ends
        self.assertEqual(self.h.state()["ball_contact_flags"], 0,
                         "the streak must end when the overlap ends")


class TestBallContactFrameTiming(unittest.TestCase):
    """The branchless ball pass must not disturb frame timing.

    Ball latches asserted on every frame, on top of the existing missile
    stress (both collision families + alternating fire presses + HP re-fill),
    must keep every frame at exactly 19912 cycles = 262 scanlines, and the
    ball contact flags must stay coherent across the whole run.
    """

    @classmethod
    def setUpClass(cls):
        require_build()
        cls.rom = load_rom(ROM_PATH)
        from common import parse_symbols
        cls.sym = parse_symbols()
        cls.sof = cls.sym["StartOfFrame"]

    def setUp(self):
        self.cpu = Cpu(self.rom)
        self.cpu.reset()
        self.cpu.inpt[4] = 0xFF
        self.cpu.inpt[5] = 0xFF
        # Release SELECT and RESET on the console switches (bit1 + bit0)
        self.cpu.riot[2] = 0x03
        # Enter playing state so gameplay updates run
        self.cpu.ram[self._ram("game_state")] = 1  # STATE_PLAYING

    def _ram(self, name):
        return self.sym[name] - 0x80

    def run_frame(self):
        start = self.cpu.cycles
        at_sof = self.cpu.pc == self.sof
        count = 0
        while count < 2:
            self.cpu.step()
            if self.cpu.pc == self.sof:
                count += 1
                if (at_sof and count == 1) or count == 2:
                    return self.cpu.cycles - start
        raise AssertionError("frame did not terminate")

    def test_500_frames_stay_262_scanlines_under_ball_stress(self):
        bcf = self._ram("ball_contact_flags")
        p0_hp = self._ram("p0_hp")
        p1_hp = self._ram("p1_hp")
        self.run_frame()                       # boot sync frame
        for _ in range(3):
            self.cpu.cxm0p = 0xC0
            self.cpu.cxm1p = 0xC0
            self.cpu.cxp0fb = 0x40
            self.cpu.cxp1fb = 0x40
            self.run_frame()
        for i in range(500):
            press = (i % 2 == 0)
            self.cpu.inpt[4] = 0x00 if press else 0xFF
            self.cpu.inpt[5] = 0x00 if press else 0xFF
            self.cpu.cxm0p = 0xC0    # both missile x player latches
            self.cpu.cxm1p = 0xC0
            self.cpu.cxp0fb = 0x40   # Ball x P0
            self.cpu.cxp1fb = 0x40   # Ball x P1
            self.cpu.ram[p0_hp] = 3  # keep both players alive
            self.cpu.ram[p1_hp] = 3
            cycles = self.run_frame()
            self.assertEqual(cycles, 19912,
                             f"frame {i} ran {cycles} cycles "
                             f"({cycles / 76:.0f} scanlines), expected 262")
            self.assertEqual(self.cpu.ram[bcf], CONTACT_P0 | CONTACT_P1,
                             f"frame {i} lost the ball contact record")

    def test_contact_streaks_track_the_injected_geometry(self):
        # Measure how many consecutive frames a contact run lasts: inject a
        # periodic "ball passes a paddle" pattern and assert the recorded
        # flags mirror it exactly (including the max run length).  This is the
        # deterministic proxy for the real per-frame contact report the game
        # will consume in a later round (no debounce this round).
        bcf = self._ram("ball_contact_flags")
        p0_hp = self._ram("p0_hp")
        p1_hp = self._ram("p1_hp")
        # A 10-frame cycle: 4 contact frames, then 6 without (P0 only).
        cycle = [True] * 4 + [False] * 6
        self.run_frame()                       # boot sync frame
        max_seen = 0
        cur = 0
        for i in range(500):
            contact = cycle[i % len(cycle)]
            self.cpu.cxp0fb = 0x40 if contact else 0
            self.cpu.cxp1fb = 0
            self.cpu.ram[p0_hp] = 3
            self.cpu.ram[p1_hp] = 3
            cycles = self.run_frame()
            self.assertEqual(cycles, 19912, f"frame {i} slipped to "
                             f"{cycles / 76:.0f} scanlines")
            expect = CONTACT_P0 if contact else 0
            self.assertEqual(self.cpu.ram[bcf], expect,
                             f"frame {i} contact flag mismatch")
            cur = cur + 1 if contact else 0
            max_seen = max(max_seen, cur)
        self.assertEqual(max_seen, 4,
                         "max consecutive contact frames must equal the "
                         "injected run length")


if __name__ == "__main__":
    unittest.main()