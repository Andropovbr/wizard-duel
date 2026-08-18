# Change: Fix INPT4/INPT5 TIA register addresses

## Objective

Make the joystick fire buttons actually readable in Stella (and on real
hardware).  The missile trigger worked in the deterministic unit-test
emulator but never fired in Stella, because the game read the wrong TIA
registers.

## Root cause

`src/constants.inc` defined:

```asm
INPT4 = $04              ; P0 fire button (bit 7, active low)
INPT5 = $05              ; P1 fire button (bit 7, active low)
```

But `$04` and `$05` are **NUSIZ0** and **NUSIZ1** - TIA *write-only*
registers.  The real TIA fire-button latches live at:

```text
INPT4 = $3C   ; P0 fire button (bit 7, active low)
INPT5 = $3D   ; P1 fire button (bit 7, active low)
```

On the 2600 data bus, reading a write-only TIA register returns the register
address on the bus (open-bus behaviour).  Stella emulates this, so every
`LDA INPT4` / `LDA INPT5` returned `$04` / `$05` respectively, with bit 7
always 0 - i.e. the software permanently read "button pressed".  The
rising-edge detection in `UpdateMissiles` therefore never observed a
`released -> pressed` transition and never fired a missile.

The bug was invisible to the unit tests because `tools/emu6502.py` modelled
the INPT reads at the *same wrong addresses* (`addr < 6` returned
`inpt[addr]`), so emulator and source agreed with each other but disagreed
with real TIA hardware and Stella.

## Investigation

Stella-based probes established the facts before the fix:

- Reading `$04`/`$05` returned `$04`/`$05` (their own addresses) with bit 7
  always 0, both at rest and while holding Space / Ctrl / Enter / X / Z.
- The fire key is correctly mapped (Stella config maps Space to
  `LeftJoystickFire`), and directions work: a SWCHA probe changed with the
  arrow keys.
- Reading the *correct* addresses `$3C`/`$3D` returns bit 7 = 1 (released)
  at rest and bit 7 = 0 (pressed) while holding Space.  Stella 6.7.1
  keyboard joystick input is delivered normally to these latches.

So this was a pure register-address bug, not an input-delivery problem.

## Changed

- `src/constants.inc`: `INPT4 = $3C`, `INPT5 = $3D`, with a comment
  explaining why `$04`/`$05` (NUSIZ0/NUSIZ1) would be wrong.
- `tools/emu6502.py`: TIA reads now map INPT0-5 to `$38-$3D` (and the
  mirrored `$78-$7D`) instead of `$00-$05`.  Writes to `$38-$3D` are
  ignored (read-only INPT latches), matching the TIA.

## Technical Reasoning

The TIA memory map places the read-only input latches at `$38-$3D`:

```text
$38-$3B  INPT0-INPT3   paddle/keypad inputs
$3C      INPT4         P0 fire button
$3D      INPT5         P1 fire button
```

`$04`/`$05` are the player-sprite size registers (NUSIZ0/NUSIZ1); they are
not readable and have no fire-button meaning.  Keeping the old definitions
would guarantee fire never worked outside the (wrong) test model.

## Timing Impact

Before:
- Frame scanlines: 262
- Critical path: 69/76 cycles (kernel unchanged)

After:
- Frame scanlines: 262
- Critical path: 69/76 cycles (kernel unchanged)

No timing change: `UpdateMissiles` still runs entirely in VBLANK and the
visible kernel is untouched.

## Memory Impact

Before:
- ROM: 1296 bytes
- RAM: 122 bytes

After:
- ROM: 1296 bytes (same instructions, different immediate addresses)
- RAM: 122 bytes

## Tests

- `python3 -m unittest tests.test_missile_fire -v`: 13/13 pass.
- Full suite `python3 tools/test.py`: 131 tests pass.
- ROM/RAM quality gates pass.
- Stella runtime validation (ROM built from fixed source):
  - no input at rest -> no missile, screen only shows P0/P1/ball;
  - holding Space -> a red M0 missile appears and moves right;
  - holding F (P1 fire) -> a blue M1 missile appears and moves left;
  - previously, holding any fire key produced a byte-identical screen.

## Known Limitations

The old `fire_sync` boot-synchronisation logic remains and is still correct:
on real hardware the INPT latches can read as pressed for the first frames
after RESET, so adopting the boot state without spawning remains necessary.

## Next Logical Steps

- Optionally add an automated Stella-based input test (e.g. script Stella to
  verify a snapshot changes when fire is held) so this class of
  emulator/test mismatch is caught in CI.