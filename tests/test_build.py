"""Build validation: ROM artifact, size, format and hardware vectors."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from common import (ROM_ORIGIN, ROM_PATH, VECTOR_RESET, parse_listing,
                    probe_dasm, probe_stella, require_build, stella_rominfo)

ROM_LIMIT = 4096


class TestRomArtifact(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_build()
        cls.rom = ROM_PATH.read_bytes()

    def test_rom_exists(self):
        self.assertTrue(ROM_PATH.exists(), "ROM not built; run python tools/build.py")

    def test_rom_size_within_limit(self):
        self.assertLessEqual(len(self.rom), ROM_LIMIT)

    def test_rom_fills_exactly_4k(self):
        # DASM -f3 emits a full 4 KiB image starting at $F000.
        self.assertEqual(len(self.rom), ROM_LIMIT)

    def test_rom_not_empty(self):
        self.assertGreater(sum(1 for b in self.rom if b), 0)

    def test_reset_vector_points_into_rom(self):
        reset = self.rom[VECTOR_RESET - ROM_ORIGIN] | \
                (self.rom[VECTOR_RESET - ROM_ORIGIN + 1] << 8)
        self.assertGreaterEqual(reset, ROM_ORIGIN)
        self.assertLessEqual(reset, 0xFFFF)

    def test_all_vectors_equal_reset(self):
        # NMI/RESET/IRQ all point at Reset on the 2600 (interrupts unused).
        for v in (0xFFFA, 0xFFFC, 0xFFFE):
            val = self.rom[v - ROM_ORIGIN] | (self.rom[v - ROM_ORIGIN + 1] << 8)
            self.assertEqual(val, self.rom[VECTOR_RESET - ROM_ORIGIN] |
                             (self.rom[VECTOR_RESET - ROM_ORIGIN + 1] << 8),
                             f"vector ${v:04X} differs from RESET")


class TestStellaDetection(unittest.TestCase):
    def test_rominfo_reports_expected_format(self):
        # -rominfo validates ROM metadata (bankswitch, display format,
        # controllers) -- NOT runtime frame behavior.  See docs/en/build.md.
        result = stella_rominfo(ROM_PATH)
        out = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0,
                         f"stella -rominfo failed:\n{out}")
        self.assertIn("wizard-duel", out)
        self.assertIn("Bankswitch Type: 4K", out)
        self.assertIn("Display Format:  NTSC", out)
        self.assertIn("Joystick in left port", out)
        self.assertIn("Joystick in right port", out)


class TestDasmProbe(unittest.TestCase):
    @unittest.skipUnless(shutil.which("dasm"), "dasm not installed")
    def test_detects_real_dasm(self):
        ok, message = probe_dasm(shutil.which("dasm"))
        self.assertTrue(ok, message)

    def test_missing_dasm_fails(self):
        ok, message = probe_dasm("/nonexistent/dasm")
        self.assertFalse(ok)
        self.assertIn("could not execute", message)

    @unittest.skipUnless(os.name == "posix", "POSIX-only fake executable")
    def test_non_dasm_executable_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-dasm"
            fake.write_text("#!/bin/sh\nprintf 'hello world\\n'\n")
            fake.chmod(0o755)
            ok, message = probe_dasm(str(fake))
            self.assertFalse(ok)
            self.assertNotIn("Usage: dasm", message)


class TestStellaProbe(unittest.TestCase):
    @unittest.skipUnless(shutil.which("stella"), "stella not installed")
    def test_detects_real_stella(self):
        ok, message = probe_stella(shutil.which("stella"))
        self.assertTrue(ok, message)

    def test_missing_stella_fails(self):
        ok, message = probe_stella("/nonexistent/stella")
        self.assertFalse(ok)
        self.assertIn("could not execute", message)


class TestListing(unittest.TestCase):
    def test_listing_exists_and_has_code(self):
        rows = parse_listing()
        self.assertGreater(len(rows), 100)
        addrs = [r["addr"] for r in rows]
        self.assertLessEqual(max(addrs), 0xFFFF)


if __name__ == "__main__":
    unittest.main()