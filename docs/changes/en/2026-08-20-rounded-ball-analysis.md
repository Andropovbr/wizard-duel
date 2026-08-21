# Change: Rounded Ball Analysis (Round 8)

## Objective

Investigate whether the TIA Ball object can produce a visually "rounded" shape
(e.g. a diamond: 2px-4px-2px) instead of the current rectangular 4x4 block,
and implement it if safely possible within the table-direct kernel architecture.

## Added

- `docs/changes/en/2026-08-20-rounded-ball-analysis.md` (this file)
- `docs/changes/pt-BR/2026-08-20-analise-bola-arredondada.md` (Portuguese)

## Changed

None. No source code was modified.

## Removed

None.

## Technical Reasoning

### TIA Ball Hardware Limitation

The TIA Ball object is fundamentally a **horizontal line of pixels**:

- **Width** is fixed per-frame by `CTRLPF` D5:D4:
  - `%00` = 1 color clock
  - `%01` = 2 color clocks
  - `%10` = 4 color clocks (current setting)
  - `%11` = 8 color clocks
- **Height** is controlled by `ENABL`: the ball is visible on scanlines where
  `ENABL` bit 1 is set.
- **Shape**: strictly rectangular at any given `CTRLPF` width. There is no
  hardware support for per-scanline width variation.

The "rounded" shape requires different widths on different rows:

```
Row 0: 2 pixels  .XX.
Row 1: 4 pixels  XXXX
Row 2: 2 pixels  .XX.
```

This is only possible if `CTRLPF` can be changed **during the visible kernel**
on each ball row.

### Why CTRLPF Changes in the Kernel Are Unsafe

The current table-direct kernel has these constraints:

1. **Two writes per row**: each event entry holds exactly `reg1/val1` and
   `reg2/val2`. The ball's ON event already uses both slots for
   `ENABL`/`BALL_ENABLE`. A `CTRLPF` write would need a third slot.

2. **Constant-cost paths**: the kernel has three paths (38/54/46 cycles) with
   no data-dependent branching. Adding a conditional `CTRLPF` write would
   introduce a variable-cost path, violating the constant-cost invariant.

3. **Event table capacity**: the ball currently uses 2 events (ON + OFF). A
   rounded shape needs 2 additional `CTRLPF` events (set narrow width, restore
   default width) = 4 events total for the ball alone. Under collision stress
   (both players + both missiles + ball = 10 events max), this leaves only 6
   events for 4 objects, which can overflow `EV_MAX_EVENTS`.

4. **Write-slot timing**: `CTRLPF` is at `$0A`. The second write of a double
   must complete by CPU cycle 27 (beam gate `x >= 13`). `CTRLPF` itself is
   always at address `$0A` (x=10), which is below the gate — so `CTRLPF`
   **cannot be the second write** of a double entry. It would always need to be
   slot 1, displacing the ball's own `ENABL` write.

5. **Architectural integrity**: the Round 11 delta=1 fix was specifically
   designed to eliminate variable-cost paths from the kernel. Adding per-row
   `CTRLPF` writes reintroduces the exact class of change that caused the
   263-scanline slip in Rounds 7-10.

### Alternatives Evaluated

#### Option A: Ball with fixed width and adjusted height

A narrower or shorter ball (e.g. 2x2) would still be rectangular. This does
not address the visual roundness requirement.

#### Option B: Change CTRLPF between scanlines

As analyzed above, this requires:
- Per-row CTRLPF writes in the visible kernel (unsafe timing)
- Or per-row CTRLPF events in the table (capacity and slot-rule violations)
- Or restructuring the kernel to support 3+ writes per row (breaks the
  54/76 cycle budget)

**Rejected**: unsafe within the current architecture.

#### Option C: Ball + another TIA object combination

- **Player objects**: both P0 and P1 are already used for the wizards.
  Repurposing a player for the ball would remove a wizard from the display.
- **Missile objects**: M0 and M1 are used for projectiles. Reusing a missile
  for the ball shape would require rethinking the projectile system.
- **Playfield**: the playfield is not displayed in this game, so it cannot
  contribute to the ball shape.

**Rejected**: no unused TIA object is available for ball shaping.

#### Option D: Keep Ball rectangular (recommended)

The current 4x4 rectangular ball is the only safe option. It:
- Preserves all timing invariants (54/76 kernel worst case)
- Preserves the 262-scanline frame
- Preserves collision semantics
- Preserves the event-table capacity and slot rules
- Requires zero code changes

### Collision Impact

No change. The ball remains 4x4 pixels. Ball x P0 and Ball x P1 collision
latches behave identically.

### Event-Table Impact

No change. The ball uses 2 events (ON/OFF) as before. No additional events
are needed.

### ROM/RAM Impact

No change. No code was modified.

## Timing Impact

Before (baseline):
- Frame scanlines: 262
- Kernel worst case: 54 / 76 cycles
- Kernel slack: 22 cycles
- VBLANK worst work: 4528 cycles
- VBLANK margin: 336 cycles

After: identical (no code changes).

## Memory Impact

Before:
- ROM: 1808 bytes
- RAM: 81 bytes

After: identical (no code changes).

## Tests

All 261 existing tests pass. No new tests were added because no code was
modified.

## Known Limitations

The TIA Ball object is **inherently rectangular**. A truly rounded ball is
not possible with the TIA's Ball hardware on the Atari 2600. This is a
fundamental platform limitation, not a project limitation.

The only workaround (changing `CTRLPF` per-scanline) conflicts with the
table-direct kernel architecture and would reintroduce the timing instability
that Rounds 7-11 were designed to eliminate.

If a visually distinct ball is desired in the future, the options are:

1. **Color gradient**: change `COLUPF` per scanline to create a visual
   depth effect (not roundness, but visual interest).
2. **Different fixed width**: change `BALL_SIZE_CTRLPF` to 2 or 8 pixels
   for a different rectangular shape.
3. **Use a Player object**: repurpose one of the two player objects as a
   programmable-shape ball (at the cost of one wizard sprite).

## Next Logical Steps

- Continue with the current 4x4 rectangular ball.
- Consider a Player-based ball in a future round if programmable shape
  is prioritized over having two simultaneous wizards.
