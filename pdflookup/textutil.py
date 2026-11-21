from __future__ import annotations

import re
import threading
from functools import lru_cache

import snowballstemmer

from pdflookup.model import Sentence, Word

_stem_local = threading.local()

_LIGATURES = str.maketrans(
    {
        "\ufb00": "ff",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
        "\u2019": "'",
        "\u2018": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u00a0": " ",
    }
)

_TOKEN = re.compile(r"[A-Za-z0-9]+")

_SUBS = (
    ("tion", "shn"),
    ("sion", "shn"),
    ("ph", "f"),
    ("gh", "g"),
    ("kn", "n"),
    ("wr", "r"),
    ("ck", "k"),
    ("wh", "w"),
    ("qu", "kw"),
    ("x", "ks"),
)

_ABBREV = {
    "mr",
    "mrs",
    "ms",
    "dr",
    "prof",
    "sr",
    "jr",
    "st",
    "fig",
    "eq",
    "vol",
    "pp",
    "no",
    "nos",
    "al",
    "etc",
    "vs",
    "cf",
    "approx",
    "dept",
    "est",
    "ed",
    "eds",
    "e.g",
    "i.e",
    "u.s",
    "u.k",
    "u.s.a",
    "eg",
    "ie",
    "ph.d",
    "m.sc",
    "b.sc",
}


def _stemmer():
    stemmer = getattr(_stem_local, "stemmer", None)
    if stemmer is None:
        stemmer = snowballstemmer.stemmer("english")
        _stem_local.stemmer = stemmer
    return stemmer


@lru_cache(maxsize=50000)
def stem_token(token: str) -> str:
    if not token or token.isdigit() or len(token) <= 2:
        return token
    return _stemmer().stemWord(token)


def phonetic_norm(token: str) -> str:
    chars: list[str] = []
    i = 0
    while i < len(token):
        matched = False
        for src, dst in _SUBS:
            if token.startswith(src, i):
                chars.append(dst)
                i += len(src)
                matched = True
                break
        if not matched:
            chars.append(token[i])
            i += 1
    return "".join(chars)


def clean_text(text: str) -> str:
    return text.translate(_LIGATURES)


def tokenize(text: str) -> list[str]:
    return [piece.lower() for piece in _TOKEN.findall(clean_text(text))]


def split_token(text: str) -> list[str]:
    """Split a PDF word into searchable pieces, keeping end punctuation."""
    raw = clean_text(text).strip()
    matches = list(_TOKEN.finditer(raw))
    if not matches:
        return []
    pieces: list[str] = []
    last = len(matches) - 1
    for index, match in enumerate(matches):
        piece = match.group()
        if index == last:
            tail = raw[match.end() :]
            if "!" in tail:
                piece += "!"
            elif "?" in tail:
                piece += "?"
            elif "." in tail:
                piece += "."
        pieces.append(piece)
    return pieces


def make_word(
    display: str,
    page: int,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    block: int,
    line: int,
) -> Word:
    norms = tokenize(display)
    norm = norms[0] if norms else ""
    return Word(
        text=display,
        norm=norm,
        stem=stem_token(norm),
        phone=phonetic_norm(norm),
        page=page,
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        block=block,
        line=line,
    )


def ends_sentence(text: str) -> bool:
    trimmed = text.strip().rstrip("\"')]}”’")
    if not trimmed.endswith((".", "!", "?")):
        return False
    core = trimmed
    while core.endswith((".", "!", "?")):
        core = core[:-1]
    core = core.lower()
    if not core or core in _ABBREV:
        return False
    if len(core) == 1 and core.isalpha():
        return False
    if core.count(".") >= 1 and len(core) <= 7:
        return False
    return True


def build_sentences(words: list[Word]) -> list[Sentence]:
    if not words:
        return []
    sentences: list[Sentence] = []
    chunk_start = 0
    total = len(words)
    for index in range(1, total + 1):
        boundary = index == total or words[index].page != words[index - 1].page or words[index].block != words[index - 1].block
        if not boundary:
            continue
        _emit_chunk(words, chunk_start, index, sentences)
        chunk_start = index
    return sentences


def _emit_chunk(words: list[Word], start: int, end: int, out: list[Sentence]) -> None:
    has_punct = any(ends_sentence(words[i].text) for i in range(start, end))
    if has_punct:
        cursor = start
        for index in range(start, end):
            if ends_sentence(words[index].text):
                _add_sentence(words, cursor, index + 1, out)
                cursor = index + 1
        if cursor < end:
            _add_sentence(words, cursor, end, out)
        return
    cursor = start
    for index in range(start, end - 1):
        if words[index + 1].line != words[index].line:
            _add_sentence(words, cursor, index + 1, out)
            cursor = index + 1
    _add_sentence(words, cursor, end, out)


def _add_sentence(words: list[Word], start: int, end: int, out: list[Sentence]) -> None:
    if start >= end:
        return
    text = " ".join(words[i].text for i in range(start, end))
    out.append(Sentence(text=text, page=words[start].page, word_start=start, word_end=end))
