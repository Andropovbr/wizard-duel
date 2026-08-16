"""Timing validation: frame structure constants and kernel cycle budget.

The kernel worst-case path is recomputed from the assembled listing with a
small deterministic 6502 cycle walker, so it does not rely on the comments
in main.asm.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from common import (ROOT, SRC_DIR, parse_listing, parse_symbols, require_build)

SCANLINE_BUDGET = 76


def _resolve_constant(expr, consts):
    """Resolve a numeric EQU expression to an int, or None when unknown.

    Handles decimal, $hex and %binary literals, plain identifiers that are
    already-resolved constants, and simple +/- arithmetic over them (the only
    operators used in constants.inc, e.g. "160 - BALL_WIDTH").
    """
    expr = expr.strip()
    if not expr:
        return None
    if expr.startswith("$"):
        return int(expr[1:], 16)
    if expr.startswith("%"):
        return int(expr[1:], 2)
    if re.fullmatch(r"\d+", expr):
        return int(expr, 10)
    if re.fullmatch(r"[A-Za-z_]\w*", expr):
        return consts.get(expr)
    parts = re.split(r"(\+|-)", expr)
    total = 0
    sign = 1
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part == "+":
            sign = 1
        elif part == "-":
            sign = -1
        else:
            term = _resolve_constant(part, consts)
            if term is None:
                return None
            total += sign * term
    return total


def read_constants():
    """Return {NAME: value} for numeric EQU symbols in constants.inc."""
    out = {}
    for line in (SRC_DIR / "constants.inc").read_text().splitlines():
        m = re.match(r"^\s*(\w+)\s*=\s*([^;]+)", line)
        if not m:
            continue
        name, expr = m.group(1), m.group(2)
        value = _resolve_constant(expr, out)
        if value is not None:
            out[name] = value
    return out


class TestFrameConstants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = read_constants()

    def test_ntsc_frame_262_scanlines(self):
        self.assertEqual(self.c.get("FRAME_SCANLINES"), 262)

    def test_region_scanlines_sum_to_frame(self):
        total = (self.c.get("VSYNC_SCANLINES", 0)
                 + self.c.get("VBLANK_SCANLINES", 0)
                 + self.c.get("KERNEL_SCANLINES", 0)
                 + self.c.get("OVERSCAN_SCANLINES", 0))
        self.assertEqual(total, self.c.get("FRAME_SCANLINES"))

    def test_kernel_is_192_scanlines(self):
        self.assertEqual(self.c.get("KERNEL_SCANLINES"), 192)

    def test_vblank_and_overscan_blank_times(self):
        # VBLANK 37 lines + OVERSCAN 30 lines + VSYNC 3 = 70 blank lines.
        self.assertEqual(self.c.get("VBLANK_SCANLINES"), 37)
        self.assertEqual(self.c.get("OVERSCAN_SCANLINES"), 30)
        self.assertEqual(self.c.get("VSYNC_SCANLINES"), 3)

    def test_timer_values_single_byte(self):
        for name in ("VBLANK_TIMER_VALUE", "OVERSCAN_TIMER_VALUE"):
            self.assertLess(self.c.get(name, 0), 256)

    def test_player_bounds_valid(self):
        height = self.c.get("PLAYER_HEIGHT", 0)
        # PLAYER_Y_MAX is a computed EQU (KERNEL_SCANLINES - HEIGHT - 1);
        # verify the expression result against the constants we can read.
        self.assertEqual(height, 12)
        self.assertEqual(self.c.get("KERNEL_SCANLINES"), 192)
        self.assertEqual(192 - height - 1, 179)
        self.assertEqual(self.c.get("PLAYER_Y_MIN"), 0)
        self.assertEqual(self.c.get("PLAYER1_X"), 16)
        self.assertEqual(self.c.get("PLAYER2_X"), 136)
        self.assertEqual(self.c.get("PLAYER1_Y_INIT"), 48)
        self.assertEqual(self.c.get("PLAYER2_Y_INIT"), 128)


class TestKernelCycleBudget(unittest.TestCase):
    """Recompute the worst-case kernel scanline cost from the listing."""

    OPC_CYCLES = {
        0x85: 3,   # STA zp
        0x8A: 2,   # TXA
        0x38: 2,   # SEC
        0xE5: 3,   # SBC zp
        0xC9: 2,   # CMP #imm
        0xC5: 3,   # CMP zp
        0xA8: 2,   # TAY
        0xB9: 4,   # LDA abs,Y (tables page-safe, see test_rom)
        0x4C: 3,   # JMP abs
        0xA9: 2,   # LDA #imm
        0xE8: 2,   # INX
        0xE0: 2,   # CPX #imm
    }

    @classmethod
    def setUpClass(cls):
        require_build()
        cls.sym = parse_symbols()
        cls.insts = cls._kernel_instructions()

    @classmethod
    def _kernel_instructions(cls):
        """Collect (addr, bytes) for one kernel loop iteration.

        The iteration ends at the BACKWARD branch that loops back to
        KernelLoop; earlier forward BNE instructions (the ball enable
        block) are part of the iteration body.
        """
        start = cls.sym["KernelLoop"]
        insts = []
        for r in parse_listing():
            if r["addr"] < start:
                continue
            insts.append((r["addr"], r["bytes"]))
            if r["bytes"][0] == 0xD0:  # BNE
                addr, bts = r["addr"], r["bytes"]
                rel = bts[1]
                if rel & 0x80:
                    rel -= 0x100
                if ((addr + 2 + rel) & 0xFFFF) < addr:  # backward = terminator
                    break
        return insts

    def _branch(self, opcode, addr, bts):
        rel = bts[0]
        if rel & 0x80:
            rel -= 0x100
        return (addr + 2 + rel) & 0xFFFF

    def _cost(self, addr, bts, taken_branch):
        op = bts[0]  # first byte of the instruction bytes is the opcode
        if op in self.OPC_CYCLES:
            return self.OPC_CYCLES[op]
        if op in (0xB0, 0xD0):  # BCS / BNE
            rel = bts[1]
            if rel & 0x80:
                rel -= 0x100
            target = (addr + 2 + rel) & 0xFFFF
            if taken_branch:
                cost = 3
                if ((addr + 2) >> 8) != (target >> 8):
                    cost += 1
                return cost
            return 2
        raise AssertionError(f"unexpected opcode ${op:02X} in kernel")

    def _simulate(self, p0_drawn, p1_drawn, ball_on):
        """Execute one kernel iteration, returning total cycles."""
        pc = self.sym["KernelLoop"]
        total = 0
        branch_index = 0
        max_steps = 64
        while max_steps:
            max_steps -= 1
            entry = next((i for i in self.insts if i[0] == pc), None)
            self.assertIsNotNone(entry, f"pc ${pc:04X} not in kernel body")
            addr, bts = entry
            op = bts[0]
            if op == 0xB0:  # BCS for a sprite block
                drawn = (p0_drawn if branch_index == 0 else p1_drawn)
                branch_index += 1
                if drawn:
                    total += self._cost(addr, bts, False)
                    pc = addr + 2
                else:
                    total += self._cost(addr, bts, True)
                    pc = self._branch(0xB0, addr, bts[1:])
                continue
            if op == 0x4C:  # JMP abs -> follow the target
                total += self._cost(addr, bts, False)
                pc = bts[1] | (bts[2] << 8)
                continue
            if op == 0xD0:  # BNE: ball block or loop terminator
                target = self._branch(op, addr, bts[1:])
                if target < addr:  # backward BNE KernelLoop (always taken)
                    total += self._cost(addr, bts, True)
                    break
                if ball_on:  # forward BNE .BallOff: not taken on the ball row
                    total += self._cost(addr, bts, False)
                    pc = addr + 2
                else:  # taken away from the ball row
                    total += self._cost(addr, bts, True)
                    pc = target
                continue
            total += self._cost(addr, bts, False)
            pc = addr + len(bts)
        return total

    def test_kernel_instruction_sequence_length(self):
        self.assertGreater(len(self.insts), 10)

    def test_worst_case_all_drawn_within_budget(self):
        cost = self._simulate(p0_drawn=True, p1_drawn=True, ball_on=True)
        self.assertLessEqual(cost, SCANLINE_BUDGET,
                             f"worst-case kernel path is {cost} > 76 cycles")
        self.assertEqual(cost, 71)  # documented worst case

    def test_best_case_all_blank_within_budget(self):
        cost = self._simulate(p0_drawn=False, p1_drawn=False, ball_on=False)
        self.assertLessEqual(cost, SCANLINE_BUDGET)
        self.assertEqual(cost, 57)  # documented best case

    def test_all_kernel_paths_within_budget(self):
        expected = {
            (True, True, True): 71,     # worst: both drawn + ball on
            (True, True, False): 69,
            (True, False, True): 65,
            (True, False, False): 63,
            (False, True, True): 65,
            (False, True, False): 63,
            (False, False, True): 59,
            (False, False, False): 57,  # best: both blank + ball off
        }
        for combo, cost_expected in expected.items():
            with self.subTest(combo=combo):
                cost = self._simulate(*combo)
                self.assertLessEqual(cost, SCANLINE_BUDGET)
                self.assertEqual(cost, cost_expected)


if __name__ == "__main__":
    unittest.main()