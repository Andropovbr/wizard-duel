#!/usr/bin/env python3
"""Measure Wizard Duel metrics and persist benchmark history.

Usage:
    python tools/benchmark.py             measure, update latest.md + history
    python tools/benchmark.py --history   only append to history.csv
    python tools/benchmark.py --json      print metrics as JSON (no persistence)
    python tools/benchmark.py --update-baseline
                                           refresh docs/benchmarks/baseline.json
                                           from the current metrics

Metrics measured from the build artifacts (deterministic, no display):

  * ROM used / available
  * RAM used / available
  * frame scanlines (from constants)
  * kernel worst/best-case cycles (recomputed from the listing)
  * kernel slack = kernel_budget - kernel_worst
  * VBLANK / OVERSCAN timer values

The regression comparison (tools/regression.py) uses the base branch or the
persisted baseline.json, never the most recent history row, so accumulated
regressions within a branch cannot hide behind its own latest run.
"""

import argparse
import csv
import json
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
BASELINE = BENCH_DIR / "baseline.json"

# Stable ordering for metrics and CSV columns.
FIELDNAMES = [
    "rom_used", "rom_available", "ram_used", "ram_available",
    "scanlines", "kernel_worst", "kernel_best", "kernel_budget",
    "kernel_slack", "vblank_timer", "overscan_timer",
]


def measure():
    sym = parse_symbols()
    used_r, avail_r = rom_usage()
    used_m, avail_m = ram_usage()
    c = read_constants()
    kernel = TestKernelCycleBudget()
    kernel.setUpClass()
    worst = kernel._simulate(event_line=True)   # event line (two writes)
    best = kernel._simulate(event_line=False)   # non-event line
    return {
        "rom_used": used_r,
        "rom_available": avail_r,
        "ram_used": used_m,
        "ram_available": avail_m,
        "scanlines": c.get("FRAME_SCANLINES"),
        "kernel_worst": worst,
        "kernel_best": best,
        "kernel_budget": SCANLINE_BUDGET,
        "kernel_slack": SCANLINE_BUDGET - worst,
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
| Kernel slack | {m['kernel_slack']} cycles |
| VBLANK timer value | {m['vblank_timer']} |
| OVERSCAN timer value | {m['overscan_timer']} |
"""
    LATEST.write_text(text)
    return text


def migrate_history(history_path=HISTORY, fieldnames=FIELDNAMES):
    """Add the kernel_slack column to pre-slack history rows (in place).

    Returns True when a migration was performed.  Existing rows are kept and
    kernel_slack is computed as kernel_budget - kernel_worst.
    """
    if not history_path.exists():
        return False
    with history_path.open(newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        header = reader.fieldnames or []
    if "kernel_slack" in header:
        return False
    new_rows = []
    for row in rows:
        try:
            budget = int(row.get("kernel_budget", ""))
            worst = int(row.get("kernel_worst", ""))
            row["kernel_slack"] = str(budget - worst)
        except (TypeError, ValueError):
            row["kernel_slack"] = ""
        new_rows.append(row)
    with history_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(new_rows)
    return True


def append_history(m):
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    migrate_history(HISTORY, FIELDNAMES)
    with HISTORY.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if HISTORY.stat().st_size == 0:
            writer.writeheader()
        writer.writerow({k: m[k] for k in FIELDNAMES})


def update_baseline(m, force=False):
    """Create or refresh the persisted regression baseline.

    The baseline is a deliberate reference point (the Round 1 state).  It is
    only created when missing or explicitly refreshed with --update-baseline,
    so per-branch benchmark runs cannot silently rewrite it.
    """
    if BASELINE.exists() and not force:
        return False
    BASELINE.write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    return True


def main():
    parser = argparse.ArgumentParser(description="Measure and persist benchmarks")
    parser.add_argument("--history", action="store_true",
                        help="only append to history.csv")
    parser.add_argument("--json", action="store_true",
                        help="print metrics as JSON without persisting")
    parser.add_argument("--update-baseline", action="store_true",
                        help="refresh docs/benchmarks/baseline.json")
    args = parser.parse_args()

    m = measure()
    if args.json:
        print(json.dumps(m, sort_keys=True))
        return

    if args.update_baseline:
        created = update_baseline(m, force=True)
        print(f"Updated baseline {BASELINE}" + (" (created)" if created else ""))
        return

    if args.history:
        append_history(m)
        print(f"Appended benchmark to {HISTORY}")
        return

    append_history(m)
    update_baseline(m, force=False)
    print(write_latest(m).strip())
    print(f"\nUpdated {LATEST}")


if __name__ == "__main__":
    main()