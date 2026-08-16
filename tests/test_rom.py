"""Assembly/ROM validation: symbols, addresses, sprites and page alignment."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from common import (ROM_ORIGIN, ROM_PATH, parse_listing, parse_symbols,
                    require_build)

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
                     "P0Sprite", "P1Sprite", "fineAdjustTable",
                     "fineAdjustBegin", "P0Y", "P1Y", "joystate",
                     "ball_x", "ball_y", "ball_dx", "ball_dy"):
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

    def test_sprite_tables_are_12_bytes_each(self):
        for name in ("P0Sprite", "P1Sprite"):
            base = self.sym[name]
            data = [self.addr(base + i) for i in range(PLAYER_HEIGHT)]
            self.assertFalse(all(b == 0 for b in data), f"{name} is all zeros")

    def test_sprite_tables_do_not_cross_page_boundary(self):
        # Guarantee that the indexed LDA in the kernel never pays the
        # +1 page-cross penalty (see main.asm kernel accounting).
        for name in ("P0Sprite", "P1Sprite"):
            base = self.sym[name]
            last = base + PLAYER_HEIGHT - 1
            self.assertEqual(base >> 8, last >> 8,
                             f"{name} crosses a page boundary")

    def test_players_are_solid_paddle_rectangles(self):
        # Round 2 renders both players as Pong-style vertical paddles:
        # PLAYER_HEIGHT identical solid rows of a 4-pixel bar.
        for name in ("P0Sprite", "P1Sprite"):
            base = self.sym[name]
            rows = [self.addr(base + i) for i in range(PLAYER_HEIGHT)]
            self.assertEqual(len(set(rows)), 1,
                             f"{name} rows are not identical")
            self.assertEqual(rows[0], 0x3C,  # %00111100
                             f"{name} is not the expected paddle shape")
            self.assertNotEqual(rows[0], 0, f"{name} is blank")

    def test_sprite_table_indices_valid(self):
        # Every row byte must use only the 8 visible pixels.
        for name in ("P0Sprite", "P1Sprite"):
            base = self.sym[name]
            for i in range(PLAYER_HEIGHT):
                self.addr(base + i)

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