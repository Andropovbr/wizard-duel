# Change: Rounded Orb Production Integration

## Objective

Integrate the diamond-shaped orb (rounded ball) into the production kernel,
replacing the rectangular 4x4 ball with a visually rounded 2-4-4-2 pixel
shape using per-row CTRLPF width changes and HMBL fine positioning.

## Added

- **Orb mini-loop in kernel** (`src/main.asm:368-395`): Writes CTRLPF and
  ENABL per orb row before the event apply block.  Diamond shape:
  narrow (1px) - wide (4px) - wide (4px) - narrow (1px).

- **Orb state variable** (`src/main.asm:1829`): `orb_row_idx` (1 byte)
  counts down from BALL_HEIGHT to 0 during the orb mini-loop.

- **Orb width table** (`src/main.asm:971-974`): 4-byte lookup table
  mapping orb_row_idx to CTRLPF values (narrow/wide).

- **Orb constants** (`src/constants.inc:249-270`): ORB_CTRLPF_NARROW,
  ORB_CTRLPF_WIDE.

- **Orb regression tests** (`tests/test_orb.py`): 6 tests covering no
  ball events, frame timing, and P0/P1 event coexistence.

## Changed

- **BuildEvents** (`src/main.asm:1260-1270`): Ball is removed from the
  active mask.  Ball events are never generated; the orb mini-loop
  handles all ball rendering.

- **Kernel entry** (`src/main.asm:259-273`): Initializes orb_row_idx
  based on ball_y visibility.

- **Kernel loop** (`src/main.asm:368-417`): Added CTRLPF restoration
  check (10 cycles on non-orb scanlines) and orb writes (CTRLPF + ENABL)
  before event apply block.

- **emu6502.py**: Added LDA abs,X (opcode $BD) support; increased step
  limit from 2M to 4M for heavier kernel.

- **test_timing.py**: Updated OPC_CYCLES with new opcodes; updated cycle
  budget assertions (54/70/62 vs 38/54/46); updated branch count (4 vs 2).

- **test_events.py**: Updated Python event model to exclude ball from
  active set; updated all affected test expectations.

- **test_memory.py / test_ball.py**: Updated RAM assertion from 81 to 82.

- **test_regression.py**: Updated kernel slack assertion from 22 to 6.

## Removed

- Ball event generation from BuildEvents (no ENABL events in table).

- Ball scanning from BuildEvents selection loop (dead code removed).

## Technical Reasoning

### Design Decision: HMBL Instead of RESBL

The R&D spike proved that per-row RESBL positioning is too expensive:
the DEX/BNE delay loop costs 7 cycles/iteration, exceeding the kernel
budget for ball_x > ~15.  HMBL fine positioning (set once in VBLANK)
eliminates this cost entirely.

### CTRLPF Write Timing

CTRLPF is written at cycle 10-16 (before the beam reaches ball_x at
~cycle 49 for x=78).  ENABL is written at cycle 13-21.  Both are safe
for all valid X positions within the visible area.

### Event Apply Block Compatibility

The event apply block writes to AUDV0 (dummy entry, reg2=0) and to
specific TIA registers for P0/P1/M0/M1 events.  It never targets
ENABL, so the orb's ENABL write is safe from overwrite.

### Kernel Cycle Budget

- Non-event path: 54 cycles (+16 from baseline 38)
- Event path: 70 cycles (+16 from baseline 54)
- Marker path: 62 cycles (+16 from baseline 46)
- All within the 76-cycle budget (slack = 6 cycles)

The +16 cycle overhead comes from:
- CTRLPF restoration: 10 cycles (LDA + STA + BNE overhead)
- Orb check: 5 cycles (LDX + BEQ overhead)
- BEQ taken: 1 cycle overhead (3 vs 2)

## Timing Impact

Before:
- Frame scanlines: 262
- Kernel worst: 54/76 cycles (slack 22)

After:
- Frame scanlines: 262 (verified with 10000 frames)
- Kernel worst: 70/76 cycles (slack 6)

## Memory Impact

Before:
- ROM: 1808 bytes
- RAM: 81 bytes

After:
- ROM: 1808 bytes (same - ball event code removal offset orb additions)
- RAM: 82 bytes (+1 for orb_row_idx)

## Tests

- 261 existing tests: all pass (updated assertions)
- 6 new orb tests: all pass
- 10000 frame stability test: all exactly 262 scanlines

## Known Limitations

- Kernel slack reduced from 22 to 6 cycles.  The event path at 70 cycles
  leaves only 6 cycles of margin.  Any future kernel additions must be
  carefully budgeted.

- CTRLPF restoration runs on every non-orb scanline (10 cycles overhead).
  A single-restoration approach could save ~5 cycles per non-orb scanline
  but would add complexity.

## Next Logical Steps

- Visual validation in Stella (diamond shape at all X/Y positions)
- Consider reducing orb overhead if ROM pressure increases
- Potential optimization: skip CTRLPF restoration if orb is never active
