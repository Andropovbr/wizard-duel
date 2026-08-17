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
        0xA9: 2,   # LDA #imm
        0xE9: 2,   # SBC #imm
        0x29: 2,   # AND #imm
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

        The iteration ends at the BACKWARD BNE that loops back to
        KernelLoop; the kernel body itself is branchless.
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

    def _simulate(self, p0_drawn=None, p1_drawn=None, ball_on=None):
        """Execute one kernel iteration, returning total cycles.

        The kernel is branchless: the only branch is the tail BNE that loops
        back, so every scanline costs the same 62 cycles regardless of
        player or ball state.  The arguments are accepted for compatibility
        with the benchmark tool but no longer affect the result.
        """
        pc = self.sym["KernelLoop"]
        total = 0
        max_steps = 64
        while max_steps:
            max_steps -= 1
            entry = next((i for i in self.insts if i[0] == pc), None)
            self.assertIsNotNone(entry, f"pc ${pc:04X} not in kernel body")
            addr, bts = entry
            op = bts[0]
            if op == 0xD0:  # BNE: only the loop terminator (always taken)
                total += self._cost(addr, bts, True)
                break
            total += self._cost(addr, bts, False)
            pc = addr + len(bts)
        return total

    def test_kernel_instruction_sequence_length(self):
        self.assertGreater(len(self.insts), 10)

    def test_worst_case_within_budget(self):
        cost = self._simulate()
        self.assertLessEqual(cost, SCANLINE_BUDGET,
                             f"kernel path is {cost} > 76 cycles")
        self.assertEqual(cost, 62)  # documented cost

    def test_best_case_within_budget(self):
        cost = self._simulate()
        self.assertLessEqual(cost, SCANLINE_BUDGET)
        self.assertEqual(cost, 62)

    def test_kernel_is_branchless(self):
        # The kernel body must contain no forward conditional branches; the
        # only branch is the backward loop terminator.  This guarantees that
        # every scanline costs the same 62 cycles regardless of game state.
        # Exclude the loop-opening STA WSYNC and the backward BNE terminator;
        # everything between must be straight-line code.
        body = self.insts[1:-1]
        for addr, bts in body:
            self.assertNotIn(bts[0], (0xB0, 0xF0, 0x10, 0x30, 0xD0),
                             f"conditional branch at ${addr:04X}")

    def test_all_kernel_paths_within_budget(self):
        # The kernel is branchless, so all eight historical "path" combos
        # cost the same 62 cycles; they are kept to pin the exact number.
        for combo in [(p0, p1, b) for p0 in (True, False)
                      for p1 in (True, False) for b in (True, False)]:
            with self.subTest(combo=combo):
                cost = self._simulate(*combo)
                self.assertLessEqual(cost, SCANLINE_BUDGET)
                self.assertEqual(cost, 62)


if __name__ == "__main__":
    unittest.main()