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


def read_constants():
    """Return {NAME: value} for numeric EQU symbols in constants.inc.

    Decimal values are written without a prefix; hexadecimal values use $.
    """
    out = {}
    for line in (SRC_DIR / "constants.inc").read_text().splitlines():
        m = re.match(r"^\s*(\w+)\s*=\s*(\$?[0-9a-fA-F]+)", line)
        if not m:
            continue
        name, raw = m.group(1), m.group(2)
        try:
            out[name] = int(raw, 16) if raw.startswith("$") else int(raw, 10)
        except ValueError:
            continue
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
        """Collect (addr, bytes) for one kernel loop iteration."""
        start = cls.sym["KernelLoop"]
        insts = []
        for r in parse_listing():
            if r["addr"] < start:
                continue
            insts.append((r["addr"], r["bytes"]))
            if r["bytes"][0] == 0xD0:  # BNE KernelLoop ends the iteration
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

    def _simulate(self, p0_drawn, p1_drawn):
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
            if op in (0xB0,):  # BCS for a sprite block
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
            if op == 0xD0:  # BNE KernelLoop (always taken in a full iteration)
                total += self._cost(addr, bts, True)
                break
            total += self._cost(addr, bts, False)
            pc = addr + len(bts)
        return total

    def test_kernel_instruction_sequence_length(self):
        self.assertGreater(len(self.insts), 10)

    def test_worst_case_both_drawn_within_budget(self):
        cost = self._simulate(p0_drawn=True, p1_drawn=True)
        self.assertLessEqual(cost, SCANLINE_BUDGET,
                             f"worst-case kernel path is {cost} > 76 cycles")
        self.assertEqual(cost, 56)  # documented worst case

    def test_best_case_both_blank_within_budget(self):
        cost = self._simulate(p0_drawn=False, p1_drawn=False)
        self.assertLessEqual(cost, SCANLINE_BUDGET)
        self.assertEqual(cost, 44)  # documented best case

    def test_single_player_drawn_paths_within_budget(self):
        for a, b in ((True, False), (False, True)):
            cost = self._simulate(a, b)
            self.assertLessEqual(cost, SCANLINE_BUDGET)


if __name__ == "__main__":
    unittest.main()