#!/usr/bin/env python3
"""Verify that required external tools are installed and functional.

Usage:
    python tools/check_env.py

Exits 2 with a clear message when a required tool is missing or does not
behave as expected.  Used locally and by CI before building.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import probe_dasm, probe_stella, tool


def main():
    tool("dasm", "python tools/check_env.py", probe=probe_dasm)
    tool("stella", "python tools/check_env.py", probe=probe_stella)
    print("Tool availability OK: dasm, stella")
    return 0


if __name__ == "__main__":
    sys.exit(main())