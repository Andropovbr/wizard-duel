# Wizard Duel

An experimental Atari 2600 game written in 6502 assembly (DASM), developed
for the NTSC platform.

Round 1 delivers the minimum technical base:

- a stable NTSC frame of exactly **262 scanlines**
- two TIA players visible simultaneously (P0 red on the left, P1 blue on
  the right)
- vertical-only movement driven by joystick 1 (P0) and joystick 2 (P1)

There is no magic system, projectiles, HP, AI or collisions yet; gameplay
rules are expected to evolve.

## Requirements

- Python 3.8+
- DASM 2.20.x
- Stella 6.x (to run the ROM)

On Ubuntu/Debian: `sudo apt-get install dasm stella`

## Commands

```sh
python tools/check_env.py       # verify dasm + stella are installed and work
python tools/build.py           # assemble the ROM
python tools/test.py            # deterministic validation suite
python tools/run.py             # run in Stella
python tools/benchmark.py       # measure and persist metrics
python tools/regression.py      # compare current metrics against a baseline
```

## Project layout

```
src/         6502 assembly source
tests/       deterministic validation suite
tools/       cross-platform Python toolchain
docs/        architecture, memory map, timing, build (EN + pt-BR)
build/       generated ROM/listing/symbols (not committed)
.github/     GitHub Actions CI
```

## Documentation

- English: `docs/en/` (architecture, memory-map, timing, build)
- Português (Brasil): `docs/pt-BR/` (arquitetura, mapa-de-memoria,
  timing, build)
- Change history: `docs/changes/` (EN and pt-BR)
- Benchmarks: `docs/benchmarks/`

## Validation

The deterministic test suite validates ROM size/format, memory usage,
symbols and addresses, page alignment, the frame structure (262 scanlines),
the kernel cycle budget (worst case 56/76 cycles, 20 cycles slack) and the
regression comparison against the baseline. Runtime checks (frame length,
movement, both players visible) are performed manually in the Stella
debugger and documented in `docs/en/timing.md`; `docs/en/build.md` explains
what `stella -rominfo` validates and the CI runtime gap. See
`docs/en/benchmarks.md` for the regression baseline and thresholds.

## License

MIT - see `LICENSE`.