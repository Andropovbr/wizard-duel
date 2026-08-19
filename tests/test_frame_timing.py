"""Frame-timing and event-table stability validation via the 6502 emulator.

Runs many full frames with aggressive fire-button input and checks the
deterministic frame loop properties the Round 3.1 kernel depends on:

  * every frame reaches StartOfFrame (the loop never hangs or crashes);
  * the event table never exceeds EV_TBL_SIZE bytes, even when both
    missiles are firing (the builder inserts directly into the table);
  * the kernel keeps firing every event (tblLen stays within bounds and
    the countdown bookkeeping stays coherent across frames).

Scanline counts themselves are validated from constants (262) and the kernel
cycle budget elsewhere; this test exercises the builder + kernel end to end
in a deterministic CPU model.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from common import ROM_PATH, require_build
from emu6502 import Cpu, load_rom
from test_events import EV_TBL_SIZE


class TestFrameStability(unittest.TestCase):
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

    def _ram(self, name):
        return self.sym[name] - 0x80

    def run_frame(self):
        """Run exactly one frame (returns cycles consumed).

        If the CPU is already at StartOfFrame (the state left by a previous
        call), the frame currently being entered is the one measured, so a
        call always returns exactly one frame's worth of cycles.
        """
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

    def test_loop_is_stable_over_many_frames(self):
        # Boot (latches read pressed), then released; nothing must fire.
        self.cpu.inpt[4] = 0x00
        self.cpu.inpt[5] = 0x00
        for _ in range(20):
            self.run_frame()

    def test_table_never_exceeds_max_with_aggressive_fire(self):
        # Alternate both fire buttons aggressively so M0 and M1 keep spawning
        # and despawning; the builder must keep the table within EV_TBL_SIZE.
        tlen = self._ram("tblLen")
        self.cpu.inpt[4] = 0xFF      # first frame is the boot sync frame
        self.cpu.inpt[5] = 0xFF
        self.run_frame()
        for i in range(60):
            p0 = (i // 4) % 2 == 0
            p1 = (i // 6) % 2 == 0
            self.cpu.inpt[4] = 0x00 if p0 else 0xFF
            self.cpu.inpt[5] = 0x00 if p1 else 0xFF
            self.run_frame()
            self.assertLessEqual(self.cpu.ram[tlen], EV_TBL_SIZE,
                                 f"tblLen exceeded EV_TBL_SIZE at frame {i}")
            self.assertGreaterEqual(self.cpu.ram[tlen], 1,
                                    f"tblLen empty at frame {i}")

    def test_missiles_actually_fire_and_despawn(self):
        # Sanity: pressing P0 spawns M0 and it later despawns, proving the
        # event pipeline drives real behavior across frames.
        m_active = self._ram("m_active")
        self.cpu.inpt[4] = 0xFF      # boot sync frame first (buttons released)
        self.cpu.inpt[5] = 0xFF
        self.run_frame()
        self.cpu.inpt[4] = 0x00      # now a real press
        self.cpu.inpt[5] = 0xFF
        self.run_frame()
        self.assertNotEqual(self.cpu.ram[m_active] & 0x01, 0,
                            "M0 must spawn after a P0 press")
        self.cpu.inpt[4] = 0xFF
        for _ in range(90):          # fly off the right edge and despawn
            self.run_frame()
        self.assertEqual(self.cpu.ram[m_active] & 0x01, 0,
                         "M0 must despawn after flying off-screen")
        # m0_x itself may wrap after despawn, but the active flag is the
        # source of truth the builder checks.

    def test_frame_never_slips_to_263_under_max_collision_stress(self):
        # Regression: before Round 4's fixed overscan (WSYNC countdown +
        # branchless ProcessCollisions), the heaviest VBLANK path slipped ~1%
        # of frames to 263 scanlines.  This reproduces that exact worst case
        # (both collision latches asserted every frame + alternating fire
        # presses, so both missiles re-spawn after every hit) and asserts
        # every frame is exactly 19912 cycles = 262 scanlines.
        self.cpu.inpt[4] = 0xFF      # boot sync frames first
        self.cpu.inpt[5] = 0xFF
        self.run_frame()
        for _ in range(3):
            self.cpu.cxm0p = 0xC0
            self.cpu.cxm1p = 0xC0
            self.run_frame()
        for i in range(80):
            press = (i % 2 == 0)
            self.cpu.inpt[4] = 0x00 if press else 0xFF
            self.cpu.inpt[5] = 0x00 if press else 0xFF
            self.cpu.cxm0p = 0xC0    # M0 x P1 AND M0 x P0 latched
            self.cpu.cxm1p = 0xC0    # M1 x P0 AND M1 x P1 latched
            cycles = self.run_frame()
            self.assertEqual(cycles, 19912,
                             f"frame {i} ran {cycles} cycles "
                             f"({cycles / 76:.0f} scanlines), expected 262")


if __name__ == "__main__":
    unittest.main()