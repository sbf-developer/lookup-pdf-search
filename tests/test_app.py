import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from pdflookup.window import MainWindow
import pymupdf as fitz


def _slides(folder: Path) -> Path:
    path = folder / "slides.pdf"
    src = fitz.open()
    page = src.new_page()
    page.insert_text((72, 90), "Cloud platforms host the class data set.", fontsize=12)
    page.insert_text((72, 120), "Nothing here is about mining.", fontsize=12)
    src.save(path)
    src.close()
    return path


def _pdf(folder: Path) -> Path:
    path = folder / "lecture.pdf"
    src = fitz.open()
    page = src.new_page()
    page.insert_text((72, 90), "Data mining is useful in this course.", fontsize=12)
    page.insert_text((72, 120), "The data mine keeps the records.", fontsize=12)
    page.insert_text((72, 150), "The following sentence explains the result.", fontsize=12)
    src.save(path)
    src.close()
    return path


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._session = tempfile.TemporaryDirectory()
        os.environ["PDFLOOKUP_SESSION_DIR"] = cls._session.name
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls._session.cleanup()

    def test_search_follows_into_the_sidebar_and_page(self):
        with tempfile.TemporaryDirectory() as folder:
            pdf = _pdf(Path(folder))
            window = MainWindow()
            window.show()
            window.add_paths([str(pdf)])
            deadline = time.time() + 8
            while time.time() < deadline and not window.docs:
                self.app.processEvents()
                time.sleep(0.02)
            self.app.processEvents()
            self.assertTrue(window.docs, "PDF did not finish indexing")
            self.assertTrue(window.docs[0].has_text)
            window.broad_btn.setChecked(True)
            window.search.setText("data mining")
            window._run_search()
            self.app.processEvents()
            self.assertGreaterEqual(len(window.matches), 2)
            self.assertIn("FOLLOWING", window.reader.toHtml())
            self.assertIn("data mine", window.reader.toPlainText().lower())
            self.assertTrue(window.viewer.canvas.pixmap() is not None)
            self.assertFalse(window.viewer.canvas.pixmap().isNull())
            self._assert_highlight_on_words(window)
            window.viewer.zoom_in()
            window.viewer.zoom_in()
            self.app.processEvents()
            self.assertGreater(window.viewer.holder.height(), window.viewer.scroll.viewport().height())
            bar = window.viewer.scroll.verticalScrollBar()
            bar.setValue(0)
            window.viewer._scroll_by(0, -160, False)
            self.assertGreater(bar.value(), 0)
            window.viewer.close_all()
            window.close()

    def test_all_and_each_pdf_filter_the_results(self):
        with tempfile.TemporaryDirectory() as folder:
            notes = _pdf(Path(folder))
            slides = _slides(Path(folder))
            window = MainWindow()
            window.show()
            window.add_paths([str(notes), str(slides)])
            deadline = time.time() + 8
            while time.time() < deadline and len(window.docs) < 2:
                self.app.processEvents()
                time.sleep(0.02)
            self.app.processEvents()
            self.assertEqual(len(window.docs), 2)
            window.broad_btn.setChecked(True)
            window.search.setText("data")
            notes_index = next(index for index, doc in enumerate(window.docs) if doc.name == "lecture.pdf")
            slides_index = next(index for index, doc in enumerate(window.docs) if doc.name == "slides.pdf")
            window._on_chip(10_000)
            self.app.processEvents()
            names = {window._searched[match.doc_index].doc.name for match in window.matches}
            self.assertIn("lecture.pdf", names)
            self.assertIn("slides.pdf", names)
            window._on_chip(slides_index)
            self.app.processEvents()
            self.assertTrue(window.matches)
            self.assertTrue(all(window._searched[match.doc_index].doc.name == "slides.pdf" for match in window.matches))
            self.assertEqual(Path(window.viewer.path).name, "slides.pdf")
            window._on_chip(notes_index)
            self.app.processEvents()
            self.assertTrue(all(window._searched[match.doc_index].doc.name == "lecture.pdf" for match in window.matches))
            self.assertEqual(Path(window.viewer.path).name, "lecture.pdf")
            window.viewer.close_all()
            window.close()

    def _assert_highlight_on_words(self, window):
        match = window.matches[0]
        doc = window._searched[match.doc_index].doc
        target = doc.words[match.hits[0]]
        image = window.viewer.canvas.pixmap().toImage()
        dpr = image.devicePixelRatio() or 1
        scale = window.viewer._render_scale
        hits = []
        for y in range(0, image.height(), 2):
            for x in range(0, image.width(), 3):
                color = image.pixelColor(x, y)
                if color.red() > 200 and color.green() > 150 and (color.red() - color.blue()) > 50:
                    hits.append((x / (scale * dpr), y / (scale * dpr)))
                    break
        self.assertTrue(hits, "highlight was not drawn on the page")
        ys = [point[1] for point in hits]
        mid = sorted(ys)[len(ys) // 2]
        self.assertGreater(mid, target.y0 - 4)
        self.assertLess(mid, target.y1 + 4)


if __name__ == "__main__":
    unittest.main()
