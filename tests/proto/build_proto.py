#!/usr/bin/env python3
"""Build the Orb Mini-Loop prototype ROM.

Usage:
    python tests/proto/build_proto.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = Path(__file__).resolve().parent / "orb_mini_loop_test.asm"
BUILD = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"

def main():
    dasm = "dasm"
    rom = BUILD / "orb_mini_loop_test.bin"
    lst = BUILD / "orb_mini_loop_test.lst"
    sym = BUILD / "orb_mini_loop_test.sym"

    print(f"Assembling {SRC} ...")
    result = subprocess.run(
        [dasm, str(SRC), "-I" + str(SRC_DIR), "-f3",
         "-o" + str(rom), "-l" + str(lst), "-s" + str(sym)],
        capture_output=True, text=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0 or not rom.exists():
        print("ERROR: DASM failed.", file=sys.stderr)
        sys.exit(1)

    size = rom.stat().st_size
    print(f"ROM: {size} bytes ({size/4096*100:.1f}% of 4 KiB)")
    print(f"Output: {rom}")

if __name__ == "__main__":
    main()
