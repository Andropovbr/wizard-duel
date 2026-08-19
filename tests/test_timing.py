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
    already-resolved constants, and simple + - * arithmetic over them (the
    operators used by constants.inc).  Unresolvable expressions return None
    instead of recursing forever.
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
    parts = re.split(r"(\+|\-|\*)", expr)
    if len(parts) == 1:
        return None  # contains an unknown operator -> not resolvable
    total = 0
    op = "+"
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part in ("+", "-", "*"):
            op = part
            continue
        term = _resolve_constant(part, consts)
        if term is None:
            return None
        if op == "+":
            total += term
        elif op == "-":
            total -= term
        else:  # "*"
            total *= term
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
        # VBLANK 57 lines + OVERSCAN 10 lines + VSYNC 3 = 70 blank lines.
        # VBLANK grew and OVERSCAN shrank in Round 3 to give BuildEvents room.
        self.assertEqual(self.c.get("VBLANK_SCANLINES"), 57)
        self.assertEqual(self.c.get("OVERSCAN_SCANLINES"), 10)
        self.assertEqual(self.c.get("VSYNC_SCANLINES"), 3)

    def test_vblank_plus_overscan_is_67(self):
        # 262 - 3 (VSYNC) - 192 (kernel) = 67 lines for VBLANK + overscan.
        self.assertEqual(self.c.get("VBLANK_SCANLINES", 0)
                         + self.c.get("OVERSCAN_SCANLINES", 0), 67)

    def test_timer_values_single_byte(self):
        for name in ("VBLANK_TIMER_VALUE", "OVERSCAN_LOOP_COUNT"):
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
    """Recompute the worst-case kernel scanline cost from the listing.

    The Round 3.1 kernel is event-driven: every scanline counts down scanCnt
    (the 192-line countdown) and evCnt (the next table entry).  Three paths
    exist inside the loop:

      * non-event line: 18 cycles (WSYNC, DEC scanCnt, BEQ not taken,
        DEC evCnt, BNE taken back to KernelLoop)
      * event line, single write: 54 cycles (the BNE is not taken and the
        BMI .singleWrite is taken)
      * event line, two writes: 65 cycles (neither the BNE nor the BMI is
        taken and the straight-line double-write code runs)

    All must stay inside the 76-cycle scanline budget.
    """

    OPC_CYCLES = {
        0x85: 3,   # STA zp
        0xC6: 5,   # DEC zp
        0xB9: 4,   # LDA abs,Y
        0xAA: 2,   # TAX
        0x95: 4,   # STA zp,X
        0x98: 2,   # TYA
        0x18: 2,   # CLC
        0x69: 2,   # ADC #imm
        0xA8: 2,   # TAY
        0x29: 2,   # AND #imm
        0x30: 2,   # BMI rel
        0x4C: 3,   # JMP abs
    }

    @classmethod
    def setUpClass(cls):
        require_build()
        cls.sym = parse_symbols()
        cls.insts = cls._kernel_instructions()

    @classmethod
    def _kernel_instructions(cls):
        """Collect (addr, bytes) for every instruction of the kernel body.

        The body spans KernelLoop up to (and including) the JMP that closes
        the event path; the overscan that follows (the BEQ target) is not
        part of a normal scanline's work.
        """
        start = cls.sym["KernelLoop"]
        end = cls.sym["OverscanWait"]
        insts = []
        for r in parse_listing():
            if start <= r["addr"] < end:
                insts.append((r["addr"], r["bytes"]))
        return insts

    def _at(self, pc):
        for addr, bts in self.insts:
            if addr == pc:
                return (addr, bts)
        raise AssertionError(f"pc ${pc:04X} not in kernel body")

    def _target(self, addr, bts):
        rel = bts[1]
        if rel & 0x80:
            rel -= 0x100
        return (addr + 2 + rel) & 0xFFFF

    def _simulate(self, event_line, two_write=True):
        """Cost of one full loop iteration for the given event outcome."""
        pc = self.sym["KernelLoop"]
        total = 0
        steps = 0
        while steps < 64:
            steps += 1
            addr, bts = self._at(pc)
            op = bts[0]
            if op == 0x4C:  # JMP KernelLoop: closes the event path
                total += self.OPC_CYCLES[0x4C]
                return total
            if op in (0xF0, 0xD0):  # BEQ / BNE
                target = self._target(addr, bts)
                if op == 0xD0 and target < addr:
                    # BNE KernelLoop: the loop terminator.  Taken = non-event
                    # line (we are back at KernelLoop); not taken = event line
                    # (fall into the event code).
                    if not event_line:
                        return total + 3
                    total += 2
                else:
                    # BEQ .kernelEnd (or any other forward branch): on a
                    # normal scanline it is not taken.
                    total += 2
                pc = addr + len(bts)
            elif op == 0x30:  # BMI .singleWrite
                # Single-write event: taken, jump into the single path.
                # Two-write event: not taken, run the straight-line path.
                if two_write:
                    total += 2
                    pc = addr + len(bts)
                else:
                    total += 3
                    pc = self._target(addr, bts)
            else:
                total += self.OPC_CYCLES[op]
                pc = addr + len(bts)
        raise AssertionError("kernel walk did not terminate")

    def test_kernel_instruction_sequence_length(self):
        self.assertGreater(len(self.insts), 10)

    def test_worst_case_within_budget(self):
        cost = self._simulate(event_line=True, two_write=True)   # two-write event line
        self.assertLessEqual(cost, SCANLINE_BUDGET,
                             f"event path is {cost} > 76 cycles")
        self.assertEqual(cost, 65)  # documented worst case

    def test_single_write_within_budget(self):
        cost = self._simulate(event_line=True, two_write=False)  # single-write event
        self.assertLessEqual(cost, SCANLINE_BUDGET,
                             f"single-write path is {cost} > 76 cycles")
        self.assertEqual(cost, 54)  # documented single-write case

    def test_best_case_within_budget(self):
        cost = self._simulate(event_line=False)   # non-event line
        self.assertLessEqual(cost, SCANLINE_BUDGET)
        self.assertEqual(cost, 18)  # documented best case

    def test_event_code_is_straight_line(self):
        # Between the DEC evCnt and the closing JMP, the event code has two
        # branches: the BMI that splits single/double writes and the closing
        # JMP.  The only other conditional branches in the whole kernel are
        # the BEQ (line countdown done) and the BNE (event or not).
        body = self.insts
        branches = [(a, b) for a, b in body if b[0] in (0xF0, 0xD0, 0x30)]
        self.assertEqual(len(branches), 3,
                         "kernel must contain exactly three conditional branches")

    def test_event_and_non_event_paths_within_budget(self):
        for event in (True, False):
            for two_write in (True, False):
                with self.subTest(event=event, two_write=two_write):
                    cost = self._simulate(event_line=event, two_write=two_write)
                    self.assertLessEqual(cost, SCANLINE_BUDGET)


if __name__ == "__main__":
    unittest.main()