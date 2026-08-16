#!/usr/bin/env python3
"""Measure Wizard Duel metrics and persist benchmark history.

Usage:
    python tools/benchmark.py            measure and update latest.md
    python tools/benchmark.py --history  only append to history.csv

Metrics measured from the build artifacts (deterministic, no display):

  * ROM used / available
  * RAM used / available
  * frame scanlines (from constants)
  * kernel worst/best-case cycles (recomputed from the listing)
  * VBLANK / OVERSCAN timer values
"""

import argparse
import csv
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from common import (BUILD_DIR, DOCS_DIR, ROOT, parse_listing, parse_symbols,
                    ram_usage, rom_usage)
from test_timing import (SCANLINE_BUDGET, TestKernelCycleBudget,
                         read_constants)

BENCH_DIR = DOCS_DIR / "benchmarks"
LATEST = BENCH_DIR / "latest.md"
HISTORY = BENCH_DIR / "history.csv"


def measure():
    sym = parse_symbols()
    used_r, avail_r = rom_usage()
    used_m, avail_m = ram_usage()
    c = read_constants()
    kernel = TestKernelCycleBudget()
    kernel.setUpClass()
    worst = kernel._simulate(True, True)
    best = kernel._simulate(False, False)
    return {
        "rom_used": used_r,
        "rom_available": avail_r,
        "ram_used": used_m,
        "ram_available": avail_m,
        "scanlines": c.get("FRAME_SCANLINES"),
        "kernel_worst": worst,
        "kernel_best": best,
        "kernel_budget": SCANLINE_BUDGET,
        "vblank_timer": c.get("VBLANK_TIMER_VALUE"),
        "overscan_timer": c.get("OVERSCAN_TIMER_VALUE"),
    }


def write_latest(m):
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    text = f"""# Wizard Duel - Benchmark

Measured from the assembled build artifacts.

| Metric | Value |
| ------ | ----- |
| ROM used | {m['rom_used']} / {m['rom_used'] + m['rom_available']} bytes |
| RAM used | {m['ram_used']} / {m['ram_used'] + m['ram_available']} bytes |
| Frame scanlines | {m['scanlines']} |
| Kernel worst case | {m['kernel_worst']} / {m['kernel_budget']} cycles |
| Kernel best case | {m['kernel_best']} cycles |
| VBLANK timer value | {m['vblank_timer']} |
| OVERSCAN timer value | {m['overscan_timer']} |
"""
    LATEST.write_text(text)
    return text


def append_history(m):
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    new = not HISTORY.exists()
    with HISTORY.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(m.keys()))
        if new:
            w.writeheader()
        w.writerow(m)


def main():
    parser = argparse.ArgumentParser(description="Measure and persist benchmarks")
    parser.add_argument("--history", action="store_true",
                        help="only append to history.csv")
    args = parser.parse_args()

    m = measure()
    if args.history:
        append_history(m)
        print(f"Appended benchmark to {HISTORY}")
        return

    append_history(m)
    print(write_latest(m).strip())
    print(f"\nUpdated {LATEST}")


if __name__ == "__main__":
    main()