# Wizard Duel - Benchmarks and regression comparison

## Metrics tracked

Measured deterministically from the assembled build artifacts (no display):

| Metric            | Meaning                                             |
| ----------------- | --------------------------------------------------- |
| ROM used          | high-water mark of emitted code/data below $FFFA    |
| RAM used          | RIOT variables allocated via `DS`                   |
| Frame scanlines   | `FRAME_SCANLINES` constant (262 for NTSC)           |
| Kernel worst case | worst kernel scanline cost, recomputed from listing |
| Kernel best case  | cheapest kernel scanline cost                       |
| Kernel slack      | `kernel_budget - kernel_worst`                      |
| VBLANK timer      | `VBLANK_TIMER_VALUE` (77 since Round 6)             |
| VBLANK worst work | TIM64T write -> first `LDA INTIM` (worst, emulated) |
| VBLANK margin     | `(timer - 1) * 64 - vblank_work`                    |
| Overscan loop     | `OVERSCAN_LOOP_COUNT` WSYNC writes                  |

## VBLANK margin

The VBLANK wait is only deterministic when the work before it finishes
comfortably before the timer expires; otherwise `WaitVBlank` falls through at
the variable work end and the frame shakes (Round 6 bug). `vblank_work` is
measured with the emulator's realistic branch timing under the worst-case
input (both missiles + both collision latches + alternating fire, HP kept
full), and `vblank_margin = (timer - 1) * 64 - vblank_work` is the slack
before the poll would exit early. A negative margin means the frame length is
input-dependent and is a hard regression.

## Kernel slack

One NTSC scanline is 76 CPU cycles. The Round 11 kernel is event-driven and
applies the event table directly on every scanline: a non-event line costs 38
cycles, an event line costs 54 cycles and the marker (end) line costs 46
cycles, so:

```text
kernel slack = 76 - 54 = 22 cycles
```

The kernel cost is constant regardless of how many writes an entry holds or
which objects fired (no data-dependent branching), so the 54-cycle event path
is the only path that competes with the budget.

Slack is a **first-class metric**: it is recorded in `latest.md`, in
`history.csv`, in `baseline.json` and in the regression report. Hardware work
that grows the kernel eats directly into slack; a scanline path that reaches
76 cycles is a hard failure. Reducing slack is a performance regression even
if the frame still renders.

## Baseline strategy

`python tools/regression.py` resolves the baseline in this order (first match
wins):

1. `--baseline <file>`: explicit JSON file with the metrics.
2. **Base branch, built locally**: on PRs the base branch (`GITHUB_BASE_REF`)
   or `origin/main` is checked out into a temporary git worktree, built with
   the base's own tooling and measured. This is the preferred comparison: it
   reflects the real base code and cannot hide regressions accumulated within
   a branch. `fetch-depth: 0` is required in CI for this to work.
3. **Base branch's committed baseline**: `git show
   <base>:docs/benchmarks/baseline.json` when the base cannot be built (e.g.
   it predates the tooling).
4. **Local persisted baseline**: `docs/benchmarks/baseline.json`, a deliberate
   reference point created when missing and only refreshed explicitly with
   `python tools/benchmark.py --update-baseline`. Per-branch benchmark runs
   never rewrite it, so comparing against it keeps accumulated regressions
   visible.
5. No baseline: the comparison is skipped, the report says so and the tool
   exits 0.

The comparison deliberately does **not** use the most recent `history.csv`
row, because that is this branch's own latest run and could hide regressions
that accumulated across several branch commits.

## Hard vs soft regressions

### Hard regressions (exit code 1)

Violating a hardware limit always fails CI:

* ROM > 4096 bytes
* RAM > 128 bytes
* kernel worst case > 76 cycles per scanline
* frame scanline count != 262
* build failure, broken tests, unavailable required tools

### Soft regressions (warnings, exit code 0)

Growth that stays within hardware limits is reported but does not fail CI.
Thresholds are centralized as constants in `tools/regression.py` (initial
conservative values):

| Metric            | Warning threshold                                  |
| ----------------- | -------------------------------------------------- |
| ROM growth        | > 32 bytes OR > 5.0%                               |
| RAM growth        | > 4 bytes OR > 10.0%                               |
| RAM pressure      | RAM used >= 75% of the 80-byte project budget      |
| RAM strong pressure | RAM used >= 90% of the 80-byte project budget    |
| Kernel worst case | increase > 4 cycles                                |
| Kernel slack      | decrease > 4 cycles                                |

The RAM thresholds back the Round 11 budget of keeping the game under 80 of
the 128 RIOT bytes: crossing 75% of that budget warns, crossing 90% warns
strongly, and using more than 80 bytes fails CI (a hard gate). RAM growth is
also compared against the baseline by absolute bytes and percentage. These
values are intentionally conservative; they are meant to make meaningful
regressions visible, not to fail on every byte. Update them only with a
documented technical reason.

## Reading the CI report

`regression.py` prints a comparison table:

```text
Metric             Baseline       Current        Delta
ROM used           528 B          612 B          +84 B (+15.9%)
RAM used           3 B            5 B            +2 B
Kernel worst case  56 cycles      60 cycles      +4 cycles
Kernel slack       20 cycles      16 cycles      -4 cycles
Frame scanlines    262            262            0

Hard limits: all PASS
Warnings:
  ROM used: ROM grew by 84 B (+15.9%)
Status: PASS with 1 warning
```

* `Delta` shows absolute and percentage change (empty `0` means unchanged).
* Any `FAIL - ...` line means a hard regression and a non-zero exit.
* `Status: PASS` - nothing to do. `Status: PASS with N warnings` - within
  hardware limits, but review the warnings. `Status: FAIL` - hardware limits
  violated.

In CI the same report is appended to the GitHub Actions job summary and saved
as `build/regression-report.txt` / `build/regression-report.json` artifacts.

## Persisted history

`docs/benchmarks/history.csv` records one row per benchmark run
(`latest.md` reflects the most recent run). In Round 1 the CSV gained the
`kernel_slack` column; in Round 6 it gained `vblank_work` / `vblank_margin`.
`tools/benchmark.py` migrates pre-existing rows in place (computing
`slack = kernel_budget - kernel_worst`, leaving the VBLANK columns empty for
rows measured before the emulator modeled realistic branch timing), so no
historical data is lost.

## Baseline and current state

The persisted baseline `docs/benchmarks/baseline.json` was created from the
Round 1 state and is deliberately kept as the reference point (it is only
rewritten with `--update-baseline`):

```text
Round 1 baseline:
ROM used:          528 bytes
RAM used:          3 bytes
Frame scanlines:   262
Kernel worst case: 56 / 76 cycles
Kernel slack:      20 cycles
Kernel best case:  44 cycles

Round 2 current (measured, after the ENABL timing fix):
ROM used:          528 bytes   (tables removed; page padding absorbs the savings)
RAM used:          7 bytes
Frame scanlines:   262
Kernel worst case: 62 / 76 cycles
Kernel slack:      14 cycles
Kernel best case:  62 cycles   (the kernel is branchless: best == worst)

Round 3 current (event-driven kernel + missiles):
ROM used:          1296 bytes  (event builder + missiles)
RAM used:          122 bytes   (event table + records + order array)
Frame scanlines:   262
Kernel worst case: 69 / 76 cycles   (two-write event line)
Kernel slack:      7 cycles
Kernel best case:  18 cycles   (non-event line)

Round 3.1 current (variable-size event entries + RAM shrink):
ROM used:          1296 bytes  (same; builder replaced, not larger)
RAM used:          48 bytes    (122 -> 48, no record/order buffers)
Frame scanlines:   262
Kernel worst case: 65 / 76 cycles   (two-write event line)
Kernel slack:      11 cycles   (7 -> 11)
Kernel best case:  18 cycles   (non-event line)

Round 4 current (collision + fixed overscan):
ROM used:          1296 bytes  (metric; ALIGN 256 absorbs the growth)
RAM used:          49 bytes    (48 -> 49, +hit_flags)
Frame scanlines:   262
Kernel worst case: 65 / 76 cycles
Kernel slack:      11 cycles
Kernel best case:  18 cycles
Overscan loop:     8 WSYNCs

Round 5 current (HP and player death):
ROM used:          1296 bytes  (metric; page alignment absorbs the growth)
RAM used:          51 bytes    (49 -> 51, +p0_hp/p1_hp)
Frame scanlines:   262
Kernel worst case: 65 / 76 cycles   (kernel unchanged)
Kernel slack:      11 cycles
Kernel best case:  18 cycles
Overscan loop:     7 WSYNCs   (8 -> 7 to absorb ProcessHitEffects)

Round 6 current (VBLANK shake fix):
ROM used:          1296 bytes
RAM used:          51 bytes
Frame scanlines:   262
Kernel worst case: 65 / 76 cycles   (kernel 192 -> 185 lines, same line cost)
Kernel slack:      11 cycles
VBLANK timer:      77         (69 -> 77; expiry ~4864 cycles)
VBLANK worst work: 4455 cycles (emulated, realistic branch timing)
VBLANK margin:     409 cycles  (timer expiry - worst work; must stay positive)
Overscan loop:     7 WSYNCs
```

Round 11 current (table-direct kernel, delta=1 fix):
```
ROM used:          1808 bytes  (+512 over Round 8; offset-aware builder + slot rules)
RAM used:          80 bytes    ($80-$CF; 60-byte uniform event table)
Frame scanlines:   262
Kernel worst case: 54 / 76 cycles   (event line; constant for all inputs)
Kernel slack:      22 cycles   (was 11 in Round 3.1-8; 76-54)
Kernel best case:  38 cycles   (non-event line)
Marker line:       46 cycles   (ends the kernel on line 185)
VBLANK timer:      77
VBLANK worst work: 4528 cycles (emulated, realistic branch timing)
VBLANK margin:     336 cycles
Overscan loop:     6 WSYNCs    (kernel end moved; 10-line overscan)
```

These numbers are measured from the artifacts on every run, not hardcoded
"truth" in the tooling.