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
| VBLANK/OVERSCAN   | tuned RIOT timer values (69 / 11)                   |

## Kernel slack

One NTSC scanline is 76 CPU cycles. The Round 3 kernel is event-driven: a
non-event line costs 18 cycles and a two-write event line (the worst case)
costs 69 cycles, so:

```text
kernel slack = 76 - 69 = 7 cycles
```

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
| RAM growth        | > 4 bytes                                          |
| Kernel worst case | increase > 4 cycles                                |
| Kernel slack      | decrease > 4 cycles                                |

These values are intentionally conservative; they are meant to make
meaningful regressions visible, not to fail on every byte. Update them only
with a documented technical reason.

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
`kernel_slack` column; `tools/benchmark.py` migrates pre-existing rows in
place, computing `slack = kernel_budget - kernel_worst`, so no historical
data is lost.

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
RAM used:          121 bytes   (event table + records + order array)
Frame scanlines:   262
Kernel worst case: 69 / 76 cycles   (two-write event line)
Kernel slack:      7 cycles
Kernel best case:  18 cycles   (non-event line)
```

These numbers are measured from the artifacts on every run, not hardcoded
"truth" in the tooling.