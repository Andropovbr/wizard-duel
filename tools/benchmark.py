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

from common import (BUILD_DIR, DOCS_DIR, ROOT, ROM_PATH, parse_listing,
                    parse_symbols, ram_usage, rom_usage)
from emu6502 import Cpu, load_rom
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
    "kernel_slack", "vblank_timer", "vblank_work", "vblank_margin",
    "overscan_loop",
]


def measure():
    sym = parse_symbols()
    used_r, avail_r = rom_usage()
    used_m, avail_m = ram_usage()
    c = read_constants()
    kernel = TestKernelCycleBudget()
    kernel.setUpClass()
    worst = kernel._simulate(event_line=True, two_write=True)  # two-write event line
    best = kernel._simulate(event_line=False)   # non-event line
    vblank_work = measure_vblank_work(sym, c)
    timer = c.get("VBLANK_TIMER_VALUE")
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
        "vblank_timer": timer,
        "vblank_work": vblank_work,
        "vblank_margin": (timer - 1) * 64 - vblank_work,
        "overscan_loop": c.get("OVERSCAN_LOOP_COUNT"),
    }


def measure_vblank_work(sym, c):
    """Return the worst measured VBLANK work in CPU cycles.

    Work is measured from the TIM64T write (start of the VBLANK countdown) to
    the first WaitVBlank poll read (the LDA INTIM that begins the wait).  If
    work exceeds the timer expiry (VBLANK_TIMER_VALUE * 64) the poll exits at
    the variable work end instead of the fixed timer boundary, which is the
    Round 6 frame-shake bug.  The emulator models taken-branch and page-cross
    cycle costs so this reflects real worst-case hardware timing.  A stressed
    run (both missiles active + both collision latches set, HP re-filled so
    missiles keep spawning) drives the worst realistic VBLANK cost.
    """
    sof = sym["StartOfFrame"]
    wv = sym["WaitVBlank"]
    p0_hp = sym["p0_hp"] - 0x80
    p1_hp = sym["p1_hp"] - 0x80
    rom = load_rom(ROM_PATH)

    def run_frame(cpu):
        start = cpu.cycles
        at_sof = cpu.pc == sof
        count = 0
        while count < 2:
            cpu.step()
            if cpu.pc == sof:
                count += 1
                if (at_sof and count == 1) or count == 2:
                    return cpu.cycles - start
        raise AssertionError("frame did not terminate")

    def measure_one(cpu):
        # Measure one frame's VBLANK work: cycles from the TIM64T write to the
        # first LDA INTIM of the WaitVBlank poll.
        tim_at = None
        prev_pc = cpu.pc
        prev_timer = cpu.timer
        while True:
            before = prev_pc
            cpu.step()
            prev_pc = cpu.pc
            if tim_at is None and cpu.timer > prev_timer + 1000:
                tim_at = cpu.cycles
            prev_timer = cpu.timer
            if tim_at is not None and before == wv:
                # first LDA INTIM of the poll -> work is done, wait begins
                return cpu.cycles - tim_at
            if cpu.pc == sof:
                break
        return 0

    worst = 0
    # Boot to steady state (4 frames), then measure stressed frames.
    cpu = Cpu(rom)
    cpu.reset()
    cpu.inpt[4] = 0xFF
    cpu.inpt[5] = 0xFF
    for frame in range(4):
        cpu.cxm0p = 0xC0
        cpu.cxm1p = 0xC0
        run_frame(cpu)
    for frame in range(12):
        press = frame % 2 == 0
        cpu.cxm0p = 0xC0
        cpu.cxm1p = 0xC0
        cpu.inpt[4] = 0x00 if press else 0xFF
        cpu.inpt[5] = 0x00 if press else 0xFF
        cpu.ram[p0_hp] = 3
        cpu.ram[p1_hp] = 3
        run_frame(cpu)
        work = measure_one(cpu)
        worst = max(worst, work)
    return worst


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
| VBLANK worst work | {m['vblank_work']} cycles |
| VBLANK margin | {m['vblank_margin']} cycles |
| Overscan WSYNC loop | {m['overscan_loop']} |
"""
    LATEST.write_text(text)
    return text


def migrate_history(history_path=HISTORY, fieldnames=FIELDNAMES):
    """Migrate older history rows to the current schema (in place).

    Adds the kernel_slack column (computed as kernel_budget - kernel_worst)
    and the vblank_work / vblank_margin columns (empty for rows measured
    before the emulator modeled realistic branch timing).

    Returns True when a migration was performed.  Existing rows are kept.
    """
    if not history_path.exists():
        return False
    with history_path.open(newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        header = reader.fieldnames or []
    missing = [col for col in fieldnames if col not in header]
    if not missing:
        return False
    for row in rows:
        if "kernel_slack" in missing:
            try:
                budget = int(row.get("kernel_budget", ""))
                worst = int(row.get("kernel_worst", ""))
                row["kernel_slack"] = str(budget - worst)
            except (TypeError, ValueError):
                row["kernel_slack"] = ""
        for col in missing:
            row.setdefault(col, "")
    with history_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames,
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return True


def append_history(m):
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    migrate_history(HISTORY, FIELDNAMES)
    # csv never writes a trailing newline after the last row, so a migrated
    # file may not end with one; without this an append would merge onto the
    # final row instead of starting a fresh line.
    if HISTORY.exists() and HISTORY.stat().st_size:
        data = HISTORY.read_bytes()
        if not data.endswith(b"\n"):
            HISTORY.write_bytes(data + b"\n")
    with HISTORY.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES,
                                lineterminator="\n")
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