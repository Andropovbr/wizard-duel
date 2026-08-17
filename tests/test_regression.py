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
from regression import (EXPECTED_SCANLINES, SCANLINE_BUDGET,
                        WARN_KERNEL_SLACK_DECREASE, WARN_KERNEL_WORST_INCREASE,
                        WARN_RAM_GROWTH_BYTES, WARN_ROM_GROWTH_BYTES,
                        compare, format_delta, git_base_metrics,
                        render_report, render_report_markdown,
                        resolve_baseline, warning_for)

BASE = {
    "rom_used": 528,
    "rom_available": 3568,
    "ram_used": 3,
    "ram_available": 125,
    "scanlines": 262,
    "kernel_worst": 56,
    "kernel_best": 44,
    "kernel_budget": 76,
    "kernel_slack": 20,
    "vblank_timer": 44,
    "overscan_timer": 37,
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
        cur["rom_used"] = 612
        rows, _, _ = compare(BASE, cur)
        row = next(r for r in rows if r[0] == "ROM used")
        self.assertEqual(row[3], 84)
        self.assertAlmostEqual(row[4], 84 / 528 * 100.0)

    def test_negative_delta_for_slack_regression(self):
        cur = dict(BASE)
        cur["kernel_slack"] = 12
        rows, _, _ = compare(BASE, cur)
        row = next(r for r in rows if r[0] == "Kernel slack")
        self.assertEqual(row[3], -8)


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
        cur["rom_used"] = 528 + 64
        rows, warnings, hard = compare(BASE, cur)
        text = render_report(rows, warnings, hard, "baseline.json", "HEAD")
        self.assertIn("Status: PASS with 1 warning", text)
        self.assertIn("WARN -", text)

    def test_render_markdown_report(self):
        cur = dict(BASE)
        cur["rom_used"] = 612
        rows, warnings, hard = compare(BASE, cur)
        md = render_report_markdown(rows, warnings, hard, "base", "current")
        self.assertIn("## Performance comparison", md)
        self.assertIn("| ROM used | 528 B | 612 B | +84 B (+15.9%) |", md)
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
        cur["rom_used"] = 528 + 64
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
        self.assertEqual(m["kernel_slack"], 14)  # 76 - 62 (branchless kernel)

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

    def test_history_migration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.csv"
            path.write_text(
                "rom_used,kernel_worst,kernel_budget,kernel_slack\n"
                "528,56,76,20\n")
            self.assertFalse(migrate_history(path))


class TestBaselineResolution(unittest.TestCase):
    def test_explicit_baseline_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "baseline.json"
            path.write_text(json.dumps(BASE))
            metrics, source = resolve_baseline(explicit=str(path))
        self.assertEqual(metrics["rom_used"], 528)
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
        self.assertEqual(metrics["ram_used"], 3)
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