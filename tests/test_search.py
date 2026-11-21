import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pdflookup.model import Document
from pdflookup.pdfio import merge_line_hyphens
from pdflookup.search import prepare, preview_text, search
from pdflookup.textutil import build_sentences, make_word, phonetic_norm, split_token, stem_token


def document_from_lines(lines: list[str], name: str = "notes.pdf") -> Document:
    words = []
    y = 0.0
    for line_index, line in enumerate(lines):
        x = 72.0
        for token in line.split():
            words.append(make_word(token, 0, x, y, x + 48, y + 14, 0, line_index))
            x += 52
        y += 22
    return Document(
        path=name,
        name=name,
        page_count=1,
        page_sizes=[(612, 792)],
        words=words,
        sentences=build_sentences(words),
        has_text=bool(words),
    )


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.doc = document_from_lines(
            [
                "Data mining is useful.",
                "The data mine keeps records.",
                "Database design is different.",
                "Call the fone after class.",
                "Network protocols matter here.",
                "A large data of the mining project failed.",
            ]
        )
        self.prepared = [prepare(self.doc)]

    def test_stems_mining_to_mine(self):
        self.assertEqual(stem_token("mining"), stem_token("mine"))

    def test_phone_sounds_like_fone(self):
        self.assertEqual(phonetic_norm("phone"), phonetic_norm("fone"))
        self.assertNotEqual(phonetic_norm("data"), phonetic_norm("date"))

    def test_exact_finds_phrase_only(self):
        result = search(self.prepared, "data mining", "exact")
        self.assertEqual(len(result.matches), 1)
        words = [self.doc.words[i].norm for i in result.matches[0].hits]
        self.assertEqual(words, ["data", "mining"])

    def test_broad_finds_data_mine_and_ranks_exact_first(self):
        result = search(self.prepared, "data mining", "broad")
        found = [" ".join(self.doc.words[i].norm for i in match.hits) for match in result.matches]
        self.assertIn("data mining", found)
        self.assertIn("data mine", found)
        self.assertEqual(found[0], "data mining")
        self.assertNotIn("database design", found)
        self.assertFalse(any(item.startswith("database") for item in found))

    def test_exact_keeps_order_and_broad_allows_either_order(self):
        exact = search(self.prepared, "mining data", "exact")
        exact_found = [" ".join(self.doc.words[i].norm for i in match.hits) for match in exact.matches]
        self.assertNotIn("data mining", exact_found)
        broad = search(self.prepared, "mining data", "broad")
        broad_found = [" ".join(self.doc.words[i].norm for i in match.hits) for match in broad.matches]
        self.assertIn("data mining", broad_found)

    def test_nearby_words_match_and_distant_words_do_not(self):
        filler = " ".join(["note"] * 30)
        doc = document_from_lines(
            [
                "ERP systems run in the cloud today.",
                "The cloud hosts the ERP suite.",
                f"ERP is a system. {filler} cloud is elsewhere.",
                "Only ERP appears in this sentence.",
            ]
        )
        prepared = [prepare(doc)]
        broad = search(prepared, "ERP cloud", "broad", proximity=8)
        texts = [doc.sentences[match.sentence_index].text for match in broad.matches]
        self.assertTrue(any(text.startswith("ERP systems run") for text in texts))
        self.assertTrue(any(text.startswith("The cloud hosts") for text in texts))
        self.assertFalse(any("note" in text for text in texts))
        self.assertFalse(any(text.startswith("Only ERP") for text in texts))
        exact = search(prepared, "ERP cloud", "exact", proximity=8)
        exact_texts = [doc.sentences[match.sentence_index].text for match in exact.matches]
        self.assertTrue(any(text.startswith("ERP systems run") for text in exact_texts))
        self.assertFalse(any(text.startswith("The cloud hosts") for text in exact_texts))
        tight = search(prepared, "ERP cloud", "broad", proximity=0)
        tight_texts = [doc.sentences[match.sentence_index].text for match in tight.matches]
        self.assertEqual(tight_texts, [])

    def test_preview_stops_at_the_character_limit(self):
        result = search(self.prepared, "data mining", "exact")
        text = preview_text(self.doc, result.matches[0], 40)
        self.assertTrue(text.endswith("…"))
        self.assertLessEqual(len(text), 41)
        self.assertTrue(text.lower().startswith("data mining"))

    def test_broad_gap_and_exact_gap(self):
        broad = search(self.prepared, "data mining", "broad")
        loose = [
            match
            for match in broad.matches
            if self.doc.words[match.hits[0]].norm == "data" and match.gap > 0
        ]
        self.assertTrue(loose)
        exact = search(self.prepared, "data mining", "exact")
        self.assertTrue(all(match.gap == 0 for match in exact.matches))

    def test_soundalike_and_typo(self):
        phone = search(self.prepared, "phone", "broad")
        self.assertTrue(any(self.doc.words[match.hits[0]].norm == "fone" for match in phone.matches))
        typo = search(self.prepared, "netwrok", "broad")
        self.assertTrue(any(self.doc.words[match.hits[0]].norm == "network" for match in typo.matches))
        exact = search(self.prepared, "netwrok", "exact")
        self.assertEqual(exact.matches, [])

    def test_following_sentence_is_the_next_line(self):
        result = search(self.prepared, "data mining", "exact")
        match = result.matches[0]
        following = self.doc.sentences[match.sentence_index + 1]
        self.assertIn("mine", following.text)

    def test_slide_lines_without_periods_are_separate(self):
        doc = document_from_lines(["Intro to ML", "Supervised learning", "Loss functions"])
        self.assertEqual(len(doc.sentences), 3)
        self.assertEqual(doc.sentences[1].text, "Supervised learning")

    def test_split_keeps_sentence_punctuation(self):
        self.assertEqual(split_token("useful."), ["useful."])
        self.assertEqual(split_token("data-mining"), ["data", "mining"])

    def test_line_break_hyphen_joins(self):
        merged = merge_line_hyphens(
            [
                ("comput-", 0, 0, 40, 10, 0, 0, 0),
                ("ing", 0, 20, 20, 30, 0, 1, 0),
                ("systems", 24, 20, 70, 30, 0, 1, 1),
            ]
        )
        self.assertEqual(merged[0][0], "computing")
        self.assertEqual(merged[1][0], "systems")

    def test_search_stays_fast_on_a_long_text(self):
        line = "Data mining is useful for the data mine and the later summary."
        doc = document_from_lines([line] * 4000)
        result = search([prepare(doc)], "data mining", "broad")
        self.assertLess(result.elapsed_ms, 250)
        self.assertGreater(len(result.matches), 0)


if __name__ == "__main__":
    unittest.main()
