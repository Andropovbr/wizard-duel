"""Documentation validation: EN/PT-BR pairs must both exist."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from common import DOCS_DIR

# Required documentation pairs: english path -> portuguese path (relative to
# docs/). Change log entries are discovered dynamically from the en/ dir.
REQUIRED_PAIRS = [
    ("en/architecture.md", "pt-BR/arquitetura.md"),
    ("en/memory-map.md", "pt-BR/mapa-de-memoria.md"),
    ("en/timing.md", "pt-BR/timing.md"),
    ("en/build.md", "pt-BR/build.md"),
    ("benchmarks/latest.md", "benchmarks/latest.md"),
]


class TestDocPairs(unittest.TestCase):
    def test_required_doc_pairs_exist(self):
        missing = []
        for en, pt in REQUIRED_PAIRS:
            if not (DOCS_DIR / en).exists():
                missing.append(f"missing {en}")
            if not (DOCS_DIR / pt).exists():
                missing.append(f"missing {pt}")
        self.assertEqual(missing, [])

    def test_change_log_pairs_exist(self):
        en_dir = DOCS_DIR / "changes" / "en"
        pt_dir = DOCS_DIR / "changes" / "pt-BR"
        if not en_dir.exists():
            self.fail("docs/changes/en/ missing")
        en_files = sorted(p.name for p in en_dir.glob("*.md"))
        pt_files = sorted(p.name for p in pt_dir.glob("*.md"))
        self.assertGreater(len(en_files), 0)
        self.assertEqual(len(en_files), len(pt_files),
                         "change log EN/PT-BR counts differ")


if __name__ == "__main__":
    unittest.main()