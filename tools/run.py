#!/usr/bin/env python3
"""Run Wizard Duel in the Stella emulator.

Usage:
    python tools/run.py                 run the ROM (normal mode)
    python tools/run.py --debug         start in the Stella debugger
"""

import argparse
import subprocess
import sys

from common import ROM_PATH, require_build, tool


def main():
    parser = argparse.ArgumentParser(description="Run Wizard Duel in Stella")
    parser.add_argument("--debug", action="store_true",
                        help="start in the Stella debugger")
    args = parser.parse_args()

    stella = tool("stella", "python tools/run.py")
    require_build()

    cmd = [stella]
    if args.debug:
        cmd.append("-debug")
    cmd.append(str(ROM_PATH))

    print("Running: " + " ".join(cmd))
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())