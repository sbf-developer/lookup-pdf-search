from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Word:
    text: str
    norm: str
    stem: str
    phone: str
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    block: int
    line: int


@dataclass(slots=True)
class Sentence:
    text: str
    page: int
    word_start: int
    word_end: int


@dataclass(slots=True)
class Document:
    path: str
    name: str
    page_count: int
    page_sizes: list[tuple[float, float]]
    words: list[Word]
    sentences: list[Sentence]
    has_text: bool
    error: str = ""

    @staticmethod
    def failed(path: str, name: str, message: str) -> Document:
        return Document(
            path=path,
            name=name,
            page_count=0,
            page_sizes=[],
            words=[],
            sentences=[],
            has_text=False,
            error=message,
        )
