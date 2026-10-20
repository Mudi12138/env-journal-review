"""Literature search helpers: DOI parsing, year ranges, and linking PDFs by DOI suffix."""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from envreview import lit  # noqa: E402


class FakeIndex:
    def __init__(self, dois, journals):
        self.doi = np.array([d.lower() for d in dois])
        self.d = pd.DataFrame({"DOI": dois, "journal_std": journals})

    def row(self, doi):
        i = np.where(self.doi == doi.lower())[0]
        return int(i[0]) if len(i) else None


class Lit(unittest.TestCase):
    def test_norm_doi(self):
        self.assertEqual(lit.norm_doi("https://doi.org/10.1021/ACS.EST.4c10919."), "10.1021/acs.est.4c10919")
        self.assertEqual(lit.norm_doi(" doi:10.1038/s41558-023-01866-3 "), "10.1038/s41558-023-01866-3")
        self.assertIsNone(lit.norm_doi("not a doi"))

    def test_years(self):
        self.assertEqual(lit.years("2020-2025"), (2020, 2025))
        self.assertEqual(lit.years("2020-"), (2020, None))
        self.assertEqual(lit.years("-2019"), (None, 2019))
        self.assertEqual(lit.years("2023"), (2023, 2023))
        self.assertEqual(lit.years(None), (None, None))
        with self.assertRaises(SystemExit):
            lit.years("20x5")

    def test_scan_links_by_suffix_anywhere_and_skips_the_rest(self):
        ix = FakeIndex(["10.1021/acs.est.4c10919", "10.1038/s41558-023-01866-3", "10.1016/j.watres.2024.1"],
                       ["Environmental Science & Technology", "Nature Climate Change", "Water Research"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "batch1").mkdir()
            (root / "batch1" / "ACS.EST.4c10919.pdf").write_bytes(b"%PDF" + b"x" * 2000)    # case ignored
            (root / "s41558-023-01866-3.pdf").write_bytes(b"x" * 10)                          # broken
            (root / "other.pdf").write_bytes(b"x" * 2000)                                    # not indexed
            lit.PDF_MAP = root / "map.json"
            res = lit.scan_pdfs(ix, root)
            pdfs = lit.load_pdf_map()
            self.assertEqual(res["linked_pdfs"], 1)
            self.assertEqual(res["too_small_skipped"], 1)
            self.assertEqual(res["pdfs_not_in_index"], 1)
            self.assertEqual(lit.pdf_path("10.1021/acs.est.4c10919", pdfs).name, "ACS.EST.4c10919.pdf")
            self.assertIsNone(lit.pdf_path("10.1016/j.watres.2024.1", pdfs))


if __name__ == "__main__":
    unittest.main()
