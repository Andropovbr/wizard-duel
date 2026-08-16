#!/usr/bin/env python3
"""Build the Wizard Duel ROM with DASM and report ROM usage.

Usage:
    python tools/build.py            build (incremental)
    python tools/build.py --clean    rebuild from a clean build directory
"""

import argparse
import subprocess
import sys

from common import (BUILD_DIR, ROM_LIMIT, ROM_NAME, SRC_DIR,
                    rom_usage, tool)

DASM_SRC = SRC_DIR / "main.asm"


def main():
    parser = argparse.ArgumentParser(description="Build Wizard Duel ROM")
    parser.add_argument("--clean", action="store_true",
                        help="remove build artifacts before assembling")
    args = parser.parse_args()

    dasm = tool("dasm", "python tools/build.py")

    if args.clean:
        BUILD_DIR.mkdir(exist_ok=True)
        for pattern in ("*.bin", "*.lst", "*.sym", "*.map"):
            for path in BUILD_DIR.glob(pattern):
                path.unlink()

    BUILD_DIR.mkdir(exist_ok=True)
    lst = BUILD_DIR / f"{ROM_NAME}.lst"
    sym = BUILD_DIR / f"{ROM_NAME}.sym"
    rom = BUILD_DIR / f"{ROM_NAME}.bin"

    print(f"Assembling {DASM_SRC} ...")
    result = subprocess.run(
        [dasm, str(DASM_SRC), "-I" + str(SRC_DIR), "-f3",
         "-o" + str(rom), "-l" + str(lst), "-s" + str(sym)],
        capture_output=True, text=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0 or not rom.exists():
        print("ERROR: DASM failed to assemble the ROM.", file=sys.stderr)
        sys.exit(1)

    size = rom.stat().st_size
    used, available = rom_usage()

    print()
    print("ROM usage:")
    print(f"  Used:      {used} bytes")
    print(f"  Available: {available} bytes")
    print(f"  Usage:     {100.0 * used / ROM_LIMIT:.1f}%")

    if size > ROM_LIMIT:
        print(f"ERROR: ROM is {size} bytes, exceeding the {ROM_LIMIT}-byte limit.",
              file=sys.stderr)
        sys.exit(1)
    print(f"OK: ROM is {size} bytes (within the {ROM_LIMIT}-byte limit).")


if __name__ == "__main__":
    main()