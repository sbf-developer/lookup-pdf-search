from __future__ import annotations

from pathlib import Path

# Qt has to load before MuPDF. On Windows the two ship overlapping DLLs,
# and importing MuPDF first crashes the process.
import PySide6  # noqa: F401
import pymupdf as fitz

from pdflookup.model import Document, Word
from pdflookup.textutil import build_sentences, clean_text, make_word, split_token


def index_pdf(path: str, progress=None, should_stop=None) -> Document | None:
    file_path = Path(path)
    name = file_path.name
    try:
        source = fitz.open(path)
    except Exception as exc:
        return Document.failed(str(file_path), name, str(exc))
    try:
        if source.needs_pass:
            return Document.failed(str(file_path.resolve()), name, "This PDF is password protected.")
        page_count = source.page_count
        sizes: list[tuple[float, float]] = []
        words: list[Word] = []
        for page_index in range(page_count):
            if should_stop and should_stop():
                return None
            if progress:
                progress(name, page_index + 1, page_count)
            page = source.load_page(page_index)
            rect = page.rect
            sizes.append((float(rect.width), float(rect.height)))
            words.extend(_words_on_page(page, page_index))
        sentences = build_sentences(words)
        resolved = str(file_path.resolve())
        if words:
            return Document(
                path=resolved,
                name=name,
                page_count=page_count,
                page_sizes=sizes,
                words=words,
                sentences=sentences,
                has_text=True,
            )
        return Document(
            path=resolved,
            name=name,
            page_count=page_count,
            page_sizes=sizes,
            words=[],
            sentences=[],
            has_text=False,
            error="No text layer. Scans and photos cannot be searched.",
        )
    except Exception as exc:
        return Document.failed(str(file_path), name, str(exc))
    finally:
        source.close()


def _raw_words(page):
    flags = 0
    if hasattr(fitz, "TEXT_DEHYPHENATE"):
        flags |= fitz.TEXT_DEHYPHENATE
    try:
        return page.get_text("words", sort=True, flags=flags) or []
    except TypeError:
        return page.get_text("words") or []


def _map_rect(page, x0: float, y0: float, x1: float, y1: float):
    if not page.rotation:
        return x0, y0, x1, y1
    try:
        rect = fitz.Rect(x0, y0, x1, y1) * page.rotation_matrix
        return float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)
    except Exception:
        return x0, y0, x1, y1


def merge_line_hyphens(items: list[tuple]) -> list[tuple]:
    merged = []
    index = 0
    while index < len(items):
        text, x0, y0, x1, y1, block, line, word_no = items[index]
        if text.endswith("-") and index + 1 < len(items):
            next_text, nx0, ny0, nx1, ny1, next_block, next_line, _next_no = items[index + 1]
            left = text[:-1]
            if (
                left
                and left[-1].isalpha()
                and next_text[:1].islower()
                and next_block == block
                and next_line != line
            ):
                merged.append(
                    (
                        left + next_text,
                        min(x0, nx0),
                        min(y0, ny0),
                        max(x1, nx1),
                        max(y1, ny1),
                        block,
                        line,
                        word_no,
                    )
                )
                index += 2
                continue
        merged.append(items[index])
        index += 1
    return merged


def _words_on_page(page, page_index: int) -> list[Word]:
    items = []
    for entry in _raw_words(page):
        x0, y0, x1, y1, text, block, line, word_no = entry[:8]
        text = clean_text(str(text)).strip()
        if not text:
            continue
        x0, y0, x1, y1 = _map_rect(page, float(x0), float(y0), float(x1), float(y1))
        items.append((text, x0, y0, x1, y1, int(block), int(line), int(word_no)))
    items.sort(key=lambda item: (item[5], item[6], item[7]))
    items = merge_line_hyphens(items)
    words: list[Word] = []
    for text, x0, y0, x1, y1, block, line, _word_no in items:
        pieces = split_token(text)
        if not pieces:
            continue
        total = sum(len(piece) for piece in pieces) or 1
        width = max(0.1, x1 - x0)
        cursor = x0
        for piece in pieces:
            piece_width = width * (len(piece) / total)
            words.append(
                make_word(
                    piece,
                    page_index,
                    cursor,
                    y0,
                    cursor + piece_width,
                    y1,
                    block,
                    line,
                )
            )
            cursor += piece_width
    return words
