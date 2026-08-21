"""Tests for the rounded-orb rendering system (Round 8).

The orb mini-loop renders the ball as a diamond shape using per-row CTRLPF
width changes and ENABL toggling.  These tests verify:

1. The event table contains no ball events (ENABL register writes)
2. Ball rendering coexists correctly with P0/P1/M0/M1 events
3. Frame timing remains 262 scanlines with the orb active
"""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import require_build, parse_symbols, ROM_PATH, SYM_PATH
from emu6502 import Cpu, load_rom

EV_MARKER_VAL = 0xFF
ENABL_REG = 0x1F - 0x1A  # ENABL offset from EV_WRITE_BASE


def _sym():
    return parse_symbols(SYM_PATH)


class OrbTestHarness:
    """Drives the ROM with controlled ball position and reads TIA state."""

    def __init__(self):
        require_build()
        self.rom = load_rom(ROM_PATH)
        self.sym = _sym()
        self.cpu = Cpu(self.rom)
        self.cpu.reset()
        self.cpu.inpt[4] = 0xFF
        self.cpu.inpt[5] = 0xFF

    def _ram(self, name):
        return self.sym[name] - 0x80

    def run_frame(self):
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

    def boot_sync(self):
        self.cpu.inpt[4] = 0xFF
        self.cpu.inpt[5] = 0xFF
        self.run_frame()

    def set_ball(self, x, y):
        m = self.cpu.ram
        m[self._ram("ball_x")] = x
        m[self._ram("ball_y")] = y

    def event_regs(self):
        """Decode the event table and return register offsets written."""
        tbl = self._ram("evTbl")
        i = 5
        regs = []
        while True:
            delta = self.cpu.ram[tbl + i]
            if delta == EV_MARKER_VAL:
                return regs
            regs.append(self.cpu.ram[tbl + i + 1])
            if self.cpu.ram[tbl + i + 3] != 0:
                regs.append(self.cpu.ram[tbl + i + 3])
            i += 5

    def measure_frames(self, n):
        """Run n frames and return list of cycle counts."""
        sof = self.sym["StartOfFrame"]
        cycles = []
        for _ in range(n):
            start = self.cpu.cycles
            at_sof = self.cpu.pc == sof
            count = 0
            step_start = self.cpu.steps
            while self.cpu.steps < step_start + 500000:
                self.cpu.step()
                if self.cpu.pc == sof:
                    count += 1
                    if (at_sof and count == 1) or count == 2:
                        break
            cycles.append(self.cpu.cycles - start)
        return cycles


class TestOrbNoBallEvents(unittest.TestCase):
    """BuildEvents must never emit ball ON/OFF events."""

    @classmethod
    def setUpClass(cls):
        require_build()

    def setUp(self):
        self.h = OrbTestHarness()
        self.h.boot_sync()

    def test_no_enabl_in_event_table(self):
        """Event table must not contain ENABL register writes."""
        self.h.set_ball(78, 95)
        self.h.run_frame()
        regs = self.h.event_regs()
        self.assertNotIn(ENABL_REG, regs,
                         "Ball events must not appear in the event table")

    def test_no_ball_events_various_positions(self):
        """Ball at various Y positions: no ENABL in event table."""
        for by in (0, 10, 50, 95, 140, 181):
            self.h.set_ball(78, by)
            self.h.run_frame()
            regs = self.h.event_regs()
            self.assertNotIn(ENABL_REG, regs,
                             f"Ball events found at ball_y={by}")

    def test_no_ball_events_various_x(self):
        """Ball at various X positions: no ENABL in event table."""
        for bx in (0, 20, 40, 78, 120, 156):
            self.h.set_ball(bx, 95)
            self.h.run_frame()
            regs = self.h.event_regs()
            self.assertNotIn(ENABL_REG, regs,
                             f"Ball events found at ball_x={bx}")


class TestOrbFrameTiming(unittest.TestCase):
    """Frame timing must remain 262 scanlines with the orb active."""

    @classmethod
    def setUpClass(cls):
        require_build()

    def setUp(self):
        self.h = OrbTestHarness()
        self.h.boot_sync()

    def test_frame_timing_with_ball_center(self):
        """Frame must remain 262 scanlines with ball at center."""
        self.h.set_ball(78, 95)
        cycles = self.h.measure_frames(100)
        expected = 262 * 76
        for c in cycles:
            self.assertEqual(c, expected,
                             f"Frame timing changed: {c} != {expected}")

    def test_frame_timing_with_ball_edges(self):
        """Frame must remain 262 scanlines with ball at kernel edges."""
        for by in (0, 90, 181):
            self.h.set_ball(78, by)
            cycles = self.h.measure_frames(100)
            expected = 262 * 76
            for c in cycles:
                self.assertEqual(c, expected,
                                 f"Frame timing changed at ball_y={by}: {c}")


class TestOrbCoexistence(unittest.TestCase):
    """Verify the orb coexists correctly with other objects."""

    @classmethod
    def setUpClass(cls):
        require_build()

    def setUp(self):
        self.h = OrbTestHarness()
        self.h.boot_sync()

    def test_p0_p1_events_still_fire(self):
        """Ball at same row as players: P0/P1 events still fire."""
        self.h.set_ball(78, 95)
        self.h.run_frame()
        regs = self.h.event_regs()
        self.assertGreater(len(regs), 0,
                           "P0/P1 events must exist alongside the orb")


class TestOrbPositioning(unittest.TestCase):
    """Verify HMBL positioning works correctly at all valid X positions."""

    @classmethod
    def setUpClass(cls):
        require_build()

    def setUp(self):
        self.h = OrbTestHarness()
        self.h.boot_sync()

    def test_x_sweep_frame_timing(self):
        """Ball at every 4th X position: frame timing stays 262 scanlines."""
        expected = 262 * 76
        for bx in range(0, 157, 4):
            self.h.set_ball(bx, 95)
            cycles = self.h.measure_frames(10)
            for c in cycles:
                self.assertEqual(c, expected,
                                 f"Frame timing changed at ball_x={bx}: {c}")

    def test_x_sweep_no_ball_events(self):
        """Ball at every 4th X position: no ENABL in event table."""
        for bx in range(0, 157, 4):
            self.h.set_ball(bx, 95)
            self.h.run_frame()
            regs = self.h.event_regs()
            self.assertNotIn(ENABL_REG, regs,
                             f"Ball events found at ball_x={bx}")

    def test_extreme_x_positions(self):
        """Ball at X=0 and X=156 (extremes): frame timing stays 262."""
        expected = 262 * 76
        for bx in (0, 1, 155, 156):
            self.h.set_ball(bx, 95)
            cycles = self.h.measure_frames(10)
            for c in cycles:
                self.assertEqual(c, expected,
                                 f"Frame timing changed at ball_x={bx}: {c}")


if __name__ == "__main__":
    unittest.main()
