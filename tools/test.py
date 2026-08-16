#!/usr/bin/env python3
"""Run the Wizard Duel validation suite.

Usage:
    python tools/test.py                 static + build validation (CI-safe)
    python tools/test.py --verbose       show each test
    python tools/test.py --build         rebuild before testing

The static suite is fully deterministic and requires no display.  Runtime
validation in Stella (frame length, movement, visibility) is performed
locally with the GUI debugger and documented in docs/en/timing.md; see
docs/en/build.md for the CI runtime gap.
"""

import argparse
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from common import BUILD_DIR, RAM_LIMIT, ROM_LIMIT, ROOT, ram_usage, rom_usage


def run_static(verbose):
    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / "tests"), pattern="test_*.py")
    verbosity = 2 if verbose else 1
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    return result.wasSuccessful()


def print_gates():
    used_r, _ = rom_usage()
    used_m, _ = ram_usage()
    print("\nQuality gates:")
    print(f"  ROM <= {ROM_LIMIT}:        {'PASS' if used_r <= ROM_LIMIT else 'FAIL'} "
          f"({used_r} bytes used)")
    print(f"  RAM <= {RAM_LIMIT}:        {'PASS' if used_m <= RAM_LIMIT else 'FAIL'} "
          f"({used_m} bytes used)")


def main():
    parser = argparse.ArgumentParser(description="Run Wizard Duel tests")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--build", action="store_true", help="build first")
    args = parser.parse_args()

    if args.build:
        subprocess.run([sys.executable, str(ROOT / "tools" / "build.py")],
                       check=True)

    ok = run_static(args.verbose)
    print_gates()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()