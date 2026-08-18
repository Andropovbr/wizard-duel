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
                     "UpdateMissiles", "PositionPlayers", "PositionBall",
                     "PositionMissiles", "BuildEvents", "AddEvent",
                     "SortEvents", "EmitEvents", "BubbleOrder", "PosObject",
                     "fineAdjustTable", "fineAdjustBegin", "P0Y", "P1Y",
                     "joystate", "ball_x", "ball_y", "ball_dx", "ball_dy",
                     "m0_x", "m0_y", "m0_active", "m1_x", "m1_y",
                     "m1_active", "fire_prev", "evCnt", "evIdx", "scanCnt",
                     "evTbl", "events", "evCount", "evOrder"):
            self.assertIn(name, self.sym, f"missing symbol {name}")

    def test_reset_at_rom_origin(self):
        self.assertEqual(self.sym["Reset"], ROM_ORIGIN)

    def test_ram_symbols_in_riot_ram(self):
        for name in ("P0Y", "P1Y", "joystate",
                     "ball_x", "ball_y", "ball_dx", "ball_dy",
                     "m0_x", "m0_y", "m0_active", "m1_x", "m1_y",
                     "m1_active", "fire_prev", "evCnt", "evIdx", "scanCnt",
                     "evTbl", "events", "evCount", "evOrder"):
            self.assertGreaterEqual(self.sym[name], 0x80)
            self.assertLessEqual(self.sym[name], 0xFF)

    def test_fine_adjust_table_page_aligned(self):
        self.assertEqual(self.sym["fineAdjustBegin"] & 0xFF, 0)

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
        # Round 3 renders both players as Pong-style vertical paddles: the
        # ON event writes PADDLE_BITS to GRP0/GRP1 on PLAYER_HEIGHT rows.
        self.assertEqual(read_constants().get("PADDLE_BITS"), 0x3C)

    def test_kernel_writes_objects_via_register_index(self):
        # The event kernel writes GRP0..ENABL with STA EV_WRITE_BASE,X.  The
        # two writes of an entry appear as STA $1A,X (95 1A) in the kernel.
        start = self.sym["KernelLoop"]
        end = self.sym["OverscanWait"]
        kernel = self.rom[start - ROM_ORIGIN:end - ROM_ORIGIN]
        self.assertIn(bytes([0x95, 0x1A]), kernel,
                      "kernel must write registers via STA $1A,X")

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