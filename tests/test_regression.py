"""Regression comparison tests: deltas, thresholds, hard/soft failures and
baseline resolution.  These tests never touch the network and never modify
committed benchmark artifacts.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from common import ROM_PATH, ROM_LIMIT, RAM_LIMIT
from benchmark import LATEST, migrate_history
from regression import (EXPECTED_SCANLINES, PROJECT_RAM_BUDGET, SCANLINE_BUDGET,
                        RAM_PRESSURE_STRONG_PCT, RAM_PRESSURE_WARN_PCT,
                        WARN_KERNEL_SLACK_DECREASE, WARN_KERNEL_WORST_INCREASE,
                        WARN_RAM_GROWTH_BYTES, WARN_RAM_GROWTH_PCT,
                        WARN_ROM_GROWTH_BYTES, compare, format_delta,
                        git_base_metrics, render_report, render_report_markdown,
                        resolve_baseline, warning_for)

BASE = {
    "rom_used": 1296,
    "rom_available": 2800,
    "ram_used": 48,
    "ram_available": 80,
    "scanlines": 262,
    "kernel_worst": 65,
    "kernel_best": 18,
    "kernel_budget": 76,
    "kernel_slack": 11,
    "vblank_timer": 69,
    "overscan_loop": 8,
}


class TestDeltas(unittest.TestCase):
    def test_equal_metrics_have_zero_deltas_and_pass(self):
        rows, warnings, hard = compare(BASE, dict(BASE))
        for _, _, _, delta, _, _ in rows:
            self.assertEqual(delta, 0)
        self.assertEqual(warnings, [])
        self.assertEqual(hard, [])

    def test_absolute_delta_computed(self):
        cur = dict(BASE)
        cur["rom_used"] = 1380
        rows, _, _ = compare(BASE, cur)
        row = next(r for r in rows if r[0] == "ROM used")
        self.assertEqual(row[3], 84)
        self.assertAlmostEqual(row[4], 84 / 1296 * 100.0)

    def test_negative_delta_for_slack_regression(self):
        cur = dict(BASE)
        cur["kernel_slack"] = -1
        rows, _, _ = compare(BASE, cur)
        row = next(r for r in rows if r[0] == "Kernel slack")
        self.assertEqual(row[3], -12)


class TestFormatting(unittest.TestCase):
    def test_format_delta_positive(self):
        self.assertEqual(format_delta(84, 15.909, "B"), "+84 B (+15.9%)")

    def test_format_delta_zero(self):
        self.assertEqual(format_delta(0, 0.0, "cycles"), "0")

    def test_format_delta_negative(self):
        self.assertEqual(format_delta(-4, -20.0, "cycles"), "-4 cycles (-20.0%)")

    def test_render_report_status_pass(self):
        rows, warnings, hard = compare(BASE, dict(BASE))
        text = render_report(rows, warnings, hard, "baseline.json", "HEAD")
        self.assertIn("Status: PASS", text)
        self.assertIn("ROM used", text)
        self.assertIn("Hard limits: all PASS", text)

    def test_render_report_status_warning(self):
        cur = dict(BASE)
        cur["rom_used"] = 1296 + 64
        rows, warnings, hard = compare(BASE, cur)
        text = render_report(rows, warnings, hard, "baseline.json", "HEAD")
        self.assertIn("Status: PASS with 1 warning", text)
        self.assertIn("WARN -", text)

    def test_render_markdown_report(self):
        cur = dict(BASE)
        cur["rom_used"] = 1380
        rows, warnings, hard = compare(BASE, cur)
        md = render_report_markdown(rows, warnings, hard, "base", "current")
        self.assertIn("## Performance comparison", md)
        self.assertIn("| ROM used | 1296 B | 1380 B | +84 B (+6.5%) |", md)
        self.assertIn("**Status: PASS with 1 warning**", md)


class TestWarningThresholds(unittest.TestCase):
    def test_rom_growth_bytes_warns(self):
        warning = warning_for("rom_used", 528, 528 + WARN_ROM_GROWTH_BYTES + 1)
        self.assertIsNotNone(warning)
        self.assertIn("ROM grew", warning)

    def test_rom_growth_within_bytes_no_warning(self):
        self.assertIsNone(warning_for("rom_used", 528, 528 + 5))

    def test_rom_growth_percent_warns_even_when_bytes_small(self):
        # 10 % growth on a small base triggers the percentage threshold.
        warning = warning_for("rom_used", 100, 110)
        self.assertIsNotNone(warning)
        self.assertIn("10.0%", warning)

    def test_ram_growth_warns(self):
        warning = warning_for("ram_used", 3, 3 + WARN_RAM_GROWTH_BYTES + 1)
        self.assertIsNotNone(warning)
        self.assertIn("grew", warning)

    def test_ram_growth_within_bytes_no_warning(self):
        # growth under WARN_RAM_GROWTH_BYTES, low pct and far from the
        # pressure bands
        self.assertIsNone(warning_for("ram_used", 48, 48 + 3))

    def test_ram_growth_percent_warns_when_bytes_small(self):
        # On a small base, a large percentage growth triggers the % threshold
        # even though the byte growth is under WARN_RAM_GROWTH_BYTES.
        warning = warning_for("ram_used", 4, 6)
        self.assertIsNotNone(warning)
        self.assertIn("50.0%", warning)

    def test_ram_pressure_warns_at_75_percent(self):
        # 96/128 = 75% hits the warning band without exceeding the project
        # budget (64), so it must be a soft warning, not a hard failure.
        warning = warning_for("ram_used", 10, 96)
        self.assertIsNotNone(warning)
        self.assertIn(f"{RAM_PRESSURE_WARN_PCT:.0f}%", warning)

    def test_ram_pressure_strong_warns_at_90_percent(self):
        warning = warning_for("ram_used", 10, 115)
        self.assertIsNotNone(warning)
        self.assertIn(f"{RAM_PRESSURE_STRONG_PCT:.0f}%", warning)

    def test_ram_no_warning_below_pressure_and_growth(self):
        self.assertIsNone(warning_for("ram_used", 48, 50))

    def test_kernel_worst_increase_warns(self):
        warning = warning_for("kernel_worst", 56,
                              56 + WARN_KERNEL_WORST_INCREASE + 1)
        self.assertIsNotNone(warning)
        self.assertIn("increased by", warning)

    def test_kernel_slack_decrease_warns(self):
        warning = warning_for("kernel_slack", 20,
                              20 - WARN_KERNEL_SLACK_DECREASE - 1)
        self.assertIsNotNone(warning)
        self.assertIn("reduced by", warning)

    def test_compare_surfaces_warnings(self):
        cur = dict(BASE)
        cur["rom_used"] = 1296 + 64
        _, warnings, _ = compare(BASE, cur)
        self.assertEqual(len(warnings), 1)


class TestHardRegressions(unittest.TestCase):
    def test_rom_over_limit_fails(self):
        cur = dict(BASE)
        cur["rom_used"] = ROM_LIMIT + 1
        _, _, hard = compare(BASE, cur)
        self.assertTrue(any("ROM" in h for h in hard))

    def test_ram_over_limit_fails(self):
        cur = dict(BASE)
        cur["ram_used"] = RAM_LIMIT + 1
        _, _, hard = compare(BASE, cur)
        self.assertTrue(any("RAM" in h for h in hard))

    def test_ram_over_project_budget_fails(self):
        # Exceeding the current round's RAM budget is a hard regression even
        # though 65 bytes is well inside the 128-byte hardware limit.
        cur = dict(BASE)
        cur["ram_used"] = PROJECT_RAM_BUDGET + 1
        _, _, hard = compare(BASE, cur)
        self.assertTrue(any("project budget" in h for h in hard))

    def test_ram_within_project_budget_passes(self):
        cur = dict(BASE)
        cur["ram_used"] = PROJECT_RAM_BUDGET
        _, _, hard = compare(BASE, cur)
        self.assertTrue(all("RAM" not in h for h in hard))

    def test_kernel_over_budget_fails(self):
        cur = dict(BASE)
        cur["kernel_worst"] = SCANLINE_BUDGET + 1
        _, _, hard = compare(BASE, cur)
        self.assertTrue(any("kernel worst case" in h for h in hard))

    def test_scanlines_invalid_fails(self):
        cur = dict(BASE)
        cur["scanlines"] = EXPECTED_SCANLINES - 1
        _, _, hard = compare(BASE, cur)
        self.assertTrue(any("scanline count" in h for h in hard))


class TestKernelSlackMetric(unittest.TestCase):
    @unittest.skipUnless(ROM_PATH.exists(), "ROM not built")
    def test_measure_reports_slack(self):
        from benchmark import measure
        m = measure()
        self.assertEqual(m["kernel_slack"],
                         m["kernel_budget"] - m["kernel_worst"])
        self.assertEqual(m["kernel_slack"], 22)  # 76 - 54 (event line)

    def test_latest_report_documents_slack(self):
        self.assertTrue(LATEST.exists())
        self.assertIn("Kernel slack", LATEST.read_text())

    def test_history_migration_adds_slack_column(self):
        import csv
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.csv"
            path.write_text(
                "rom_used,kernel_worst,kernel_budget\n528,56,76\n")
            self.assertTrue(migrate_history(path))
            with path.open(newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            self.assertIn("kernel_slack", reader.fieldnames)
            self.assertEqual(rows[0]["kernel_slack"], "20")
            self.assertEqual(rows[0]["rom_used"], "528")

    def test_history_migration_adds_vblank_columns(self):
        import csv
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.csv"
            # A Round 5 file already has kernel_slack but predates the
            # Round 6 VBLANK work/margin columns.
            path.write_text(
                "rom_used,kernel_worst,kernel_budget,kernel_slack\n"
                "528,56,76,20\n")
            self.assertTrue(migrate_history(path))
            with path.open(newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            self.assertIn("vblank_work", reader.fieldnames)
            self.assertIn("vblank_margin", reader.fieldnames)
            self.assertEqual(rows[0]["kernel_slack"], "20")
            self.assertEqual(rows[0]["vblank_work"], "")

    def test_history_migration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.csv"
            header = ("rom_used,rom_available,ram_used,ram_available,"
                      "scanlines,kernel_worst,kernel_best,kernel_budget,"
                      "kernel_slack,vblank_timer,vblank_work,vblank_margin,"
                      "overscan_loop")
            path.write_text(header + "\n528,3568,3,125,262,56,44,76,20,44,,,\n")
            self.assertFalse(migrate_history(path))


class TestBaselineResolution(unittest.TestCase):
    def test_explicit_baseline_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "baseline.json"
            path.write_text(json.dumps(BASE))
            metrics, source = resolve_baseline(explicit=str(path))
        self.assertEqual(metrics["rom_used"], 1296)
        self.assertIn("explicit baseline", source)

    def test_git_built_base_preferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline_path = Path(tmp) / "none.json"
            metrics, source = resolve_baseline(
                baseline_path=baseline_path,
                base_ref_provider=lambda: "origin/main",
                same_commit_fn=lambda ref: False,
                base_metrics_fn=lambda ref: {"rom_used": 512},
                show_baseline_fn=lambda ref: None)
        self.assertEqual(metrics["rom_used"], 512)
        self.assertIn("built base", source)

    def test_git_show_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline_path = Path(tmp) / "none.json"
            metrics, source = resolve_baseline(
                baseline_path=baseline_path,
                base_ref_provider=lambda: "origin/main",
                same_commit_fn=lambda ref: False,
                base_metrics_fn=lambda ref: None,
                show_baseline_fn=lambda ref: {"rom_used": 500})
        self.assertEqual(metrics["rom_used"], 500)
        self.assertIn("persisted baseline from", source)

    def test_persisted_baseline_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline_path = Path(tmp) / "baseline.json"
            baseline_path.write_text(json.dumps(BASE))
            metrics, source = resolve_baseline(
                baseline_path=baseline_path,
                base_ref_provider=lambda: None)
        self.assertEqual(metrics["ram_used"], 48)
        self.assertIn("persisted baseline", source)

    def test_no_baseline_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics, source = resolve_baseline(
                baseline_path=Path(tmp) / "missing.json",
                base_ref_provider=lambda: None)
        self.assertIsNone(metrics)
        self.assertIn("no baseline available", source)

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_git_base_metrics_missing_ref_returns_none(self):
        self.assertIsNone(git_base_metrics("definitely-not-a-real-ref"))


if __name__ == "__main__":
    unittest.main()