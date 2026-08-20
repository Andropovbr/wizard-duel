"""Build validation: ROM artifact, size, format and hardware vectors."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import common

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

    @unittest.skipUnless(os.name == "posix", "POSIX-only fake executable")
    def test_fake_stella_rejected(self):
        # An executable named stella that is not actually Stella must fail.
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "stella"
            fake.write_text("#!/bin/sh\nprintf 'hello world\\n'\n")
            fake.chmod(0o755)
            ok, message = probe_stella(str(fake))
        self.assertFalse(ok)

    @unittest.skipUnless(os.name == "posix", "POSIX-only fake executable")
    def test_fake_stella_printing_nothing_rejected(self):
        # Silent exit-0 executable: without the Windows console quirk this
        # must never be accepted on Linux/macOS.
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "stella"
            fake.write_text("#!/bin/sh\nexit 0\n")
            fake.chmod(0o755)
            ok, message = probe_stella(str(fake))
        self.assertFalse(ok)

    @unittest.skipUnless(os.name == "posix", "POSIX-only fake executable")
    def test_fake_stella_missing_usage_marker_rejected(self):
        # "Stella" alone is not enough; the usage marker is required.
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "stella"
            fake.write_text("#!/bin/sh\nprintf 'Stella version 7.0\\n'\n")
            fake.chmod(0o755)
            ok, message = probe_stella(str(fake))
        self.assertFalse(ok)

    @unittest.skipUnless(os.name == "posix", "POSIX-only fake executable")
    def test_realistic_help_in_path_with_spaces_accepted(self):
        # Probe must work when the executable path contains spaces.
        text = "\nStella version 7.0\n\nUsage: stella [options ...] romfile\n"
        with tempfile.TemporaryDirectory() as tmp:
            spaced = Path(tmp) / "dir with spaces"
            spaced.mkdir()
            fake = spaced / "stella"
            fake.write_text("#!/bin/sh\nprintf '" + text + "'\n")
            fake.chmod(0o755)
            ok, message = probe_stella(str(fake))
        self.assertTrue(ok, message)


class TestStellaProbeWindows(unittest.TestCase):
    """Windows-specific Stella probe behavior, simulated on any platform.

    Stella 7.x GUI builds on Windows print `-help` straight to the console
    screen buffer (CONOUT$), so `capture_output` comes back empty.  These
    tests mock that scenario and verify the fallback inspects the executable
    itself (PE + exit 0 + distinctive markers) instead of any cmd.exe
    redirection trickery.
    """

    @staticmethod
    def _make_fake_pe(markers=True):
        """A minimal but structurally valid PE file for fallback tests."""
        pe = bytearray(b"MZ" + b"\x00" * 0x3A)
        pe_offset = 0x80
        pe += pe_offset.to_bytes(4, "little")       # e_lfanew at 0x3C
        pe += b"\x00" * (pe_offset - len(pe))       # pad to 0x80
        pe += b"PE\x00\x00"
        pe += b"\x00" * 64
        if markers:
            pe += b"\nStella version 7.0\n"
            pe += b"Usage: stella [options ...] romfile\n"
        return bytes(pe)

    @staticmethod
    def _probe_with(path, returncode):
        """Run probe_stella under the Windows console-output simulation."""
        result = SimpleNamespace(stdout="", stderr="", returncode=returncode)
        with mock.patch("os.name", "nt"), \
                mock.patch("common.subprocess.run", return_value=result):
            return probe_stella(path)

    def test_uncapturable_output_accepted_for_real_stella(self):
        # -help output goes to the console (not the pipe); a genuine
        # stella.exe must still be accepted via PE + exit 0 + markers.
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "stella.exe"
            fake.write_bytes(self._make_fake_pe(markers=True))
            ok, message = self._probe_with(str(fake), 0)
        self.assertTrue(ok, message)
        self.assertIn("verified PE", message)

    def test_non_stella_pe_rejected(self):
        # A PE named stella.exe without the Stella markers must be rejected.
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "stella.exe"
            fake.write_bytes(self._make_fake_pe(markers=False))
            ok, message = self._probe_with(str(fake), 0)
        self.assertFalse(ok)

    def test_non_pe_rejected(self):
        # A non-PE file named stella.exe must be rejected even on exit 0.
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "stella.exe"
            fake.write_text("#!/usr/bin/env python3\nprint('hello')\n")
            ok, message = self._probe_with(str(fake), 0)
        self.assertFalse(ok)

    def test_nonzero_exit_rejected(self):
        # A real-looking PE that fails on -help must be rejected.
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "stella.exe"
            fake.write_bytes(self._make_fake_pe(markers=True))
            ok, message = self._probe_with(str(fake), 1)
        self.assertFalse(ok)

    def test_captured_output_accepted_without_fallback(self):
        # Console-subsystem Stella builds (or a console-less environment)
        # print to the pipe; the strict text check must still pass.
        text = "\nStella version 7.0\n\nUsage: stella [options ...] romfile\n"
        with mock.patch("os.name", "nt"), \
                mock.patch("common.subprocess.run",
                           return_value=SimpleNamespace(stdout=text, stderr="",
                                                        returncode=0)):
            ok, message = probe_stella("C:/stella/stella.exe")
        self.assertTrue(ok, message)

    def test_exec_error_reported(self):
        with mock.patch("os.name", "nt"), \
                mock.patch("common.subprocess.run", side_effect=OSError("boom")):
            ok, message = probe_stella("C:/stella/stella.exe")
        self.assertFalse(ok)
        self.assertIn("could not execute", message)

    def test_path_with_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            spaced = Path(tmp) / "My Stella Dir"
            spaced.mkdir()
            fake = spaced / "stella.exe"
            fake.write_bytes(self._make_fake_pe(markers=True))
            ok, message = self._probe_with(str(fake), 0)
        self.assertTrue(ok, message)


class TestListing(unittest.TestCase):
    def test_listing_exists_and_has_code(self):
        rows = parse_listing()
        self.assertGreater(len(rows), 100)
        addrs = [r["addr"] for r in rows]
        self.assertLessEqual(max(addrs), 0xFFFF)


if __name__ == "__main__":
    unittest.main()