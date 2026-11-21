import sys
import tempfile
import unittest
from pathlib import Path

import PySide6  # noqa: F401  # before MuPDF, or Windows crashes on the DLL overlap
import pymupdf as fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pdflookup.pdfio import index_pdf
from pdflookup.search import prepare, search


class IndexTests(unittest.TestCase):
    def test_real_pdf_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "lecture.pdf"
            src = fitz.open()
            page = src.new_page()
            page.insert_text((72, 80), "Data mining is useful.", fontsize=12)
            page.insert_text((72, 110), "The data mine keeps records.", fontsize=12)
            page.insert_text((72, 140), "Database design is different.", fontsize=12)
            src.save(path)
            src.close()

            document = index_pdf(str(path))
            self.assertIsNotNone(document)
            self.assertTrue(document.has_text)
            norms = [word.norm for word in document.words]
            self.assertIn("mining", norms)
            self.assertIn("mine", norms)
            prepared = [prepare(document)]
            exact = search(prepared, "data mining", "exact")
            broad = search(prepared, "data mining", "broad")
            self.assertEqual(len(exact.matches), 1)
            self.assertGreaterEqual(len(broad.matches), 2)
            self.assertLess(broad.elapsed_ms, 100)


if __name__ == "__main__":
    unittest.main()
