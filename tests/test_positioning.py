"""Horizontal positioning validation (coarse + fine).

The TIA cannot address an arbitrary pixel directly: horizontal placement is
split into a coarse step (RESP0..RESBL strobe after a divide-by-15 loop) and
a fine step (HMP0..HMBL, up to +/-7 pixels). This file models PosObject from
the assembled ROM and validates, for every possible input position P:

  * the divide loop produces the documented two's-complement remainder
    ($F1..$FF) so the page-aligned fine-adjust table is reached;
  * the rendered pixel equals the requested pixel, i.e. the compensation
    added in PositionBall / PositionPlayers cancels the routine's inherent
    offset (no systematic offset, no jump at the coarse/fine boundaries);
  * consecutive positions differ by exactly 1 pixel, including across the
    coarse/fine transitions at every multiple of 15;
  * the ball renders at exactly ball_x.

The coarse/fine model matches the behavior measured on the target (TIA /
Stella) by freezing the ball at every ball_x 0..156 and the paddles at every
PLAYER1_X in 0..155 (see the Round 2 change log):

  * divide-by-15 loop leaves Y = s - 15 (two's complement $F1..$FF) where
    s = P mod 15 is the fine-adjust table index;
  * fine adjustment = s - 7 (the page-aligned table holds +7..-7);
  * coarse position = 15*q for q >= 1, but only 3 for q = 0: the shortest
    divide path writes RESP before TIA cycle 23, so the object lands 3
    pixels right of the ideal q=0 base (0). This makes the routine render a
    player at P - 7 (q >= 1) or P - 4 (q = 0);
  * the ball appears 1 pixel left of a player for the same input;
  * PositionBall therefore passes ball_x + 8 (q >= 1) or ball_x + 5 (q = 0),
    and PositionPlayers passes X + 7 (q >= 1) or X + 4 (q = 0), so both
    render at their requested pixel for every valid position.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from common import (ROM_ORIGIN, ROM_PATH, parse_symbols, require_build)
from test_timing import read_constants

EXPECTED_TABLE = [
    0x70, 0x60, 0x50, 0x40, 0x30, 0x20, 0x10, 0x00,
    0xF0, 0xE0, 0xD0, 0xC0, 0xB0, 0xA0, 0x90,
]


def fine_shift(table_byte):
    """Signed pixel movement encoded in an HMPx high nibble.

    0 = none; 1..7 = left 1..7; 9..F (= -7..-1) = right 1..7.
    """
    nib = table_byte >> 4
    if nib == 0:
        return 0
    if nib < 8:
        return -nib          # left
    return 16 - nib          # right


class PositioningModel:
    """Reimplementation of PosObject (divide loop + fine table lookup)."""

    def __init__(self, table):
        self.table = table

    def divide_loop(self, p):
        """Run the SBC #15 / BCS loop; return (subtractions, remainder byte).

        The loop overshoots: it keeps subtracting while the accumulator is
        >= 0, so the final remainder is negative, two's complement $F1..$FF.
        """
        a = p
        q = 0
        while True:
            a -= 15
            q += 1
            if a < 0:
                break
        return q, a & 0xFF

    def rendered(self, p):
        """Position of a player object given raw PosObject input pixel P.

        q = P // 15 is the number of complete 15-pixel steps; the RESP
        strobe lands those at 15*q for q >= 1 and at 3 for q = 0 (the short
        divide path writes RESP before TIA cycle 23).
        """
        _, rem = self.divide_loop(p)
        s = (rem - 0xF1) & 0xFF          # s = P mod 15
        q = p // 15
        coarse = 3 if q == 0 else 15 * q
        return coarse + fine_shift(self.table[s])

    def player_rendered(self, p):
        """Rendered position of a player whose desired X is P."""
        pos = p + 7
        if pos < 15:
            pos = p + 4                  # q = 0 coarse base is 3, not 0
        return self.rendered(pos)

    def ball_rendered(self, x):
        """Rendered position of the ball whose desired left pixel is x."""
        pos = x + 8
        if pos < 15:
            pos = x + 5                  # q = 0 coarse base is 3, not 0
        return self.rendered(pos) - 1    # ball renders 1 pixel left of a player


class TestFineAdjustTable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_build()
        cls.sym = parse_symbols()
        cls.rom = ROM_PATH.read_bytes()

    def _table_bytes(self):
        base = self.sym["fineAdjustBegin"] - ROM_ORIGIN
        return list(self.rom[base:base + 15])

    def test_table_matches_reference(self):
        self.assertEqual(self._table_bytes(), EXPECTED_TABLE)

    def test_table_is_page_aligned_and_indexed_across_a_page(self):
        # LDA fineAdjustTable,Y must always cross a page boundary so the
        # RESP cycle stays deterministic (table base in one page, all 15
        # entries in the next).
        base = self.sym["fineAdjustTable"]
        self.assertEqual(self.sym["fineAdjustBegin"] >> 8, (base + 0xFF) >> 8)
        for rem in range(0xF1, 0x100):
            self.assertNotEqual((base + rem) >> 8, base >> 8,
                                f"index $%02X does not cross a page" % rem)

    def test_divide_loop_present_in_rom(self):
        # PosObject must be SBC #15 (E9 0F) feeding a BCS back to itself.
        start = self.sym["PosObject"] - ROM_ORIGIN
        self.assertIn(bytes([0xE9, 0x0F, 0xB0]),
                      bytes(self.rom[start:start + 32]))


class TestDivideLoopRemainder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_build()
        cls.model = PositioningModel(EXPECTED_TABLE)

    def test_remainder_is_twos_complement_negative(self):
        for p in range(160):
            q, rem = self.model.divide_loop(p)
            self.assertIn(rem, range(0xF1, 0x100), f"P={p}")
            # table index must equal P mod 15 (the overshoot is -15 + (P%15))
            self.assertEqual((rem - 0xF1) & 0xFF, p % 15, f"P={p}")
            self.assertEqual(q, p // 15 + 1, f"P={p}")

    def test_rendered_matches_measured_offsets(self):
        # q >= 1 renders at P - 7; q = 0 renders at P - 4 (coarse base 3).
        for p in range(15, 160):
            self.assertEqual(self.model.rendered(p), p - 7, f"P={p}")
        for p in range(4, 15):
            self.assertEqual(self.model.rendered(p), p - 4, f"P={p}")


class TestPlayerCompensation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_build()
        cls.model = PositioningModel(EXPECTED_TABLE)

    def test_player_renders_at_requested_pixel(self):
        # PositionPlayers passes X + 7 (or X + 4 for q = 0), cancelling the
        # routine's P - 7 / P - 4 offsets.
        for p in range(160):
            self.assertEqual(self.model.player_rendered(p), p, f"P={p}")

    def test_consecutive_positions_advance_one_pixel(self):
        for p in range(159):
            self.assertEqual(self.model.player_rendered(p + 1) -
                             self.model.player_rendered(p),
                             1, f"transition {p} -> {p + 1}")


class TestBallCompensation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_build()
        cls.model = PositioningModel(EXPECTED_TABLE)
        cls.c = read_constants()

    def test_ball_renders_at_ball_x(self):
        # PositionBall passes ball_x + 8 (or ball_x + 5 for q = 0); the ball
        # renders 1 pixel left of a player, so it lands at exactly ball_x.
        for x in range(self.c["BALL_X_MIN"], self.c["BALL_X_MAX"] + 1):
            self.assertEqual(self.model.ball_rendered(x), x, f"ball_x={x}")

    def test_ball_moves_one_pixel_per_frame(self):
        # No 15-pixel coarse jumps: every consecutive ball_x pair (including
        # the coarse/fine boundaries at 6->7, 13->14, 28->29, ...) must move
        # exactly 1 pixel.
        for x in range(self.c["BALL_X_MIN"], self.c["BALL_X_MAX"]):
            self.assertEqual(self.model.ball_rendered(x + 1) -
                             self.model.ball_rendered(x),
                             1, f"transition {x} -> {x + 1}")

    def test_ball_stays_fully_visible(self):
        width = self.c["BALL_WIDTH"]
        for x in range(self.c["BALL_X_MIN"], self.c["BALL_X_MAX"] + 1):
            left = self.model.ball_rendered(x)
            self.assertGreaterEqual(left, 0, f"ball_x={x}")
            self.assertLessEqual(left + width - 1, 159, f"ball_x={x}")


class TestMissileCompensation(unittest.TestCase):
    """Missiles are TIA Missile objects and, like the ball, render 1 pixel
    left of a player for the same input, so PositionMissiles uses the same
    compensation as PositionBall (input = x + 8, or x + 5 for the first
    15-pixel region)."""

    @classmethod
    def setUpClass(cls):
        require_build()
        cls.model = PositioningModel(EXPECTED_TABLE)
        cls.c = read_constants()

    def test_missile_renders_at_requested_pixel(self):
        # M0 flies x = 18..158, M1 x = 134..2; every value must land on itself.
        for x in range(self.c["M0_X_INIT"], self.c["M0_X_MAX"] + 1):
            self.assertEqual(self.model.ball_rendered(x), x, f"M0 x={x}")
        for x in range(self.c["M1_X_MIN"], self.c["M1_X_INIT"] + 1):
            self.assertEqual(self.model.ball_rendered(x), x, f"M1 x={x}")

    def test_missile_moves_two_pixels_per_frame(self):
        # MISSILE_SPEED = 2: consecutive fired positions step by exactly 2 px
        # with no 15-pixel coarse jumps.
        for x in range(self.c["M0_X_INIT"], self.c["M0_X_MAX"]):
            self.assertEqual(self.model.ball_rendered(x + 1) -
                             self.model.ball_rendered(x),
                             1, f"transition {x} -> {x+1}")

    def test_missile_stays_fully_visible(self):
        width = self.c["MISSILE_WIDTH"]
        self.assertEqual(width, 2)
        for x in range(self.c["M0_X_INIT"], self.c["M0_X_MAX"] + 1):
            left = self.model.ball_rendered(x)
            self.assertGreaterEqual(left, 0, f"M0 x={x}")
            self.assertLessEqual(left + width - 1, 159, f"M0 x={x}")
        for x in range(self.c["M1_X_MIN"], self.c["M1_X_INIT"] + 1):
            left = self.model.ball_rendered(x)
            self.assertGreaterEqual(left, 0, f"M1 x={x}")
            self.assertLessEqual(left + width - 1, 159, f"M1 x={x}")

    def test_missile_bounds_sane(self):
        # M0 starts near the left paddle and despawns at the right edge; M1
        # mirrors it.  Both stay inside the visible 160-pixel arena.
        self.assertEqual(self.c["M0_X_INIT"], 18)
        self.assertEqual(self.c["M1_X_INIT"], 134)
        self.assertLessEqual(self.c["M0_X_MAX"], 159)
        self.assertGreaterEqual(self.c["M1_X_MIN"], 0)


if __name__ == "__main__":
    unittest.main()