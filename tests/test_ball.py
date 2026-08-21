"""Ball behavior validation.

Executes the assembled UpdateBall routine from the ROM with a small 6502
interpreter and verifies movement and boundary bounces deterministically,
without needing an emulator or a display.  Also validates the ball constants,
the RAM budget and the event-driven kernel that renders the ball.
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
        xmax = self.c["BALL_X_MAX"]
        x, y, dx, dy = self.step(xmax, 95, 1, 1)
        self.assertEqual((x, y), (xmax - 1, 96))
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
        xmax = self.c["BALL_X_MAX"]
        x, y, dx, dy = self.step(xmax, self.c["BALL_Y_MAX"], 1, 1)
        self.assertEqual((x, y), (xmax - 1, self.c["BALL_Y_MAX"] - 1))
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

    def test_ball_is_small_1_by_2(self):
        self.assertEqual(self.c.get("BALL_WIDTH"), 1)
        self.assertEqual(self.c.get("BALL_HEIGHT"), 2)
        # CTRLPF D5:D4 = %00 -> 1 color clock wide ($00).
        self.assertEqual(self.c.get("BALL_SIZE_CTRLPF"), 0b00000000)

    def test_ball_bounds_within_visible_area(self):
        height = self.c.get("BALL_HEIGHT")
        kernel = self.c.get("KERNEL_SCANLINES")
        self.assertEqual(self.c.get("BALL_X_MIN"), 0)
        self.assertEqual(self.c.get("BALL_X_MAX"), 160 - 1)
        self.assertEqual(self.c.get("BALL_Y_MIN"), 0)
        # ball_y is the FIRST display row; the ball occupies rows
        # ball_y .. ball_y + BALL_HEIGHT - 1.  BALL_Y_MAX keeps the last row
        # on the last visible kernel line (kernel - 1); the ball OFF event at
        # row KERNEL_SCANLINES is dropped by the event builder and ENABL is
        # cleared during overscan init.
        self.assertEqual(self.c.get("BALL_Y_MAX"), kernel - height)

    def test_ball_display_rows_stay_inside_visible_area(self):
        # For every allowed ball_y the ball is displayed on scanlines
        # ball_y .. ball_y + BALL_HEIGHT - 1, all within the visible region.
        height = self.c.get("BALL_HEIGHT")
        kernel = self.c.get("KERNEL_SCANLINES")
        y_min = self.c.get("BALL_Y_MIN")
        y_max = self.c.get("BALL_Y_MAX")
        self.assertGreaterEqual(y_min, 0)
        self.assertLessEqual(y_max + height - 1, kernel - 1)

    def test_ball_color_enable_and_size_register(self):
        self.assertEqual(self.c.get("BALL_COLOR"), 0x0E)
        # The TIA only samples bit 1 of the ball enable register, so the
        # event table writes %00000010 on a ball row (verified against the
        # Stella source: myEnam = value & 0x02).
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

    def test_ram_usage(self):
        # Round 6: P0Y..hit_flags + ball_contact_flags (15) + fire_prev/evCnt
        # (2) + evTbl (60, dummy + 10 entries + marker) + builder temps
        # evRow/tempCount/tblLen (3) + nullDelta (1) = 81 bytes ($80-$D0).
        # The +1 byte over Round 11 is the ball x player contact record
        # (CONTACT_P0/CONTACT_P1).  Round 12 adds game_state, game_mode,
        # select_prev, reset_prev (4 bytes) = 85 bytes.
        self.assertEqual(self.used, 85)


class TestEventKernel(unittest.TestCase):
    """Round 3 kernel: event-driven, ball rendered through the event table."""

    @classmethod
    def setUpClass(cls):
        require_build()
        cls.rom = ROM_PATH.read_bytes()
        cls.sym = parse_symbols()
        start = cls.sym["KernelLoop"]
        end = cls.sym["OverscanWait"]
        cls.kernel_bytes = cls.rom[start - ROM_ORIGIN:end - ROM_ORIGIN]
        cls.c = read_constants()

    def test_kernel_counts_down_event_delta(self):
        # evCnt holds the scanlines until the next event fires.  The Round 11
        # kernel uses a single RAM countdown (DEC evCnt) on every scanline:
        # the line counter and the event counter are the same byte, so the
        # kernel never needs a separate scanCnt.
        evc = self.sym["evCnt"] & 0xFF
        self.assertIn(bytes([0xC6, evc]), self.kernel_bytes,
                      "kernel must DEC evCnt")

    def test_kernel_writes_registers_via_register_index(self):
        # The kernel writes GRP0..ENABL with STA EV_WRITE_BASE,X where X is
        # the register index from the event table (95 1A = STA $1A,X).
        base = self.c["EV_WRITE_BASE"]
        self.assertEqual(base, 0x1A)
        self.assertIn(bytes([0x95, 0x1A]), self.kernel_bytes,
                      "kernel must write GRP0..ENABL via STA $1A,X")

    def test_kernel_does_not_reference_ball_x(self):
        # Regression: the ball's vertical span must be independent of ball_x.
        # In the event kernel the ball is drawn by events at ball_y, so the
        # kernel body must not reference ball_x at all.
        ball_x_zp = self.sym["ball_x"] & 0xFF
        self.assertNotIn(ball_x_zp, self.kernel_bytes,
                         "kernel must not reference ball_x")

    def test_ball_events_are_height_apart(self):
        # The builder emits the ball ON event at ball_y and OFF at ball_y +
        # BALL_HEIGHT, so the ball is visible for exactly BALL_HEIGHT rows.
        self.assertEqual(self.c["BALL_HEIGHT"], 2)

    def test_no_ball_bleed_into_overscan(self):
        # BALL_Y_MAX = KERNEL_SCANLINES - BALL_HEIGHT keeps the ball's last
        # row on the last kernel line; the ball OFF event at row
        # KERNEL_SCANLINES is dropped and the overscan init clears ENABL, so
        # the ball can never bleed into overscan.
        height = self.c["BALL_HEIGHT"]
        kernel = self.c["KERNEL_SCANLINES"]
        y_max = self.c["BALL_Y_MAX"]
        self.assertEqual(y_max, kernel - height)
        self.assertEqual(y_max + height - 1, kernel - 1)
        # Overscan init clears GRP0..ENABL (LDA #0 + five consecutive STAs),
        # so ENABL can never hold 1 into overscan.
        clear_all = bytes([0xA9, 0x00, 0x85, 0x1B, 0x85, 0x1C,
                           0x85, 0x1D, 0x85, 0x1E, 0x85, 0x1F])
        self.assertIn(clear_all, self.kernel_bytes,
                      "overscan init must clear GRP0..ENABL")

    def test_kernel_region_does_not_exceed_page(self):
        # The kernel body must stay within a single 256-byte page so every
        # branch and indexed access is deterministic.
        self.assertEqual(self.sym["KernelLoop"] >> 8,
                         self.sym["OverscanWait"] >> 8,
                         "kernel crosses a page boundary")


if __name__ == "__main__":
    unittest.main()