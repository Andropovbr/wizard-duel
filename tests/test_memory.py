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
        # Round 11 RAM: players/ball/missiles/hp/flags (14) + fire_prev/evCnt
        # (2) + event table (60: dummy + 10 entries + marker) + builder temps
        # (3) + nullDelta (1) = 80 bytes ($80-$CF).  The four pending kernel
        # registers from Round 10 are gone (the table-direct apply reads the
        # entries directly), so the +1 byte over Round 10 is only the dummy
        # entry that lets the pre-first-event apply write benign AUDV0.
        self.assertEqual(self.used, 80)


if __name__ == "__main__":
    unittest.main()