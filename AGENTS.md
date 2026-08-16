# AGENTS.md

## Project Overview

This repository contains **Wizard Duel**, an experimental Atari 2600 game developed in 6502 Assembly.

The project intentionally targets a highly constrained platform and treats those constraints as part of the engineering challenge.

The current target is:

* Atari 2600 / VCS
* NTSC as the primary timing target unless explicitly stated otherwise
* 6502/6507 Assembly
* DASM assembler
* Stella emulator
* Maximum ROM size: **4 KiB**
* No bankswitching
* No external runtime
* Portable development workflow supporting both Linux and Windows

Gameplay design is expected to evolve.

Do **not** encode unnecessary gameplay assumptions into the project architecture, tests, tooling, or documentation unless the requirement is explicitly established.

Engineering constraints, timing correctness, reproducibility, ROM/RAM usage, build reliability, and regression detection are considered first-class requirements.

---

# Core Engineering Principles

## 1. Hardware Constraints Are Requirements

Atari 2600 hardware limitations must never be treated as recommendations.

Every implementation must respect:

* CPU timing
* TIA timing
* scanline timing
* VSYNC/VBLANK timing
* available RAM
* ROM size
* TIA object limitations
* RIOT resources
* frame timing
* kernel execution budgets

A change that visually appears to work but violates hardware timing is considered incorrect.

Emulator tolerance must never be used to justify invalid timing.

---

# Timing and Scanline Requirements

## 2. Scanline Timing Must Always Be Calculated

The Atari 2600 is a cycle-sensitive platform.

Any code executed during the visible kernel or other timing-critical sections must have its cycle cost explicitly understood.

For NTSC:

* CPU frequency is approximately 1.19 MHz.
* One scanline contains **76 CPU cycles**.
* A typical NTSC frame contains **262 scanlines**.
* Nominal refresh rate is approximately 60 Hz.

Timing-sensitive code must never rely on guesswork.

Whenever modifying:

* visible kernel code
* WSYNC handling
* RESPx positioning
* HMOVE/HMPx usage
* playfield changes during display
* sprite positioning
* color changes during display
* multiplexing
* mid-scanline TIA writes
* VSYNC/VBLANK logic
* scanline loops

the agent must calculate the affected execution paths.

Conditional branches are especially important.

Both branch outcomes must be analyzed whenever they occur in timing-sensitive code.

---

# Cycle Documentation

## 3. Critical Code Must Document Cycle Costs

Timing-critical routines should contain comments describing their cycle budget.

Example:

```asm
; Scanline budget: 76 cycles
;
; WSYNC               3
; LDA playerColor     3
; STA COLUP0          3
; LDA playerGraphic   4
; STA GRP0            3
; ...
;
; Total before next WSYNC: XX cycles
```

Comments do not replace automated validation, but they are expected where timing is non-obvious.

When branches have different costs, document the relevant paths.

Example:

```asm
; Branch not taken: 2 cycles
; Branch taken:     3 cycles
; Page crossing may add another cycle
```

Avoid placing branches near page boundaries without explicitly checking the timing consequences.

---

# Scanline Stability

## 4. Scanline Count Must Not Regress

The project must maintain a deterministic frame structure.

Automated tests should validate, whenever practical:

* total scanlines per frame
* VSYNC duration
* VBLANK duration
* visible region duration
* overscan duration
* unexpected scanline variation
* unstable frame timing

For NTSC builds, the expected target is normally:

```text
262 scanlines/frame
```

Any unexpected deviation must fail automated validation.

If variable scanline counts are intentionally introduced, this must be explicitly documented and justified.

Never silently accept scanline instability.

---

# Kernel Rules

## 5. Keep the Display Kernel Predictable

The visible kernel should remain as simple and deterministic as practical.

Avoid:

* expensive gameplay calculations inside the visible kernel
* unpredictable loops
* complex branching
* unnecessary indirect addressing
* general game-state processing during display
* calculations that can be moved to VBLANK or overscan

Prefer:

```text
VBLANK:
    gameplay calculations
    AI
    collision processing
    state updates
    position calculations

VISIBLE KERNEL:
    draw

OVERSCAN:
    remaining game logic
    housekeeping
```

Exact responsibility may evolve, but display code should remain timing-focused.

---

# ROM Constraint

## 6. ROM Must Remain Within 4 KiB

The project intentionally targets a standard 4 KiB ROM.

Maximum ROM size:

```text
4096 bytes
```

Bankswitching must not be introduced unless explicitly authorized.

Every build must report ROM usage.

Recommended output:

```text
ROM usage:
  Used:      3012 bytes
  Available: 1084 bytes
  Usage:     73.5%
```

The build or CI pipeline must fail if the generated ROM exceeds 4096 bytes.

ROM growth should be tracked over time.

Whenever a change causes significant ROM growth, the agent should mention it.

---

# RAM Constraint

## 7. RAM Usage Must Be Tracked

The Atari 2600 provides only 128 bytes of RIOT RAM.

RAM allocation must therefore be deliberate.

Avoid unnecessary variables and duplication.

Prefer:

* bit fields when appropriate
* shared temporary variables
* byte-sized counters
* compact state representations
* reuse of memory when lifetimes do not overlap

Do not sacrifice code clarity prematurely for one-byte savings, but RAM usage must remain visible and measured.

The build system should generate a RAM usage report whenever practical.

Recommended output:

```text
RAM usage:
  Used:       42 bytes
  Available:  86 bytes
  Usage:      32.8%
```

The CI pipeline must fail if RAM allocation exceeds the hardware limit.

---

# Performance Budgets

## 8. Performance Must Be Measured

Optimization must be driven by measurements.

Track relevant metrics such as:

* ROM usage
* RAM usage
* scanlines per frame
* CPU cycles in critical routines
* VBLANK cycle budget
* overscan cycle budget
* kernel cycle budget
* worst-case execution paths

Where practical, maintain historical performance data.

Example:

```text
commit      ROM     RAM    scanlines    worst kernel slack
abc123      2780    38     262          11 cycles
def456      2844    40     262           7 cycles
```

A benchmark should make regressions visible rather than relying on subjective observation.

---

# Performance Regression Policy

## 9. Regressions Must Be Detected Automatically

The CI pipeline should reject changes that violate hard limits.

Examples:

* ROM > 4096 bytes
* RAM > 128 bytes
* invalid frame scanline count
* scanline instability
* kernel cycle budget exceeded
* required tools unavailable
* build failure
* invalid ROM output
* automated test failure

Soft regressions should also be reported.

Examples:

* significant ROM growth
* significant RAM growth
* reduced kernel slack
* increased VBLANK cost
* increased overscan cost

Not every performance regression must fail CI, but every meaningful regression should be visible.

---

# Benchmark History

## 10. Maintain Historical Metrics

Benchmark and performance information should be persisted in the repository when practical.

Prefer a structure such as:

```text
docs/
  benchmarks/
    latest.md
    history.csv
```

or:

```text
docs/
  performance/
```

The exact format may evolve.

The important requirement is that developers can answer questions such as:

* When did ROM size grow?
* Which change reduced kernel timing margin?
* How much RAM is currently available?
* Has frame timing ever regressed?
* Did a refactor improve or degrade performance?

Avoid committing volatile emulator logs or unnecessarily large generated files.

Keep historical data concise and useful.

---

# Automated Testing

## 11. Tests Are Required

Every meaningful feature or bug fix should include appropriate tests where technically possible.

Testing should not be limited to gameplay behavior.

The project should develop tests covering areas such as:

### Build validation

* ROM builds successfully
* expected ROM artifact exists
* ROM size is valid
* ROM format is valid

### Memory validation

* RAM usage does not exceed limits
* ROM usage does not exceed limits

### Timing validation

* frame scanline count
* VSYNC timing
* VBLANK timing
* visible scanline count
* overscan timing
* critical cycle budgets

### Assembly validation

* required symbols exist
* expected vectors exist
* reset vector is valid
* code/data stays within expected address ranges

### Runtime validation

Where practical:

* startup succeeds
* frames remain stable
* emulator does not report critical errors
* known game-state transitions behave correctly

### Regression tests

Every bug that can reasonably be reproduced automatically should receive a regression test.

A fixed bug should not be allowed to silently return.

---

# Stella Integration

## 12. Stella Is the Reference Emulator

Stella is the primary emulator used for development and validation.

Tooling may use Stella features such as:

* headless execution where supported
* debugger
* frame statistics
* scanline inspection
* CPU/TIA inspection
* automated run scripts

Do not require a graphical environment for CI unless absolutely necessary.

Prefer automation-compatible execution.

If an automated Stella-based validation cannot run reliably on CI, provide a separate deterministic validation tool instead of simply omitting the test.

---

# DASM

## 13. DASM Is the Reference Assembler

The reference assembler is DASM.

The project must not depend on IDE-specific build behavior.

The canonical build must work from a terminal.

Typical conceptual build:

```text
dasm src/main.asm -f3 -owizard-duel.bin -lwizard-duel.lst -swizard-duel.sym
```

Exact paths and filenames may differ.

The repository should generate useful diagnostic artifacts such as:

* ROM binary
* listing file
* symbol file

These artifacts may be placed in a build directory.

Example:

```text
build/
  wizard-duel.bin
  wizard-duel.lst
  wizard-duel.sym
```

Generated artifacts should not normally be committed unless explicitly required.

---

# Cross-Platform Build

## 14. Build Workflow Must Be Platform-Agnostic

Development must be supported on:

* Linux
* Windows

Do not assume:

* Bash-only environments
* GNU-only utilities
* Windows-only batch scripts
* IDE-specific configuration

Prefer cross-platform tooling.

Python is acceptable for project tooling when appropriate.

Example:

```text
python tools/build.py
python tools/test.py
python tools/run.py
python tools/benchmark.py
```

Small platform-specific wrappers may exist, but the underlying workflow must remain shared.

Avoid duplicating major build logic between `.sh` and `.bat` files.

---

# Tool Availability Checks

## 15. Commands Must Validate Their Dependencies

Build, test, benchmark, and run commands must check whether required external programs are available.

At minimum, verify required tools such as:

```text
dasm
stella
python
```

where applicable.

If a dependency is missing, fail with a clear message.

Bad:

```text
FileNotFoundError
```

Better:

```text
ERROR: DASM was not found.

Install DASM and ensure the `dasm` executable is available in PATH.

Required for:
  python tools/build.py
```

The same principle applies to Stella and any future project dependency.

---

# Canonical Commands

## 16. Provide Simple Commands

The repository should expose straightforward commands for common operations.

Preferred conceptual interface:

```text
python tools/build.py
python tools/test.py
python tools/run.py
python tools/benchmark.py
```

Optionally:

```text
python tools/check.py
```

may execute the full local validation suite.

A developer should not need to remember complex assembler flags for everyday use.

---

# Clean Builds

## 17. Builds Must Be Reproducible

The project should support clean builds.

Generated files should be isolated from source files whenever practical.

Recommended layout:

```text
src/
tests/
tools/
docs/
build/
```

The build process must not depend on stale generated output.

CI must always build from a clean checkout.

---

# CI/CD

## 18. GitHub Actions Must Validate Every Change

The repository should contain a GitHub Actions pipeline.

At minimum it should run on:

* pull requests
* pushes to the main branch

The pipeline should perform:

1. dependency/tool setup
2. clean build
3. ROM validation
4. RAM validation
5. automated tests
6. timing validation
7. benchmark generation
8. regression checks

Recommended conceptual flow:

```text
checkout
   ↓
setup tools
   ↓
build
   ↓
static validation
   ↓
tests
   ↓
timing checks
   ↓
benchmark
   ↓
regression analysis
```

CI should fail loudly when hardware limits are violated.

---

# CI Artifacts

## 19. Keep Useful Build Evidence

CI may publish artifacts such as:

* ROM
* assembler listing
* symbol table
* benchmark report
* validation report

This makes debugging regressions easier.

Do not publish unnecessary large files.

---

# Quality Gates

## 20. Required Gates Before Considering Work Complete

A task is not complete merely because the ROM launches.

Before finishing a meaningful change, verify:

```text
Build                 PASS
Tests                 PASS
ROM <= 4096 bytes     PASS
RAM <= 128 bytes      PASS
Frame timing          PASS
Scanline validation   PASS
Critical timing       PASS
Regression checks     PASS
```

When a validation cannot yet be automated, state this explicitly.

Do not silently omit validation.

---

# Code Quality

## 21. Assembly Must Remain Maintainable

6502 Assembly should be written for humans as well as the CPU.

Prefer meaningful names.

Bad:

```asm
LDA temp1
STA temp2
```

Better:

```asm
LDA player_y
STA missile_y
```

Use constants instead of unexplained literals.

Bad:

```asm
LDA #$2C
```

Better:

```asm
LDA #PLAYER_COLOR
```

Document hardware tricks and non-obvious timing behavior.

Avoid comments that simply repeat instructions.

Bad:

```asm
LDA player_x ; Load player_x
```

Useful:

```asm
; RESP0 must occur before cycle 23 or horizontal positioning
; shifts into the next 15-pixel region.
STA RESP0
```

---

# Optimization Policy

## 22. Optimize Deliberately

Do not optimize blindly.

Priorities are:

1. hardware correctness
2. deterministic timing
3. game correctness
4. maintainability
5. ROM/RAM efficiency
6. micro-optimization

Timing-critical kernel code is an exception where cycle optimization may necessarily dominate readability.

When introducing a non-obvious optimization, document why it exists.

Do not replace readable code with obscure tricks merely to save insignificant space unless ROM pressure justifies it.

---

# Page Boundary Awareness

## 23. Page Crossings Matter

6502 page crossings can alter instruction timing.

Timing-sensitive code must account for this.

Critical routines, lookup tables, and branches should be placed deliberately when their address may affect timing.

Do not assume assembler placement is harmless.

Map/listing information should be available for inspection.

---

# Game Logic Separation

## 24. Keep Gameplay Out of Timing-Critical Code

Gameplay rules are expected to evolve.

Prefer separation between:

```text
game state
simulation
AI
input
collision handling
render preparation
display kernel
```

Do not unnecessarily couple a gameplay mechanic to the display implementation.

Where Atari hardware requires coupling, keep the boundary explicit.

---

# No Premature Gameplay Assumptions

## 25. Gameplay Is Intentionally Flexible

Do not assume permanent rules regarding:

* number of spells
* spell types
* health
* cooldowns
* AI behavior
* game modes
* player abilities
* arena layout
* scoring
* rounds
* power-ups
* status effects

unless the current task explicitly establishes them.

Infrastructure should remain capable of evolving with the game.

Do not build a large generic engine in anticipation of hypothetical features.

Implement only the abstractions justified by current requirements.

---

# AI-Agent Working Rules

## 26. Inspect Before Editing

Before implementing a change:

1. inspect the repository
2. understand the current architecture
3. identify timing-sensitive code
4. inspect existing tests
5. inspect build and CI tooling
6. identify ROM/RAM/timing impact

Do not immediately rewrite working systems.

Prefer small, reviewable changes.

---

# Preserve Existing Behavior

## 27. Avoid Unrelated Changes

Do not:

* perform large refactors unless required
* rename unrelated symbols
* reformat the entire codebase
* redesign build tooling unnecessarily
* change gameplay outside the task scope
* remove tests because they fail after a change

If an existing test becomes invalid because requirements genuinely changed, explain why before updating it.

---

# Bug Fix Policy

## 28. Reproduce Before Fixing

For bugs:

1. understand the failure
2. reproduce it
3. identify root cause
4. create a regression test when feasible
5. implement the smallest appropriate fix
6. run the full validation suite
7. compare performance before and after

Do not hide symptoms without understanding timing or hardware implications.

---

# Performance Comparison

## 29. Report Before/After Metrics

When a change affects low-level code, report relevant metrics.

Example:

```text
Before:
ROM: 2872 bytes
RAM: 41 bytes
Frame: 262 scanlines
Kernel worst path: 71/76 cycles

After:
ROM: 2899 bytes (+27)
RAM: 41 bytes
Frame: 262 scanlines
Kernel worst path: 69/76 cycles
```

This is especially important for:

* kernel changes
* rendering changes
* positioning code
* collision code
* new low-level systems
* optimizations
* significant refactors

---

# Documentation

## 30. Keep Technical Documentation Current

Documentation should explain architectural and hardware decisions that would otherwise be difficult to rediscover.

Useful topics include:

* memory layout
* frame layout
* kernel structure
* TIA object allocation
* timing budgets
* ROM usage
* RAM usage
* toolchain setup
* build process
* benchmark methodology

Avoid excessive documentation of obvious code.

# Educational Change Log

## 31. Every Work Session Must Leave a Traceable Change Log

For educational, review, debugging, and video-production purposes, every meaningful implementation round must produce a concise but technically useful record of what changed.

The goal is to make it possible to understand the evolution of the project without relying exclusively on Git diffs.

The agent must document, when applicable:

* code added
* code modified
* code removed
* files created
* files deleted
* tests added or changed
* build/tooling changes
* CI/CD changes
* timing changes
* ROM/RAM impact
* architectural decisions
* rejected approaches
* known limitations introduced or discovered

Do not merely list filenames.

Explain **why** each meaningful change was made and what behavior or engineering requirement it addresses.

---

# Change Log Structure

A recommended location is:

```text
docs/
  changes/
```

Each meaningful implementation round should generate one entry.

Recommended naming:

```text
docs/changes/
  2026-08-16-initial-kernel.md
  2026-08-17-player-movement.md
  2026-08-18-build-pipeline.md
```

If multiple changes occur on the same day, use an additional descriptive suffix.

Do not overwrite previous records.

---

# Recommended Change Log Format

Each entry should contain sections equivalent to:

```markdown
# Change: Initial kernel

## Objective

What this work session attempted to accomplish.

## Added

Describe new code, files, tests, tooling, or behavior.

## Changed

Describe existing code or behavior that was modified.

## Removed

Describe anything intentionally removed and why.

## Technical Reasoning

Explain the reasoning behind the implementation.

Include relevant Atari 2600 considerations such as:

- TIA behavior
- scanline timing
- CPU cycles
- RAM pressure
- ROM pressure
- page boundaries
- object allocation

## Timing Impact

Before:
- Frame scanlines:
- Critical path:

After:
- Frame scanlines:
- Critical path:

Explain any meaningful difference.

## Memory Impact

Before:
- ROM:
- RAM:

After:
- ROM:
- RAM:

## Tests

List tests added, modified, and executed.

Report their result.

## Known Limitations

Document anything intentionally incomplete or potentially problematic.

## Next Logical Steps

Describe reasonable next work items without treating them as committed gameplay requirements.
```

Sections with no relevant changes may be omitted rather than filled with meaningless text.

---

# Explain Changes for Humans

## 32. Change Logs Must Be Educational

The change log is not a duplicate of `git diff`.

Prefer explanations such as:

> Moved the player position update from the visible kernel to VBLANK because movement calculation does not need to occur while the electron beam is rendering the visible region. This recovers cycles in the display kernel and makes scanline timing more predictable.

Avoid entries such as:

> Refactored player code.

The intended audience includes:

* developers reviewing the project
* the project author returning after time away
* people learning Atari 2600 programming
* viewers of educational development videos

Explain hardware-specific consequences whenever they are relevant.

---

# Record Removed and Rejected Work

## 33. Removal Is Part of the History

When code or an approach is removed, record:

* what was removed
* why it was removed
* what replaced it, if anything
* whether the reason involved correctness, timing, ROM, RAM, maintainability, or changed requirements

When an implementation approach was attempted but rejected for an important technical reason, record that decision when useful.

Example:

> A branch-based sprite positioning approach was tested but rejected because the alternate execution paths produced inconsistent timing inside the visible kernel.

This information is especially valuable for educational material and future debugging.

---

# Git and Change Log Relationship

## 34. Git History and Educational History Serve Different Purposes

Git remains the source of truth for exact source changes.

The educational change log explains the reasoning and consequences of those changes.

Do not paste full diffs into documentation.

Do not duplicate every minor edit.

Document meaningful engineering changes at the work-session or task level.

Where useful, the change log may include the related commit hash.

Example:

```text
Commit: abc1234
```

Do not require a commit to exist before documenting work.

---

# Portuguese Documentation

## 35. Maintain Equivalent Documentation in Brazilian Portuguese

The project must maintain technical documentation in:

* English
* Brazilian Portuguese (`pt-BR`)

The two versions must remain functionally equivalent.

The Portuguese documentation is not expected to be a literal word-for-word translation.

It should preserve:

* technical meaning
* constraints
* decisions
* explanations
* examples
* warnings
* measurements

Use natural Brazilian Portuguese rather than mechanical translation.

Assembly identifiers, hardware register names, command names, file names, and technical terms that are conventionally used in English may remain unchanged.

Examples:

```text
WSYNC
VBLANK
scanline
kernel
benchmark
build
TIA
RIOT
DASM
Stella
```

Do not translate source-code identifiers merely for documentation consistency.

---

# Suggested Documentation Structure

A recommended organization is:

```text
docs/
  en/
    architecture.md
    memory-map.md
    timing.md
    build.md
    benchmarks/
    changes/

  pt-BR/
    arquitetura.md
    mapa-de-memoria.md
    timing.md
    build.md
    benchmarks/
    changes/
```

Alternatively, paired filenames are acceptable:

```text
docs/
  architecture.en.md
  architecture.pt-BR.md
```

Choose one convention and use it consistently.

The agent should not duplicate documentation structures unnecessarily.

---

# Documentation Synchronization

## 36. Documentation Changes Must Be Applied to Both Languages

When technical documentation is created or changed, update both English and Portuguese versions in the same task whenever practical.

CI should validate that required documentation pairs exist.

Where possible, add an automated documentation consistency check.

At minimum, CI should be able to detect cases such as:

```text
docs/en/timing.md exists
docs/pt-BR/timing.md missing
```

or:

```text
English change log entry exists
Portuguese equivalent missing
```

The pipeline does not need to verify that translations are linguistically identical.

Its purpose is to prevent one language from being silently abandoned.

---

# Bilingual Change Logs

## 37. Change History Must Also Exist in Both Languages

Each educational change entry must have an English and Brazilian Portuguese equivalent.

Recommended structure:

```text
docs/
  changes/
    en/
      2026-08-16-initial-kernel.md

    pt-BR/
      2026-08-16-kernel-inicial.md
```

or equivalent paired filenames.

Both versions should describe the same engineering work.

Performance numbers, ROM usage, RAM usage, timing measurements, test results, and commit references must match between versions.

---

# Documentation as Part of Definition of Done

## 38. A Meaningful Change Is Not Complete Until Its History Is Documented

For meaningful implementation work, Definition of Done additionally requires:

* educational change log created or updated
* added/changed/removed work described
* technical reasoning documented
* performance impact recorded when relevant
* tests recorded
* English documentation updated
* Brazilian Portuguese documentation updated
* both language versions remain technically consistent

The final agent report should also include the paths of the generated documentation.

Example:

```text
Documentation:
  EN: docs/changes/en/2026-08-16-player-movement.md
  PT-BR: docs/changes/pt-BR/2026-08-16-movimento-player.md
```

---

# Educational Documentation Principle

The repository should make it possible to answer not only:

> What does the code look like now?

but also:

> How did we get here, what changed, why was it changed, and what did that cost on the Atari 2600?

```
```


---

# Suggested Repository Layout

The structure may evolve, but a reasonable starting point is:

```text
wizard-duel/
├── AGENTS.md
├── README.md
├── src/
│   ├── main.asm
│   ├── constants.inc
│   └── ...
├── tests/
│   └── ...
├── tools/
│   ├── build.py
│   ├── run.py
│   ├── test.py
│   ├── benchmark.py
│   └── ...
├── docs/
│   ├── architecture.md
│   ├── memory-map.md
│   ├── timing.md
│   └── benchmarks/
├── build/
└── .github/
    └── workflows/
        └── ci.yml
```

Do not create empty architecture for its own sake.

Directories and files should exist when they provide actual value.

---

# Definition of Done

A change is considered complete only when:

* code assembles successfully
* existing tests pass
* appropriate new tests are added
* ROM remains within 4 KiB
* RAM remains within hardware limits
* scanline timing remains valid
* timing-critical paths have been checked
* benchmarks show no unexplained regression
* CI remains green
* Windows/Linux workflows remain valid
* documentation is updated when architectural behavior changed

The final task report should summarize:

```text
What changed
Tests performed
ROM usage
RAM usage
Timing/scanline result
Performance impact
Known limitations
```

---

# Final Rule

On Atari 2600 development:

> **Visual correctness is not proof of hardware correctness.**

Never conclude that an implementation is correct merely because it appears to work in Stella.

Timing, scanlines, memory limits, build reproducibility, and hardware constraints must be validated explicitly.
