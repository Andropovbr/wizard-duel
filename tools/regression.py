#!/usr/bin/env python3
"""Compare current Wizard Duel metrics against a baseline and report regressions.

Usage:
    python tools/regression.py               current vs resolved baseline
    python tools/regression.py --baseline F  compare against an explicit JSON file
    python tools/regression.py --json        also write build/regression-report.json

Baseline resolution (first match wins):
  1. --baseline <file>
  2. the base branch, built in a temporary git worktree (base ref from
     GITHUB_BASE_REF on CI, otherwise origin/main when available)
  3. the base branch's committed docs/benchmarks/baseline.json (git show)
  4. the local persisted docs/benchmarks/baseline.json
  5. no baseline: report is skipped and the tool exits 0

Hard regressions (hardware limits) fail with exit code 1:
  * ROM > 4096 bytes
  * RAM > 128 bytes
  * RAM > PROJECT_RAM_BUDGET (the current round's RAM target, tighter than
    the hardware limit so budget pressure is caught before it becomes fatal)
  * kernel worst case > 76 cycles
  * frame scanline count != 262

Soft regressions (growth within hardware limits) are reported as warnings
and do NOT fail CI.  Thresholds are centralized below and documented in
docs/en/benchmarks.md (and docs/pt-BR/benchmarks.md).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from common import (BUILD_DIR, ROOT, RAM_LIMIT, ROM_LIMIT, run)
from benchmark import BASELINE, measure
from test_timing import SCANLINE_BUDGET

REPORT_TXT = BUILD_DIR / "regression-report.txt"
REPORT_JSON = BUILD_DIR / "regression-report.json"
REPORT_MD = BUILD_DIR / "regression-report.md"

EXPECTED_SCANLINES = 262

# ---------------------------------------------------------------------------
# Soft regression thresholds (centralized; documented in docs/en/benchmarks.md)
# ---------------------------------------------------------------------------
WARN_ROM_GROWTH_BYTES = 32
WARN_ROM_GROWTH_PCT = 5.0
WARN_RAM_GROWTH_BYTES = 4
WARN_RAM_GROWTH_PCT = 10.0
WARN_KERNEL_WORST_INCREASE = 4
WARN_KERNEL_SLACK_DECREASE = 4

# RAM pressure: warn when utilization crosses these fractions of the 128-byte
# hardware limit.  The project RAM budget (below) is a harder, earlier gate.
RAM_PRESSURE_WARN_PCT = 75.0
RAM_PRESSURE_STRONG_PCT = 90.0

# Current round's RAM target.  Exceeding it is a hard regression even though
# the hardware limit is 128 bytes, so budget pressure is caught early.
# Round 11: 80 bytes ($80-$CF) - the event table grew to 60 bytes (5-byte
# dummy + 10 entries + marker) so the table-direct kernel can apply every
# entry from the table without pending registers (the delta=1 fix).
PROJECT_RAM_BUDGET = 80

# (key, label, unit) -- the labels/order used in the report.
METRICS = [
    ("rom_used", "ROM used", "B"),
    ("ram_used", "RAM used", "B"),
    ("kernel_worst", "Kernel worst case", "cycles"),
    ("kernel_slack", "Kernel slack", "cycles"),
    ("scanlines", "Frame scanlines", ""),
]


def warning_for(key, base, current):
    """Return a human-readable warning string, or None when within thresholds."""
    if key == "rom_used":
        growth = current - base
        pct = (growth / base * 100.0) if base else 0.0
        if growth > WARN_ROM_GROWTH_BYTES or pct > WARN_ROM_GROWTH_PCT:
            return f"ROM grew by {growth} B ({pct:+.1f}%)"
    elif key == "ram_used":
        growth = current - base
        pct = (growth / base * 100.0) if base else 0.0
        pressure = 100.0 * current / RAM_LIMIT
        reasons = []
        if growth > WARN_RAM_GROWTH_BYTES:
            reasons.append(f"grew by {growth} B")
        elif base and pct > WARN_RAM_GROWTH_PCT:
            reasons.append(f"grew by {growth} B ({pct:+.1f}%)")
        if pressure >= RAM_PRESSURE_STRONG_PCT:
            reasons.append(f"utilization {pressure:.0f}% >= "
                           f"{RAM_PRESSURE_STRONG_PCT:.0f}%")
        elif pressure >= RAM_PRESSURE_WARN_PCT:
            reasons.append(f"utilization {pressure:.0f}% >= "
                           f"{RAM_PRESSURE_WARN_PCT:.0f}%")
        if reasons:
            return "RAM " + "; ".join(reasons)
    elif key == "kernel_worst":
        increase = current - base
        if increase > WARN_KERNEL_WORST_INCREASE:
            return f"kernel worst case increased by {increase} cycles"
    elif key == "kernel_slack":
        decrease = base - current
        if decrease > WARN_KERNEL_SLACK_DECREASE:
            return f"kernel slack reduced by {decrease} cycles"
    return None


def compare(base, current):
    """Return (rows, warnings, hard_failures).

    rows is a list of (label, baseline_str, current_str, delta, pct, unit).
    """
    rows = []
    warnings = []
    for key, label, unit in METRICS:
        b = base.get(key)
        c = current.get(key)
        if b is None or c is None:
            continue
        delta = c - b
        pct = (delta / b * 100.0) if b else 0.0
        rows.append((label, b, c, delta, pct, unit))
        warning = warning_for(key, b, c)
        if warning:
            warnings.append(f"{label}: {warning}")

    hard = []
    if current.get("rom_used", 0) > ROM_LIMIT:
        hard.append(f"ROM {current['rom_used']} > {ROM_LIMIT} bytes")
    if current.get("ram_used", 0) > RAM_LIMIT:
        hard.append(f"RAM {current['ram_used']} > {RAM_LIMIT} bytes")
    if current.get("ram_used", 0) > PROJECT_RAM_BUDGET:
        hard.append(f"RAM {current['ram_used']} > project budget "
                    f"{PROJECT_RAM_BUDGET} bytes")
    if current.get("kernel_worst", 0) > SCANLINE_BUDGET:
        hard.append(f"kernel worst case {current['kernel_worst']} > "
                    f"{SCANLINE_BUDGET} cycles")
    if current.get("scanlines") != EXPECTED_SCANLINES:
        hard.append(f"scanline count {current.get('scanlines')} != "
                    f"{EXPECTED_SCANLINES}")
    return rows, warnings, hard


def format_cell(value, unit):
    text = f"{value} {unit}".strip()
    return text


def format_delta(delta, pct, unit):
    if delta == 0:
        return "0"
    text = f"{delta:+d} {unit}".strip()
    text += f" ({pct:+.1f}%)"
    return text


def render_report(rows, warnings, hard, baseline_source, current_source):
    """Return the developer-facing report text."""
    lines = []
    lines.append("Performance comparison")
    lines.append("======================")
    lines.append("")
    lines.append(f"Baseline: {baseline_source}")
    lines.append(f"Current:  {current_source}")
    lines.append("")
    width_label = max(len(r[0]) for r in rows) if rows else 8
    header = (f"{'Metric':<{width_label}}  {'Baseline':<14} {'Current':<14}"
              f" Delta")
    lines.append(header)
    lines.append("-" * len(header))
    for label, b, c, delta, pct, unit in rows:
        lines.append(f"{label:<{width_label}}  "
                     f"{format_cell(b, unit):<14} "
                     f"{format_cell(c, unit):<14} "
                     f"{format_delta(delta, pct, unit)}")
    lines.append("")
    if hard:
        lines.append("HARD REGRESSIONS:")
        for h in hard:
            lines.append(f"  FAIL - {h}")
    else:
        lines.append("Hard limits: all PASS")
    if warnings:
        lines.append("Warnings:")
        for w in warnings:
            lines.append(f"  WARN - {w}")
    lines.append("")
    if hard:
        status = "FAIL"
    elif warnings:
        status = f"PASS with {len(warnings)} warning" + ("s" if len(warnings) > 1 else "")
    else:
        status = "PASS"
    lines.append("Status: " + status)
    return "\n".join(lines)


def render_report_markdown(rows, warnings, hard, baseline_source, current_source):
    """GitHub-flavoured markdown version for the job summary/artifact."""
    lines = ["## Performance comparison", ""]
    lines.append(f"- Baseline: {baseline_source}")
    lines.append(f"- Current: {current_source}")
    lines.append("")
    lines.append("| Metric | Baseline | Current | Delta |")
    lines.append("| ------ | -------- | ------- | ----- |")
    for label, b, c, delta, pct, unit in rows:
        lines.append(f"| {label} | {format_cell(b, unit)} | "
                     f"{format_cell(c, unit)} | "
                     f"{format_delta(delta, pct, unit)} |")
    lines.append("")
    for w in warnings:
        lines.append(f"- WARN: {w}")
    for h in hard:
        lines.append(f"- FAIL: {h}")
    if hard:
        status = "FAIL"
    elif warnings:
        status = f"PASS with {len(warnings)} warning" + ("s" if len(warnings) > 1 else "")
    else:
        status = "PASS"
    lines.append("")
    lines.append(f"**Status: {status}**")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Baseline resolution
# ---------------------------------------------------------------------------

def is_git_repo():
    return shutil.which("git") is not None and \
        run(["git", "rev-parse", "--is-inside-work-tree"], cwd=str(ROOT)).returncode == 0


def current_ref():
    r = run(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT))
    return r.stdout.strip() if r.returncode == 0 else "local"


def resolve_base_ref():
    """Return the base ref to compare against, or None."""
    explicit = os.environ.get("WIZARD_BASE_REF")
    if explicit:
        return explicit
    gh_base = os.environ.get("GITHUB_BASE_REF")
    if gh_base:
        return f"origin/{gh_base}"
    if not is_git_repo():
        return None
    for candidate in ("origin/main", "main"):
        if run(["git", "rev-parse", "--verify", candidate],
               cwd=str(ROOT)).returncode == 0:
            return candidate
    return None


def same_commit(base_ref):
    if not is_git_repo():
        return False
    head = run(["git", "rev-parse", "HEAD"], cwd=str(ROOT)).stdout.strip()
    base = run(["git", "rev-parse", base_ref], cwd=str(ROOT)).stdout.strip()
    return bool(head) and head == base


def git_base_metrics(base_ref):
    """Build the base ref in a temporary worktree and measure it.

    Returns a metrics dict, or None when the base cannot be built/measured
    (e.g. it predates the tooling).  Never raises for missing bases.
    """
    if not is_git_repo():
        return None
    tmp_root = Path(tempfile.mkdtemp(prefix="wd-baseline-"))
    worktree = tmp_root / "wt"
    try:
        add = run(["git", "worktree", "add", "--detach", str(worktree),
                   base_ref], cwd=str(ROOT))
        if add.returncode != 0:
            return None
        if not (worktree / "tools" / "build.py").exists():
            return None
        build = run([sys.executable, str(worktree / "tools" / "build.py"),
                     "--clean"], cwd=str(worktree))
        if build.returncode != 0:
            return None
        bench = run([sys.executable, str(worktree / "tools" / "benchmark.py"),
                     "--json"], cwd=str(worktree))
        if bench.returncode != 0:
            return None
        return json.loads(bench.stdout)
    except (OSError, ValueError):
        return None
    finally:
        run(["git", "worktree", "remove", "--force", str(worktree)],
            cwd=str(ROOT))
        run(["git", "worktree", "prune"], cwd=str(ROOT))


def git_show_baseline(base_ref):
    """Read the base branch's committed baseline.json via `git show`."""
    if not is_git_repo():
        return None
    r = run(["git", "show", f"{base_ref}:docs/benchmarks/baseline.json"],
            cwd=str(ROOT))
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def resolve_baseline(explicit=None, baseline_path=None, base_ref_provider=None,
                     same_commit_fn=None, base_metrics_fn=None,
                     show_baseline_fn=None):
    """Return (metrics dict, description) or (None, reason).

    The git-related steps are injectable for tests; defaults are the real
    implementations above.
    """
    baseline_path = baseline_path or BASELINE
    if explicit is not None:
        try:
            data = json.loads(Path(explicit).read_text())
            return data, f"explicit baseline {explicit}"
        except (OSError, ValueError) as exc:
            return None, f"could not load explicit baseline: {exc}"

    base_ref = (base_ref_provider() if base_ref_provider else resolve_base_ref())
    same = same_commit_fn or same_commit
    base_metrics = base_metrics_fn or git_base_metrics
    show_baseline = show_baseline_fn or git_show_baseline
    if base_ref and not same(base_ref):
        metrics = base_metrics(base_ref)
        if metrics:
            return metrics, f"built base {base_ref}"
        metrics = show_baseline(base_ref)
        if metrics:
            return metrics, f"persisted baseline from {base_ref}"

    if baseline_path.exists():
        try:
            data = json.loads(baseline_path.read_text())
            return data, f"persisted baseline {baseline_path}"
        except (OSError, ValueError) as exc:
            return None, f"could not load persisted baseline: {exc}"

    return None, "no baseline available"


# ---------------------------------------------------------------------------

def write_artifacts(text, json_text, markdown_text=None):
    BUILD_DIR.mkdir(exist_ok=True)
    REPORT_TXT.write_text(text)
    if json_text is not None:
        REPORT_JSON.write_text(json_text + "\n")
    if markdown_text is not None:
        REPORT_MD.write_text(markdown_text)


def main():
    parser = argparse.ArgumentParser(description="Report benchmark regressions")
    parser.add_argument("--baseline", metavar="FILE",
                        help="explicit baseline metrics JSON")
    parser.add_argument("--json", action="store_true",
                        help="write build/regression-report.json")
    args = parser.parse_args()

    current = measure()
    baseline, source = resolve_baseline(explicit=args.baseline)

    if baseline is None:
        text = (f"No baseline available ({source}); skipping regression "
                f"comparison.\n")
        print(text)
        print("Current metrics:")
        print(json.dumps(current, sort_keys=True, indent=2))
        markdown = ("## Regression comparison\n\n"
                    f"**No baseline available** ({source}); comparison "
                    "skipped.\n")
        write_artifacts(text,
                        json.dumps(current, sort_keys=True) if args.json else None,
                        markdown)
        return 0

    rows, warnings, hard = compare(baseline, current)
    cur_src = f"{current_ref()} ({os.path.basename(str(BUILD_DIR))})"
    text = render_report(rows, warnings, hard, source, cur_src)
    print(text)
    markdown = render_report_markdown(rows, warnings, hard, source, cur_src)

    if args.json:
        payload = {
            "baseline_source": source,
            "current_source": cur_src,
            "baseline": baseline,
            "current": current,
            "warnings": warnings,
            "hard_failures": hard,
            "status": "FAIL" if hard else ("PASS" if not warnings else "PASS_WITH_WARNINGS"),
        }
        write_artifacts(text, json.dumps(payload, sort_keys=True, indent=2),
                        markdown)
    else:
        write_artifacts(text, None, markdown)

    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())