"""Assembly/ROM validation: symbols, addresses, paddle rendering, page alignment."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from common import (ROM_ORIGIN, ROM_PATH, parse_listing, parse_symbols,
                    require_build)
from test_timing import read_constants

PLAYER_HEIGHT = 12


class TestSymbols(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_build()
        cls.sym = parse_symbols()

    def test_required_symbols_exist(self):
        for name in ("Reset", "StartOfFrame", "WaitVBlank", "KernelLoop",
                     "OverscanWait", "UpdatePlayers", "UpdateBall",
                     "PositionPlayers", "PositionBall", "PosObject",
                     "fineAdjustTable", "fineAdjustBegin", "P0Y", "P1Y",
                     "joystate", "ball_x", "ball_y", "ball_dx", "ball_dy"):
            self.assertIn(name, self.sym, f"missing symbol {name}")

    def test_reset_at_rom_origin(self):
        self.assertEqual(self.sym["Reset"], ROM_ORIGIN)

    def test_ram_symbols_in_riot_ram(self):
        for name in ("P0Y", "P1Y", "joystate",
                     "ball_x", "ball_y", "ball_dx", "ball_dy"):
            self.assertGreaterEqual(self.sym[name], 0x80)
            self.assertLessEqual(self.sym[name], 0xFF)

    def test_fine_adjust_table_page_aligned(self):
        self.assertEqual(self.sym["fineAdjustBegin"] & 0xFF, 0)

    def test_ram_symbols_distinct(self):
        self.assertEqual(len({self.sym["P0Y"], self.sym["P1Y"],
                              self.sym["joystate"], self.sym["ball_x"],
                              self.sym["ball_y"], self.sym["ball_dx"],
                              self.sym["ball_dy"]}), 7)

    def test_kernel_loop_inside_rom(self):
        self.assertGreaterEqual(self.sym["KernelLoop"], ROM_ORIGIN)


class TestRomLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_build()
        cls.rom = ROM_PATH.read_bytes()
        cls.rows = parse_listing()
        cls.sym = parse_symbols()

    def addr(self, a):
        return self.rom[a - ROM_ORIGIN]

    def test_paddle_bits_constant_is_solid_bar(self):
        # Round 2 renders both players as Pong-style vertical paddles:
        # PLAYER_HEIGHT identical solid rows of a 4-pixel bar, encoded as the
        # PADDLE_BITS constant used by the branchless kernel rectangles.
        self.assertEqual(read_constants().get("PADDLE_BITS"), 0x3C)

    def test_kernel_uses_branchless_paddle_pattern(self):
        # Both players render as a constant PADDLE_BITS rectangle: the kernel
        # body contains exactly two AND #PADDLE_BITS (29 3C), one per player.
        start = self.sym["KernelLoop"]
        end = self.sym["OverscanWait"]
        kernel = self.rom[start - ROM_ORIGIN:end - ROM_ORIGIN]
        self.assertEqual(kernel.count(bytes([0x29, 0x3C])), 2,
                         "kernel must render both paddles with AND #PADDLE_BITS")

    def test_fine_adjust_table_15_entries(self):
        base = self.sym["fineAdjustBegin"]
        self.assertEqual(self.addr(base), 0x70)   # left 7
        self.assertEqual(self.addr(base + 7), 0x00)  # no movement
        self.assertEqual(self.addr(base + 14), 0x90)  # right 7

    def test_no_bankswitch_padding_between_code_and_vectors(self):
        # The fineAdjustBegin page must be inside the 4 KiB image.
        self.assertGreaterEqual(self.sym["fineAdjustBegin"], ROM_ORIGIN)
        self.assertLessEqual(self.sym["fineAdjustBegin"] + 0xFF, 0xFFFF)


if __name__ == "__main__":
    unittest.main()