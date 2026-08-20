"""Player HP and death validation (Round 5).

Runs the assembled ROM on the deterministic 6502 emulator (tools/emu6502.py)
and exercises the real ProcessHitEffects assembly (plus the BuildEvents HP
gate and the dead-player fire lock).

Round 5 semantics:

    each player starts with PLAYER_START_HP hit points
    HIT_P0 -> one HP from p0_hp, HIT_P1 -> one HP from p1_hp
    a hit on an already-dead player is ignored (HP never goes below 0)
    a player at 0 HP is dead:
        no longer rendered (BuildEvents skips its GRP events)
        can no longer fire (its FIRE bit in fire_prev is forced to 1 every
            overscan, so UpdateMissiles never sees a rising edge)
        a missile already flying survives the owner's death
    the two players' HP are independent

hit_flags is read but NOT cleared by ProcessHitEffects (ProcessCollisions
overwrites it every frame), so each recorded hit is consumed exactly once.
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
START_HP = C["PLAYER_START_HP"]
M0P_P1 = 0x80                 # CXM0P D7
M1P_P0 = 0x80                 # CXM1P D7
EV_REG_GRP0 = C["EV_REG_GRP0"]
EV_REG_GRP1 = C["EV_REG_GRP1"]


def hit_p1(h, times):
    """M0 hits P1 `times` times, re-firing between hits."""
    for _ in range(times):
        h.set_buttons(False, False)
        h.run_frame()                   # release so the next press is an edge
        h.fire_m0()                     # press -> M0 spawns
        h.set_collisions(m0_p1=True)
        h.run_frame()                   # the hit is processed


def hit_p0(h, times):
    """M1 hits P0 `times` times, re-firing between hits."""
    for _ in range(times):
        h.set_buttons(False, False)
        h.run_frame()                   # release so the next press is an edge
        h.fire_m1()                     # press -> M1 spawns
        h.set_collisions(m1_p0=True)
        h.run_frame()                   # the hit is processed


class TestInitialHp(unittest.TestCase):
    def setUp(self):
        self.h = CollisionHarness()
        self.h.boot_sync()

    def test_players_start_with_full_hp(self):
        self.assertEqual(self.h.cpu.ram[self.h._ram("p0_hp")], START_HP)
        self.assertEqual(self.h.cpu.ram[self.h._ram("p1_hp")], START_HP)


class TestDamage(unittest.TestCase):
    def setUp(self):
        self.h = CollisionHarness()
        self.h.boot_sync()

    def hp(self, player):
        return self.h.cpu.ram[self.h._ram(player)]

    def test_m0_hit_reduces_p1_hp_only(self):
        self.h.fire_m0()
        self.h.set_collisions(m0_p1=True)
        self.h.run_frame()
        self.assertEqual(self.hp("p1_hp"), START_HP - 1)
        self.assertEqual(self.hp("p0_hp"), START_HP,
                         "P1 taking a hit must not touch P0's HP")

    def test_m1_hit_reduces_p0_hp_only(self):
        self.h.fire_m1()
        self.h.set_collisions(m1_p0=True)
        self.h.run_frame()
        self.assertEqual(self.hp("p0_hp"), START_HP - 1)
        self.assertEqual(self.hp("p1_hp"), START_HP,
                         "P0 taking a hit must not touch P1's HP")

    def test_simultaneous_hits_reduce_both(self):
        self.h.fire_m0()
        self.h.fire_m1()
        self.h.set_collisions(m0_p1=True, m1_p0=True)
        self.h.run_frame()
        self.assertEqual(self.hp("p0_hp"), START_HP - 1)
        self.assertEqual(self.hp("p1_hp"), START_HP - 1)

    def test_hit_is_consumed_exactly_once(self):
        # A hit rendered in frame N costs one HP; frame N+1 (no new collision)
        # must not cost another, and hit_flags must be back to zero.
        self.h.fire_m0()
        self.h.set_collisions(m0_p1=True)
        self.h.run_frame()
        self.assertEqual(self.hp("p1_hp"), START_HP - 1)
        self.h.run_frame()
        self.assertEqual(self.hp("p1_hp"), START_HP - 1,
                         "a hit must not be applied twice")
        self.assertEqual(self.h.state()["hit_flags"], 0)

    def test_stale_hit_flags_do_not_damage(self):
        # A stale hit_flags byte left in RAM is cleared by ProcessCollisions
        # before ProcessHitEffects reads it, so it must not cost HP.
        self.h.cpu.ram[self.h._ram("hit_flags")] = 0xFF
        self.h.run_frame()
        self.assertEqual(self.hp("p0_hp"), START_HP)
        self.assertEqual(self.hp("p1_hp"), START_HP)


class TestDeathByHits(unittest.TestCase):
    """Repeated real cross-fire hits drive a player from START_HP down to 0."""

    def setUp(self):
        self.h = CollisionHarness()
        self.h.boot_sync()

    def hp(self, player):
        return self.h.cpu.ram[self.h._ram(player)]

    def test_start_plus_n_minus_one_hits_leaves_one_hp(self):
        hit_p1(self.h, START_HP - 1)
        self.assertEqual(self.hp("p1_hp"), 1)

    def test_full_health_is_depleted_by_start_hp_hits(self):
        hit_p1(self.h, START_HP)
        self.assertEqual(self.hp("p1_hp"), 0, "P1 must be dead")

    def test_hp_never_goes_below_zero(self):
        hit_p0(self.h, START_HP)           # kill P0
        self.assertEqual(self.hp("p0_hp"), 0)
        hit_p0(self.h, 3)                  # more hits on the corpse
        self.assertEqual(self.hp("p0_hp"), 0,
                         "a dead player must never lose more HP")

    def test_players_are_independent(self):
        hit_p1(self.h, START_HP)           # kill P1
        self.assertEqual(self.hp("p0_hp"), START_HP,
                         "P1's death must not cost P0 any HP")


class TestDeadPlayerBehavior(unittest.TestCase):
    def setUp(self):
        self.h = CollisionHarness()
        self.h.boot_sync()
        # Kill P0 directly in RAM, then run a frame so ProcessHitEffects
        # applies the fire lock for the frames that follow.
        self.h.cpu.ram[self.h._ram("p0_hp")] = 0
        self.h.run_frame()

    def test_dead_player_not_rendered(self):
        regs = self.h.event_regs()
        self.assertNotIn(EV_REG_GRP0, regs,
                         "a dead P0 must contribute no GRP0 events")
        self.assertIn(EV_REG_GRP1, regs,
                      "the alive P1 must still be rendered")

    def test_dead_player_cannot_fire(self):
        # Release/press cycles after death must never spawn M0: the fire lock
        # forces P0's FIRE bit to "pressed" every overscan, so UpdateMissiles
        # never sees a rising edge.
        self.h.set_buttons(False, False)
        self.h.run_frame()
        for _ in range(6):
            self.h.set_buttons(True, False)   # press P0
            self.h.run_frame()
            self.assertEqual(self.h.state()["m0"], 0,
                             "a dead P0 must never spawn M0")
            self.h.set_buttons(False, False)  # release
            self.h.run_frame()

    def test_alive_player_can_fire(self):
        # While P0 is dead, P1 must fire normally (players are independent).
        self.h.set_buttons(False, False)
        self.h.run_frame()
        self.h.set_buttons(False, True)
        self.h.run_frame()
        self.assertEqual(self.h.state()["m1"], 1,
                         "the alive P1 must still fire")

    def test_active_missile_survives_owner_death(self):
        # Kill P0 with real M1 hits while M0 (P0's missile) is flying: M0 must
        # keep flying after its owner dies and keep moving across frames.
        h = CollisionHarness()
        h.boot_sync()
        h.fire_m0()                       # M0 spawns (owner P0)
        self.assertEqual(h.state()["m0"], 1)
        hit_p0(h, START_HP)               # kill P0 via M1 hits
        self.assertEqual(h.cpu.ram[h._ram("p0_hp")], 0)
        self.assertEqual(h.state()["m0"], 1,
                         "M0 must survive its owner P0's death")
        x0 = h.state()["m0_x"]
        for _ in range(4):
            h.run_frame()
            self.assertGreater(h.state()["m0_x"], x0,
                               "a surviving missile must keep moving")
            x0 = h.state()["m0_x"]


if __name__ == "__main__":
    unittest.main()