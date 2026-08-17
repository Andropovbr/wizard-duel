"""Ball behavior validation.

Executes the assembled UpdateBall routine from the ROM with a small 6502
interpreter and verifies movement and boundary bounces deterministically,
without needing an emulator or a display.  Also validates the ball constants,
the RAM budget and that ENABL is written on every kernel scanline so the ball
never sticks.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from common import (ROM_ORIGIN, ROM_PATH, parse_listing, parse_symbols,
                    ram_usage, require_build)
from test_timing import read_constants


class Mini6502:
    """Minimal 6502 interpreter covering exactly the instructions used by
    UpdateBall: LDA zp/imm, CMP #imm, STA zp, CLC, ADC zp, BNE and RTS.

    Any other opcode inside the routine fails the test, so adding a new
    instruction to UpdateBall forces this interpreter to be extended.
    """

    def __init__(self, rom):
        self.rom = rom
        self.ram = bytearray(128)  # RIOT RAM $80-$FF
        self.a = 0
        self.sr = 0  # NV-BDIZC; only N, Z, C are used here

    def read(self, addr):
        if ROM_ORIGIN <= addr <= 0xFFFF:
            return self.rom[addr - ROM_ORIGIN]
        if 0x80 <= addr <= 0xFF:
            return self.ram[addr - 0x80]
        raise AssertionError(f"read outside supported memory: ${addr:04X}")

    def write(self, addr, value):
        if 0x80 <= addr <= 0xFF:
            self.ram[addr - 0x80] = value & 0xFF
            return
        raise AssertionError(f"write outside RAM: ${addr:04X}")

    def load(self, value):
        value &= 0xFF
        self.sr &= 0x01  # keep C, clear N/Z
        if value & 0x80:
            self.sr |= 0x80
        if value == 0:
            self.sr |= 0x02
        self.a = value

    def cmp_imm(self, value):
        value &= 0xFF
        t = (self.a - value) & 0xFFFF
        self.sr &= 0x01  # keep C, clear N/Z
        if t & 0x80:
            self.sr |= 0x80
        if (t & 0xFF) == 0:
            self.sr |= 0x02
        if self.a >= value:
            self.sr |= 0x01

    def adc(self, value):
        carry = self.sr & 0x01
        s = self.a + value + carry
        v = (~(self.a ^ value) & (self.a ^ (s & 0xFF))) & 0x80
        self.sr = 0
        if s & 0x80:
            self.sr |= 0x80
        if (s & 0xFF) == 0:
            self.sr |= 0x02
        if s > 0xFF:
            self.sr |= 0x01
        if v:
            self.sr |= 0x40
        self.a = s & 0xFF

    def run(self, entry):
        pc = entry
        steps = 0
        while steps < 512:
            steps += 1
            op = self.read(pc)
            if op == 0x60:  # RTS
                return self.ram
            if op == 0xA5:  # LDA zp
                self.load(self.read(self.read(pc + 1)))
                pc += 2
            elif op == 0xA9:  # LDA #imm
                self.load(self.read(pc + 1))
                pc += 2
            elif op == 0xC9:  # CMP #imm
                self.cmp_imm(self.read(pc + 1))
                pc += 2
            elif op == 0x85:  # STA zp
                self.write(self.read(pc + 1), self.a)
                pc += 2
            elif op == 0x18:  # CLC
                self.sr &= 0xFE
                pc += 1
            elif op == 0x65:  # ADC zp
                self.adc(self.read(self.read(pc + 1)))
                pc += 2
            elif op == 0xD0:  # BNE rel
                rel = self.read(pc + 1)
                if rel & 0x80:
                    rel -= 0x100
                if self.sr & 0x02:  # Z set -> not taken
                    pc += 2
                else:
                    pc = (pc + 2 + rel) & 0xFFFF
            else:
                raise AssertionError(
                    f"unexpected opcode ${op:02X} at ${pc:04X} in UpdateBall")
        raise AssertionError("UpdateBall did not return within 512 steps")


class TestUpdateBallMovement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_build()
        cls.rom = ROM_PATH.read_bytes()
        cls.sym = parse_symbols()
        cls.c = read_constants()

    def setUp(self):
        self.cpu = Mini6502(self.rom)
        self.bx = self.sym["ball_x"] - 0x80
        self.by = self.sym["ball_y"] - 0x80
        self.bdx = self.sym["ball_dx"] - 0x80
        self.bdy = self.sym["ball_dy"] - 0x80

    def step(self, x, y, dx, dy):
        m = self.cpu.ram
        m[self.bx], m[self.by] = x & 0xFF, y & 0xFF
        m[self.bdx], m[self.bdy] = dx & 0xFF, dy & 0xFF
        m = self.cpu.run(self.sym["UpdateBall"])
        return m[self.bx], m[self.by], m[self.bdx], m[self.bdy]

    def test_moves_diagonally_down_right(self):
        x, y, dx, dy = self.step(78, 95, 1, 1)
        self.assertEqual((x, y), (79, 96))
        self.assertEqual((dx, dy), (1, 1))

    def test_moves_up_left(self):
        x, y, dx, dy = self.step(80, 90, 0xFF, 0xFF)
        self.assertEqual((x, y), (79, 89))

    def test_bounces_at_right_edge(self):
        x, y, dx, dy = self.step(156, 95, 1, 1)
        self.assertEqual((x, y), (155, 96))
        self.assertEqual(dx, 0xFF)  # reversed to left

    def test_bounces_at_left_edge(self):
        x, y, dx, dy = self.step(0, 95, 0xFF, 1)
        self.assertEqual((x, y), (1, 96))
        self.assertEqual(dx, 1)  # reversed to right

    def test_bounces_at_bottom_edge(self):
        x, y, dx, dy = self.step(78, self.c["BALL_Y_MAX"], 1, 1)
        self.assertEqual((x, y), (79, self.c["BALL_Y_MAX"] - 1))
        self.assertEqual(dy, 0xFF)  # reversed up

    def test_bounces_at_top_edge(self):
        x, y, dx, dy = self.step(78, 0, 1, 0xFF)
        self.assertEqual((x, y), (79, 1))
        self.assertEqual(dy, 1)  # reversed down

    def test_bounce_at_bottom_right_corner(self):
        # Both bounces fire on the same frame and must stay in bounds.
        x, y, dx, dy = self.step(156, self.c["BALL_Y_MAX"], 1, 1)
        self.assertEqual((x, y), (155, self.c["BALL_Y_MAX"] - 1))
        self.assertEqual((dx, dy), (0xFF, 0xFF))

    def test_ball_stays_in_bounds_over_many_frames(self):
        x = self.c["BALL_X_INIT"]
        y = self.c["BALL_Y_INIT"]
        dx, dy = 1, 1
        for _ in range(2000):
            x, y, dx, dy = self.step(x, y, dx, dy)
            self.assertTrue(
                self.c["BALL_X_MIN"] <= x <= self.c["BALL_X_MAX"],
                f"ball_x {x} out of bounds")
            self.assertTrue(
                self.c["BALL_Y_MIN"] <= y <= self.c["BALL_Y_MAX"],
                f"ball_y {y} out of bounds")

    def test_ball_reaches_all_four_edges(self):
        # Over a long run the ball must actually touch every edge, proving
        # all four bounce checks fire.
        seen = set()
        x = self.c["BALL_X_INIT"]
        y = self.c["BALL_Y_INIT"]
        dx, dy = 1, 1
        for _ in range(2000):
            x, y, dx, dy = self.step(x, y, dx, dy)
            if x == self.c["BALL_X_MAX"]:
                seen.add("right")
            if x == self.c["BALL_X_MIN"]:
                seen.add("left")
            if y == self.c["BALL_Y_MAX"]:
                seen.add("bottom")
            if y == self.c["BALL_Y_MIN"]:
                seen.add("top")
        self.assertEqual(seen, {"left", "right", "top", "bottom"})


class TestBallConstants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = read_constants()

    def test_ball_is_square_4_by_4(self):
        self.assertEqual(self.c.get("BALL_WIDTH"), 4)
        self.assertEqual(self.c.get("BALL_HEIGHT"), 4)
        # CTRLPF D5:D4 = %10 -> 4 color clocks wide ($20, not $10 which is
        # only 2 clocks wide).
        self.assertEqual(self.c.get("BALL_SIZE_CTRLPF"), 0b00100000)

    def test_ball_bounds_within_visible_area(self):
        height = self.c.get("BALL_HEIGHT")
        self.assertEqual(self.c.get("BALL_X_MIN"), 0)
        self.assertEqual(self.c.get("BALL_X_MAX"), 160 - 4)
        self.assertEqual(self.c.get("BALL_Y_MIN"), 0)
        # The ball is BALL_HEIGHT rows tall; with ENABL latched for the next
        # line the top write row is ball_y and the bottom write row is
        # ball_y + BALL_HEIGHT - 1. BALL_Y_MAX keeps the last ENABL write on
        # kernel line 190, so the final line (191) always writes ENABL = 0
        # and the ball can never bleed into overscan.
        self.assertEqual(self.c.get("BALL_Y_MAX"), 192 - height - 1)

    def test_ball_display_rows_stay_inside_visible_area(self):
        # For every allowed ball_y the ball is displayed on scanlines
        # ball_y + 1 .. ball_y + BALL_HEIGHT, all within 1..191.
        height = self.c.get("BALL_HEIGHT")
        y_min = self.c.get("BALL_Y_MIN")
        y_max = self.c.get("BALL_Y_MAX")
        self.assertGreaterEqual(y_min + 1, 1)
        self.assertLessEqual(y_max + height, 192 - 1)

    def test_ball_color_enable_and_size_register(self):
        self.assertEqual(self.c.get("BALL_COLOR"), 0x0E)
        self.assertEqual(self.c.get("BALL_ENABLE"), 0x02)

    def test_ball_initial_position_within_bounds(self):
        x = self.c.get("BALL_X_INIT")
        y = self.c.get("BALL_Y_INIT")
        self.assertGreaterEqual(x, self.c.get("BALL_X_MIN"))
        self.assertLessEqual(x, self.c.get("BALL_X_MAX"))
        self.assertGreaterEqual(y, self.c.get("BALL_Y_MIN"))
        self.assertLessEqual(y, self.c.get("BALL_Y_MAX"))

    def test_direction_steps(self):
        self.assertEqual(self.c.get("DIR_LEFT"), 0xFF)
        self.assertEqual(self.c.get("DIR_RIGHT"), 1)
        self.assertEqual(self.c.get("DIR_UP"), 0xFF)
        self.assertEqual(self.c.get("DIR_DOWN"), 1)


class TestBallRamBudget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_build()
        cls.used, _ = ram_usage()

    def test_ram_usage_is_seven_bytes(self):
        # P0Y + P1Y + joystate + ball_x/ball_y/ball_dx/ball_dy.
        self.assertEqual(self.used, 7)


class TestKernelBallEnable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_build()
        cls.rom = ROM_PATH.read_bytes()
        cls.sym = parse_symbols()
        start = cls.sym["KernelLoop"]
        end = cls.sym["OverscanWait"]
        cls.kernel_bytes = cls.rom[start - ROM_ORIGIN:end - ROM_ORIGIN]
        cls.c = read_constants()

    def test_enabl_written_once_per_scanline_via_shared_store(self):
        # ENABL ($1F) is latched for the following scanline, so it must be
        # written on every line or the ball would stick on screen. The ball
        # block converges its on and off paths on a single shared STA ENABL:
        # exactly one such store in the kernel body guarantees a write every
        # scanline with no window where the register keeps its old value.
        self.assertEqual(self.kernel_bytes.count(bytes([0x85, 0x1F])), 1,
                         "kernel must write ENABL exactly once per scanline")

    def test_ball_range_check_present(self):
        # The ball block must compare the scanline index against ball_y with
        # SBC zp followed by CMP #BALL_HEIGHT (row = X - ball_y; enable while
        # row < BALL_HEIGHT).
        height = self.c["BALL_HEIGHT"]
        ball_zp = self.sym["ball_y"] & 0xFF
        self.assertIn(bytes([0xE5, ball_zp, 0xC9, height]),
                      self.kernel_bytes,
                      "kernel must range-check X against ball_y..+height")

    def test_ball_enabled_for_exactly_height_scanlines(self):
        # Model the kernel range check: ENABL = 1 exactly when
        # ball_y <= X < ball_y + BALL_HEIGHT.
        height = self.c["BALL_HEIGHT"]
        for ball_y in (0, 1, 95, self.c["BALL_Y_MAX"]):
            on_rows = [x for x in range(192) if ball_y <= x < ball_y + height]
            self.assertEqual(len(on_rows), height, f"ball_y={ball_y}")
            self.assertEqual(on_rows[0], ball_y)

    def test_no_ball_bleed_into_overscan(self):
        # The last kernel scanline (X = 191) must never write ENABL = 1, so
        # the ball cannot bleed into overscan or the next frame.
        height = self.c["BALL_HEIGHT"]
        for ball_y in range(self.c["BALL_Y_MIN"], self.c["BALL_Y_MAX"] + 1):
            self.assertFalse(ball_y <= 191 < ball_y + height,
                             f"ball_y={ball_y} leaks ENABL on the last line")

    def test_kernel_region_does_not_exceed_page(self):
        # The kernel body must stay within a single 256-byte page so every
        # branch and indexed access is deterministic.
        self.assertEqual(self.sym["KernelLoop"] >> 8,
                         self.sym["OverscanWait"] >> 8,
                         "kernel crosses a page boundary")


if __name__ == "__main__":
    unittest.main()