"""Title/abstract extraction on the layouts that broke it (synthetic text, no publisher PDFs)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from envreview import manuscript as M  # noqa: E402

ELSEVIER = """Review
A study of nitrite partitioning in mainstream anammox reactors
Jane Doe a, John Roe b
a School of Engineering, Some University
H I G H L I G H T S
G R A P H I C A L  A B S T R A C T
• A highlight that is not the abstract.
A R T I C L E  I N F O
A B S T R A C T
Mainstream anammox provides a low-carbon pathway for nitrogen removal. Here we show that
nitrite partitioning governs the process and that comammox
* Corresponding authors.
E-mail addresses: j.doe@uni.edu (J. Doe).
Contents lists available at ScienceDirect
Water Research
journal homepage: www.elsevier.com/locate/watres
https://doi.org/10.1016/j.watres.2026.000000
Received 1 April 2026; Accepted 2 June 2026
0043-1354/© 2026 The Author(s). Published by Elsevier Ltd.

occupation reshapes competition among nitrifiers, which en-
hances stability in long-term operation.
1. Introduction
Body text.
"""


class Extraction(unittest.TestCase):
    def test_spaced_heading_footer_and_graphical_abstract(self):
        a = M.guess_abstract(ELSEVIER, title="A study of nitrite partitioning in mainstream")
        self.assertTrue(a.startswith("Mainstream anammox provides"))
        self.assertIn("comammox occupation reshapes competition", a)   # joined across the footer
        self.assertNotIn("Corresponding", a)
        self.assertNotIn("highlight", a.lower())
        self.assertTrue(a.endswith("long-term operation."))

    def test_line_end_hyphen_joined_only_when_the_document_says_so(self):
        text = "Abstract: We enhan-\nce reasoning and use expert-\nled review. We enhance it.\nKeywords: x"
        self.assertEqual(M.guess_abstract(text), "We enhance reasoning and use expert-led review. "
                                                  "We enhance it.")

    def test_soft_hyphen_removed(self):
        self.assertEqual(M._clean("nitro­\ngen re­moval"), "nitrogen removal")

    def test_editorial_manager_cover_page(self):
        text = ("Manuscript Number: WR1\nAbstract:\nPollutants threaten ecosystems. We review "
                "machine learning for them.\nPowered by Editorial Manager® and ProduXion Manager®\n"
                "Click here to access/download\nHighlights\n• x")
        self.assertEqual(M.guess_abstract(text),
                         "Pollutants threaten ecosystems. We review machine learning for them.")

    def test_docx(self):
        import docx
        d = docx.Document()
        for p in ["A docx manuscript on wastewater treatment emissions", "Abstract",
                  "We measured nitrous oxide at ten plants.", "Introduction", "Body."]:
            d.add_paragraph(p)
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "ms.docx"
            d.save(f)
            r = M.load(f)
        self.assertEqual(r["title"], "A docx manuscript on wastewater treatment emissions")
        self.assertEqual(r["abstract"], "We measured nitrous oxide at ten plants.")


if __name__ == "__main__":
    unittest.main()
