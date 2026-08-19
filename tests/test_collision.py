"""Missile x Player collision validation (Round 4).

Runs the assembled ROM on the deterministic 6502 emulator (tools/emu6502.py)
and exercises the real ProcessCollisions assembly.  The emulator models the
TIA collision latches at the register level: `cpu.cxm0p` / `cpu.cxm1p` hold
the CXM0P/CXM1P read values, they persist until the ROM writes CXCLR, and
reads have no side effects - the real latch contract.  Tests inject latch
bits to represent an overlap rendered by the visible kernel (pixel geometry
itself is validated in Stella; see docs/en/timing.md).

TIA latch layout (verified against the Stella source, the reference
emulator):

    CXM0P  ($00, read): D7 = M0 x P1,  D6 = M0 x P0
    CXM1P  ($01, read): D7 = M1 x P0,  D6 = M1 x P1
    CXCLR  ($2C, write): clears every latch

Expected semantics (Round 4):

    M0 -> P1  sets HIT_P1 and deactivates M0
    M1 -> P0  sets HIT_P0 and deactivates M1
    own-player latches (M0 x P0, M1 x P1) are ignored
    simultaneous hits are both recorded
    a hit rendered in frame N is never counted again in frame N+2
      (hit_flags is cleared and CXCLR is written every frame)
    the fire input stays one-press-one-shot across a hit
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from common import ROM_PATH, require_build
from emu6502 import Cpu, load_rom
from test_timing import read_constants

C = read_constants()
HIT_P0 = C["HIT_P0"]          # %00000001: P0 hit by M1
HIT_P1 = C["HIT_P1"]          # %00000010: P1 hit by M0
M0P_P1 = 0x80                 # CXM0P D7
M0P_P0 = 0x40                 # CXM0P D6
M1P_P0 = 0x80                 # CXM1P D7
M1P_P1 = 0x40                 # CXM1P D6
EV_REG_ENAM0 = C["EV_REG_ENAM0"]   # 3
EV_REG_ENAM1 = C["EV_REG_ENAM1"]   # 4
EV_REG_GRP0 = C["EV_REG_GRP0"]     # 1
EV_TERMINATOR_DELTA = C["EV_TERMINATOR_DELTA"]   # $FF


def _sym():
    from common import parse_symbols
    return parse_symbols()


class CollisionHarness:
    """Drives the ROM frame-by-frame with controlled fire buttons and TIA
    collision-latch injections."""

    def __init__(self, boot_artifact=True):
        require_build()
        self.rom = load_rom(ROM_PATH)
        self.sym = _sym()
        self.cpu = Cpu(self.rom)
        self.cpu.reset()
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

    def set_collisions(self, m0_p1=False, m0_p0=False, m1_p0=False,
                       m1_p1=False):
        """Set the TIA collision latches as if the visible kernel just
        rendered these overlaps.  Bits OR-accumulate and persist until the
        ROM writes CXCLR (which ProcessCollisions does every frame)."""
        if m0_p1:
            self.cpu.cxm0p |= M0P_P1
        if m0_p0:
            self.cpu.cxm0p |= M0P_P0
        if m1_p0:
            self.cpu.cxm1p |= M1P_P0
        if m1_p1:
            self.cpu.cxm1p |= M1P_P1

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
            "m0": m[self._ram("m_active")] & 0x01,
            "m1": (m[self._ram("m_active")] >> 1) & 0x01,
            "hit_flags": m[self._ram("hit_flags")],
            "m0_x": m[self._ram("m0_x")],
            "m1_x": m[self._ram("m1_x")],
            "ball_x": m[self._ram("ball_x")],
            "ball_y": m[self._ram("ball_y")],
            "cxm0p": self.cpu.cxm0p,
            "cxm1p": self.cpu.cxm1p,
        }

    def event_regs(self):
        """Decode the event table in RAM and return the register indices it
        writes (without the EV_SINGLE_FLAG), one per write."""
        tbl = self._ram("evTbl")
        i = 0
        regs = []
        while True:
            delta = self.cpu.ram[tbl + i]
            if delta == EV_TERMINATOR_DELTA:
                return regs
            reg1 = self.cpu.ram[tbl + i + 1]
            if reg1 & 0x80:              # single entry (3 bytes)
                regs.append(reg1 & 0x7F)
                i += 3
            else:                        # double entry (5 bytes)
                regs.append(reg1)
                regs.append(self.cpu.ram[tbl + i + 3] & 0x7F)
                i += 5

    def boot_sync(self):
        """Run the boot-sync frame and leave both buttons released."""
        self.set_buttons(False, False)
        self.run_frame()

    def fire_m0(self):
        self.set_buttons(True, False)
        self.run_frame()

    def fire_m1(self):
        self.set_buttons(False, True)
        self.run_frame()


class TestM0HitsP1(unittest.TestCase):
    def setUp(self):
        self.h = CollisionHarness()
        self.h.boot_sync()
        self.h.fire_m0()

    def test_m0_p1_sets_hit_p1_and_disables_m0(self):
        self.assertEqual(self.h.state()["m0"], 1, "M0 must be flying")
        self.h.set_collisions(m0_p1=True)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["hit_flags"], HIT_P1,
                         "M0 -> P1 must set the P1 hit flag")
        self.assertEqual(s["m0"], 0, "the missile that scored must deactivate")
        self.assertEqual(s["m1"], 0, "M1 must be unaffected")

    def test_m0_p1_does_not_set_hit_p0(self):
        self.h.set_collisions(m0_p1=True)
        self.h.run_frame()
        self.assertEqual(self.h.state()["hit_flags"] & HIT_P0, 0,
                         "M0 -> P1 must never hit P0")

    def test_m0_p1_disables_only_m0(self):
        # M1 is flying independently; M0 -> P1 must not disable it.
        self.h.set_buttons(False, True)
        self.h.run_frame()
        self.assertEqual(self.h.state()["m1"], 1)
        self.h.set_collisions(m0_p1=True)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["m0"], 0)
        self.assertEqual(s["m1"], 1, "M1 must keep flying after M0 hits P1")


class TestM1HitsP0(unittest.TestCase):
    def setUp(self):
        self.h = CollisionHarness()
        self.h.boot_sync()
        self.h.fire_m1()

    def test_m1_p0_sets_hit_p0_and_disables_m1(self):
        self.assertEqual(self.h.state()["m1"], 1, "M1 must be flying")
        self.h.set_collisions(m1_p0=True)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["hit_flags"], HIT_P0,
                         "M1 -> P0 must set the P0 hit flag")
        self.assertEqual(s["m1"], 0, "the missile that scored must deactivate")
        self.assertEqual(s["m0"], 0, "M0 must be unaffected")

    def test_m1_p0_does_not_set_hit_p1(self):
        self.h.set_collisions(m1_p0=True)
        self.h.run_frame()
        self.assertEqual(self.h.state()["hit_flags"] & HIT_P1, 0,
                         "M1 -> P0 must never hit P1")

    def test_m1_p0_disables_only_m1(self):
        self.h.set_buttons(True, False)
        self.h.run_frame()
        self.assertEqual(self.h.state()["m0"], 1)
        self.h.set_collisions(m1_p0=True)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["m1"], 0)
        self.assertEqual(s["m0"], 1, "M0 must keep flying after M1 hits P0")


class TestNoCollision(unittest.TestCase):
    def setUp(self):
        self.h = CollisionHarness()
        self.h.boot_sync()

    def test_flying_missile_without_latch_no_hit(self):
        self.h.fire_m0()
        for _ in range(5):
            self.h.run_frame()
            s = self.h.state()
            self.assertEqual(s["hit_flags"], 0, "no latch -> no hit")
            self.assertEqual(s["m0"], 1,
                             "missile must keep flying until it reaches P1")

    def test_hit_flags_zero_with_no_input(self):
        for _ in range(5):
            self.h.run_frame()
            self.assertEqual(self.h.state()["hit_flags"], 0)

    def test_hit_flags_cleared_before_processing(self):
        # A stale hit_flags value must be deterministically reset at the start
        # of collision processing even when no collision occurred.
        self.h.cpu.ram[self.h._ram("hit_flags")] = 0xFF
        self.h.run_frame()
        self.assertEqual(self.h.state()["hit_flags"], 0)


class TestOwnPlayerCollisionIgnored(unittest.TestCase):
    def setUp(self):
        self.h = CollisionHarness()
        self.h.boot_sync()
        self.h.fire_m0()
        self.h.fire_m1()

    def test_own_player_latches_produce_no_hit(self):
        # M0 x P0 and M1 x P1 are own-player overlaps: even if the hardware
        # reports them, they must not produce a gameplay hit.
        self.h.set_collisions(m0_p0=True, m1_p1=True)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["hit_flags"], 0,
                         "own-player latches must be ignored")
        self.assertEqual(s["m0"], 1, "M0 must not be disabled by M0 x P0")
        self.assertEqual(s["m1"], 1, "M1 must not be disabled by M1 x P1")

    def test_own_player_latch_with_cross_hit_only_records_cross_hit(self):
        self.h.set_collisions(m0_p1=True, m0_p0=True)
        self.h.run_frame()
        self.assertEqual(self.h.state()["hit_flags"], HIT_P1,
                         "M0 x P0 must not add a P0 hit")

        self.h.fire_m0()          # respawn M0 after the hit above
        self.h.fire_m1()
        self.h.set_collisions(m1_p0=True, m1_p1=True)
        self.h.run_frame()
        self.assertEqual(self.h.state()["hit_flags"], HIT_P0,
                         "M1 x P1 must not add a P1 hit")


class TestSimultaneousHits(unittest.TestCase):
    def setUp(self):
        self.h = CollisionHarness()
        self.h.boot_sync()
        self.h.fire_m0()
        self.h.fire_m1()

    def test_both_hits_recorded_and_both_missiles_disabled(self):
        self.h.set_collisions(m0_p1=True, m1_p0=True)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["hit_flags"], HIT_P0 | HIT_P1,
                         "both hits must be recorded in the same frame")
        self.assertEqual(s["m0"], 0)
        self.assertEqual(s["m1"], 0)

    def test_simultaneous_with_all_four_latches(self):
        # Even with every MxP latch set, only the cross hits count.
        self.h.set_collisions(m0_p1=True, m0_p0=True,
                              m1_p0=True, m1_p1=True)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["hit_flags"], HIT_P0 | HIT_P1)
        self.assertEqual(s["m0"], 0)
        self.assertEqual(s["m1"], 0)


class TestStaleLatch(unittest.TestCase):
    def setUp(self):
        self.h = CollisionHarness()
        self.h.boot_sync()
        self.h.fire_m0()

    def test_hit_not_counted_twice(self):
        self.h.set_collisions(m0_p1=True)
        self.h.run_frame()                     # frame N: the hit is processed
        s = self.h.state()
        self.assertEqual(s["hit_flags"], HIT_P1)
        self.assertEqual(s["m0"], 0)
        # frame N+1: no new collision -> the hit must not repeat
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["hit_flags"], 0,
                         "a hit rendered in frame N must not repeat in N+1")
        self.assertEqual(s["m0"], 0, "the missile must stay deactivated")

    def test_cxclr_clears_the_latches(self):
        self.h.set_collisions(m0_p1=True, m1_p0=True)
        self.h.run_frame()
        s = self.h.state()
        self.assertEqual(s["hit_flags"], HIT_P0 | HIT_P1)
        self.assertEqual(s["cxm0p"], 0,
                         "CXCLR must clear the CXM0P latch after processing")
        self.assertEqual(s["cxm1p"], 0,
                         "CXCLR must clear the CXM1P latch after processing")

    def test_latches_persist_until_cxclr(self):
        # Before the ROM processes them, injected latches stay set.
        self.h.set_collisions(m0_p1=True)
        self.assertEqual(self.h.state()["cxm0p"], M0P_P1,
                         "latch must persist until the ROM clears it")


class TestMissileLifetimeAfterHit(unittest.TestCase):
    def setUp(self):
        self.h = CollisionHarness()
        self.h.boot_sync()
        self.h.fire_m0()

    def test_missile_position_frozen_after_hit(self):
        # The collision is processed at the end of the frame whose kernel
        # rendered the overlap, so the missile moves once more (into the hit)
        # and is then frozen until the player fires again.
        self.h.set_collisions(m0_p1=True)
        self.h.run_frame()
        self.assertEqual(self.h.state()["m0"], 0)
        x_frozen = self.h.state()["m0_x"]
        for _ in range(4):
            self.h.run_frame()
            self.assertEqual(self.h.state()["m0_x"], x_frozen,
                             "a deactivated missile must not keep moving")

    def test_no_missile_events_after_hit(self):
        self.h.set_collisions(m0_p1=True)
        self.h.run_frame()
        self.assertEqual(self.h.state()["m0"], 0)
        self.h.run_frame()
        self.assertNotIn(EV_REG_ENAM0, self.h.event_regs(),
                         "a deactivated missile must contribute no events")
        self.assertIn(EV_REG_GRP0, self.h.event_regs(),
                      "players must still be rendered")


class TestBallUnaffected(unittest.TestCase):
    def test_ball_keeps_moving_across_hits(self):
        h = CollisionHarness()
        h.boot_sync()
        h.fire_m0()
        h.fire_m1()
        b0 = (h.state()["ball_x"], h.state()["ball_y"])
        h.set_collisions(m0_p1=True, m1_p0=True)
        h.run_frame()
        self.assertEqual(h.state()["hit_flags"], HIT_P0 | HIT_P1)
        moved = False
        for _ in range(4):
            h.run_frame()
            bx, by = h.state()["ball_x"], h.state()["ball_y"]
            if (bx, by) != b0:
                moved = True
            b0 = (bx, by)
        self.assertTrue(moved, "the ball must keep moving across hits")


class TestInputSemantics(unittest.TestCase):
    """One-press-one-shot must survive a hit:
    press -> shot -> hit -> hold (no new shot) -> release -> press -> shot."""

    def test_p0_one_press_one_shot_across_hit(self):
        h = CollisionHarness()
        h.boot_sync()
        h.fire_m0()                       # press -> shot
        self.assertEqual(h.state()["m0"], 1)
        h.set_collisions(m0_p1=True)
        h.run_frame()                     # hit processed -> missile gone
        self.assertEqual(h.state()["m0"], 0)
        for _ in range(5):                # hold: no new shot
            h.run_frame()
            s = h.state()
            self.assertEqual(s["m0"], 0, "holding after a hit must not fire")
            self.assertEqual(s["hit_flags"], 0)
        h.set_buttons(False, False)
        h.run_frame()                     # release: rearms only
        self.assertEqual(h.state()["m0"], 0)
        h.set_buttons(True, False)
        h.run_frame()                     # press -> a brand new shot
        self.assertEqual(h.state()["m0"], 1)

    def test_p1_one_press_one_shot_across_hit(self):
        h = CollisionHarness()
        h.boot_sync()
        h.fire_m1()
        self.assertEqual(h.state()["m1"], 1)
        h.set_collisions(m1_p0=True)
        h.run_frame()
        self.assertEqual(h.state()["m1"], 0)
        for _ in range(3):
            h.run_frame()
            self.assertEqual(h.state()["m1"], 0)
        h.set_buttons(False, False)
        h.run_frame()
        h.set_buttons(False, True)
        h.run_frame()
        self.assertEqual(h.state()["m1"], 1)

    def test_repress_after_hit_spawns_immediately(self):
        # The hit is processed BEFORE UpdateMissiles, so once the button is
        # released and pressed again a new missile spawns right away.
        h = CollisionHarness()
        h.boot_sync()
        h.fire_m0()
        h.set_collisions(m0_p1=True)
        h.set_buttons(False, False)       # release
        h.run_frame()                     # hit processed, M0 deactivated
        self.assertEqual(h.state()["m0"], 0)
        h.set_buttons(True, False)        # fresh press
        h.run_frame()
        self.assertEqual(h.state()["m0"], 1,
                         "a fresh press after the hit must spawn a new missile")


if __name__ == "__main__":
    unittest.main()