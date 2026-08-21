"""Memory validation: ROM and RAM usage must stay within hardware limits."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from common import RAM_LIMIT, ROM_LIMIT, require_build, ram_usage, rom_usage


class TestRomLimit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_build()
        cls.used, cls.available = rom_usage()

    def test_rom_used_within_limit(self):
        self.assertLessEqual(self.used, ROM_LIMIT)

    def test_rom_available_non_negative(self):
        self.assertGreaterEqual(self.available, 0)

    def test_rom_usage_totals_4k(self):
        self.assertEqual(self.used + self.available, ROM_LIMIT)

    def test_rom_usage_reported(self):
        # Round 1 ROM is well under the 4 KiB ceiling.
        self.assertLessEqual(self.used, ROM_LIMIT)


class TestRamLimit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_build()
        cls.used, cls.available = ram_usage()

    def test_ram_used_within_limit(self):
        self.assertLessEqual(self.used, RAM_LIMIT)

    def test_ram_available_non_negative(self):
        self.assertGreaterEqual(self.available, 0)

    def test_ram_usage_totals_128(self):
        self.assertEqual(self.used + self.available, RAM_LIMIT)

    def test_round3_ram_usage(self):
        # Round 6 (ball contact) RAM: players/ball/missiles/hp/flags (15,
        # now including ball_contact_flags) + fire_prev/evCnt (2) + event
        # table (60: dummy + 10 entries + marker) + builder temps (3) +
        # nullDelta (1) + orb_row_idx (1, rounded ball) = 82 bytes
        # ($80-$D1).  The +2 bytes over Round 11 are ball_contact_flags and
        # orb_row_idx.  The four pending kernel registers from Round 10 are
        # gone (the table-direct apply reads the entries directly).
        self.assertEqual(self.used, 82)


if __name__ == "__main__":
    unittest.main()