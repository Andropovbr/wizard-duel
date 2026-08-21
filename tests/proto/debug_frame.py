#!/usr/bin/env python3
"""Debug script to test the orb prototype frame loop."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))

from emu6502 import Cpu, load_rom

PROTO_ROM = Path(__file__).resolve().parent / "orb_mini_loop_test.bin"
PROTO_SYM = Path(__file__).resolve().parent / "orb_mini_loop_test.sym"

# Parse symbols
sym = {}
for line in PROTO_SYM.read_text().splitlines():
    parts = line.split()
    if len(parts) >= 2:
        try:
            sym[parts[0]] = int(parts[1], 16)
        except ValueError:
            continue

sof = sym["StartOfFrame"]
print(f"StartOfFrame: ${sof:04X}")

rom = load_rom(PROTO_ROM)
cpu = Cpu(rom)
cpu.reset()
cpu.pc = sof

# Run 3 frames manually
for frame in range(3):
    start = cpu.cycles
    at_sof = cpu.pc == sof
    count = 0
    steps = 0
    max_steps = 100000
    while count < 2 and steps < max_steps:
        cpu.step()
        steps += 1
        if cpu.pc == sof:
            count += 1
            if (at_sof and count == 1) or count == 2:
                elapsed = cpu.cycles - start
                print(f"Frame {frame}: {elapsed} cycles, {steps} steps")
                break
    else:
        print(f"Frame {frame}: TIMEOUT after {steps} steps, pc=${cpu.pc:04X}")
        # Show what's happening
        print(f"  Last 5 instructions:")
        for i in range(5):
            op = cpu.rom[cpu.pc - 0xF000]
            print(f"    ${cpu.pc:04X}: op=${op:02X}")
            cpu.step()
            steps += 1
        break
