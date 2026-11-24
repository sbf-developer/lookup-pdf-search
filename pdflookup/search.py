from __future__ import annotations

import bisect
import time
from dataclasses import dataclass
from itertools import product

from pdflookup.model import Document
from pdflookup.textutil import phonetic_norm, stem_token, tokenize

MAX_RESULTS = 200
_MAX_COLLECT = 2500
_BROAD_GAP = 3

_INFLECTIONS = {
    "ing",
    "ings",
    "ed",
    "es",
    "s",
    "er",
    "ers",
    "ly",
    "tion",
    "ment",
    "ness",
    "able",
    "ible",
    "ive",
    "al",
    "en",
}


@dataclass(slots=True)
class Prepared:
    doc: Document
    postings: dict[str, list[int]]
    norms: dict[str, tuple[str, str]]
    sorted_norms: tuple[str, ...]


@dataclass(slots=True)
class Match:
    doc_index: int
    page: int
    sentence_index: int
    hits: tuple[int, ...]
    score: int
    gap: int


@dataclass(slots=True)
class SearchHits:
    matches: list[Match]
    truncated: bool
    elapsed_ms: float


def prepare(doc: Document) -> Prepared:
    postings: dict[str, list[int]] = {}
    norms: dict[str, tuple[str, str]] = {}
    for index, word in enumerate(doc.words):
        if not word.norm:
            continue
        postings.setdefault(word.norm, []).append(index)
        norms.setdefault(word.norm, (word.stem, word.phone))
    return Prepared(doc=doc, postings=postings, norms=norms, sorted_norms=tuple(sorted(postings)))


def _prefix_variant(a: str, b: str) -> bool:
    if len(a) > len(b):
        a, b = b, a
    if len(a) < 4 or len(b) == len(a) or len(b) - len(a) > 5:
        return False
    if not b.startswith(a):
        return False
    return b[len(a) :] in _INFLECTIONS


def _edit_le1(a: str, b: str) -> bool:
    """True when one substitution, insertion, deletion, or adjacent swap apart."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        diffs = [i for i in range(la) if a[i] != b[i]]
        if len(diffs) == 1:
            return True
        if (
            len(diffs) == 2
            and diffs[1] == diffs[0] + 1
            and a[diffs[0]] == b[diffs[1]]
            and a[diffs[1]] == b[diffs[0]]
        ):
            return True
        return False
    if la > lb:
        a, b = b, a
        la, lb = lb, la
    i = j = 0
    used = False
    while i < la and j < lb:
        if a[i] == b[j]:
            i += 1
            j += 1
            continue
        if used:
            return False
        used = True
        j += 1
    return True


def query_terms(query: str) -> list[tuple[str, bool]]:
    """Tokens, and whether quotes lock each one to the whole word.

    `"edi"` is only the word edi. `edi` may also sit inside a longer word.
    An opening quote that is still being typed locks the rest of the query.
    """
    text = query.replace("\u201c", '"').replace("\u201d", '"')
    terms: list[tuple[str, bool]] = []
    locked = False
    chunk: list[str] = []

    def flush(whole: bool) -> None:
        piece = "".join(chunk)
        chunk.clear()
        for token in tokenize(piece):
            terms.append((token, whole))

    for char in text:
        if char == '"':
            flush(locked)
            locked = not locked
            continue
        chunk.append(char)
    flush(locked)
    return terms


def _prefix_quality(token: str, word: str) -> int:
    """Closer to the full word ranks higher, and always below an exact hit."""
    return 58 + (32 * len(token) // len(word))


def _prefixes_for(token: str, prepared: list[Prepared], allow_when_known: bool) -> dict[str, int]:
    """Words the typed piece already covers, once it is at least half the word.

    A finished word in the middle of a query stays exact, so `data` does not
    swallow `database`. The word still being typed, or a piece that is not a
    word on its own, keeps completing.
    """
    if len(token) < 3:
        return {}
    if not allow_when_known and any(token in prep.postings for prep in prepared):
        return {}
    max_len = len(token) * 2
    found: dict[str, int] = {}
    for prep in prepared:
        words = prep.sorted_norms
        start = bisect.bisect_left(words, token)
        for word in words[start:]:
            if not word.startswith(token):
                break
            if word == token or len(word) > max_len:
                continue
            found[word] = _prefix_quality(token, word)
    if len(found) > 24:
        closest = sorted(found, key=lambda word: (len(word), word))[:24]
        found = {word: found[word] for word in closest}
    return found


def _contain_quality(token: str, word: str) -> int:
    """Inside a longer word, below a word that actually starts with the query."""
    return 42 + (16 * len(token) // len(word))


def _contains_for(token: str, prepared: list[Prepared]) -> dict[str, int]:
    """Longer words that contain these letters in order, such as edi inside credit."""
    if len(token) < 3:
        return {}
    found: dict[str, int] = {}
    for prep in prepared:
        for word in prep.sorted_norms:
            if len(word) <= len(token) or token not in word:
                continue
            qual = _contain_quality(token, word)
            if qual > found.get(word, 0):
                found[word] = qual
    if len(found) > 48:
        closest = sorted(found, key=lambda word: (len(word), word))[:48]
        found = {word: found[word] for word in closest}
    return found


def _merge_extra(found: dict[str, int], extra: dict[str, int] | None) -> None:
    for word, qual in (extra or {}).items():
        if qual > found.get(word, 0):
            found[word] = qual


def _expand(
    token: str,
    vocab: dict[str, tuple[str, str]],
    broad: bool,
    prefixes: dict[str, int] | None = None,
    contained: dict[str, int] | None = None,
) -> dict[str, int]:
    if not broad:
        found = {token: 100}
        _merge_extra(found, prefixes)
        _merge_extra(found, contained)
        return found
    token_stem = stem_token(token)
    token_phone = phonetic_norm(token)
    found: dict[str, int] = {}
    for word, (word_stem, word_phone) in vocab.items():
        if word == token:
            found[word] = 100
            continue
        if token.isdigit() or word.isdigit():
            continue
        if len(token) >= 3 and token_stem == word_stem:
            found[word] = 80
            continue
        if _prefix_variant(token, word):
            found[word] = 60
            continue
        if len(token) >= 4 and len(word) >= 4 and token_phone == word_phone:
            found[word] = 55
            continue
        if (
            len(token) >= 5
            and len(word) >= 5
            and token[0] == word[0]
            and abs(len(token) - len(word)) <= 1
            and _edit_le1(token, word)
        ):
            found[word] = 40
    _merge_extra(found, prefixes)
    _merge_extra(found, contained)
    return found


def _combined_vocab(prepared: list[Prepared]) -> dict[str, tuple[str, str]]:
    vocab: dict[str, tuple[str, str]] = {}
    for item in prepared:
        for norm, info in item.norms.items():
            vocab.setdefault(norm, info)
    return vocab


def _sentence_index(doc: Document, word_index: int) -> int:
    sentences = doc.sentences
    lo = 0
    hi = len(sentences) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        sentence = sentences[mid]
        if word_index < sentence.word_start:
            hi = mid - 1
        elif word_index >= sentence.word_end:
            lo = mid + 1
        else:
            return mid
    return -1


def _search_doc(
    doc_index: int,
    prep: Prepared,
    expansions: list[dict[str, int]],
    gap_limit: int,
) -> tuple[list[Match], bool]:
    words = prep.doc.words
    if not words or not expansions:
        return [], False
    best_at: dict[int, int] = {}
    for norm, qual in expansions[0].items():
        for idx in prep.postings.get(norm, ()):
            if qual > best_at.get(idx, 0):
                best_at[idx] = qual
    found: list[Match] = []
    total = len(words)
    for start_idx, start_qual in sorted(best_at.items()):
        hits = [start_idx]
        qualities = [start_qual]
        gaps = 0
        cursor = start_idx
        ok = True
        budget = gap_limit
        for expansion in expansions[1:]:
            found_at = None
            found_qual = 0
            limit = min(total - 1, cursor + 1 + budget)
            for index in range(cursor + 1, limit + 1):
                qual = expansion.get(words[index].norm, 0)
                if qual:
                    found_at = index
                    found_qual = qual
                    break
            if found_at is None:
                ok = False
                break
            step_gap = found_at - cursor - 1
            gaps += step_gap
            budget -= step_gap
            cursor = found_at
            hits.append(found_at)
            qualities.append(found_qual)
        if not ok:
            continue
        sentence = _sentence_index(prep.doc, hits[0])
        if sentence < 0:
            continue
        end_sentence = _sentence_index(prep.doc, hits[-1])
        score = sum(qualities) - gaps * 12
        if all(qual == 100 for qual in qualities):
            score += 40
        if gaps == 0:
            score += 20
        if end_sentence == sentence:
            score += 15
        elif end_sentence > sentence:
            score -= 8 * (end_sentence - sentence)
        found.append(
            Match(
                doc_index=doc_index,
                page=words[hits[0]].page,
                sentence_index=sentence,
                hits=tuple(hits),
                score=score,
                gap=gaps,
            )
        )
        if len(found) >= _MAX_COLLECT:
            return found, True
    return found, False


def _dedupe(matches: list[Match]) -> list[Match]:
    matches.sort(key=lambda m: (-m.score, m.gap, (m.hits[-1] - m.hits[0]) if m.hits else 0))
    kept: list[Match] = []
    used: dict[int, set[int]] = {}
    for match in matches:
        claimed = used.setdefault(match.doc_index, set())
        span = range(match.hits[0], match.hits[-1] + 1)
        if any(index in claimed for index in span):
            continue
        claimed.update(span)
        kept.append(match)
    return kept


def _token_positions(expansion: dict[str, int], postings: dict[str, list[int]]) -> list[tuple[int, int]]:
    best: dict[int, int] = {}
    for norm, qual in expansion.items():
        if qual <= 0:
            continue
        for idx in postings.get(norm, ()):
            if qual > best.get(idx, 0):
                best[idx] = qual
    return sorted(best.items())


def _slice_positions(items: list[tuple[int, int]], lo: int, hi: int) -> list[tuple[int, int]]:
    start = bisect.bisect_left(items, (lo, -1))
    stop = bisect.bisect_left(items, (hi, -1))
    return items[start:stop]


def _near_matches(
    doc_index: int,
    prep: Prepared,
    expansions: list[dict[str, int]],
    proximity: int,
) -> list[Match]:
    """Words in one sentence, within `proximity` extra words, in any order."""
    count = len(expansions)
    if count < 2 or count > 5 or proximity < 0:
        return []
    lists = [_token_positions(expansion, prep.postings) for expansion in expansions]
    if any(not items for items in lists):
        return []
    anchor = min(range(count), key=lambda index: len(lists[index]))
    max_diff = proximity + count - 1
    found: list[Match] = []
    doc = prep.doc
    for idx, qual in lists[anchor]:
        sentence_index = _sentence_index(doc, idx)
        if sentence_index < 0:
            continue
        sentence = doc.sentences[sentence_index]
        lo = max(sentence.word_start, idx - max_diff)
        hi = min(sentence.word_end, idx + max_diff + 1)
        groups: list[list[tuple[int, int]]] = [[] for _ in range(count)]
        groups[anchor] = [(idx, qual)]
        possible = True
        for token_index, items in enumerate(lists):
            if token_index == anchor:
                continue
            options = [item for item in _slice_positions(items, lo, hi) if item[0] != idx]
            if not options:
                possible = False
                break
            options.sort(key=lambda item: (abs(item[0] - idx), -item[1]))
            groups[token_index] = options[:6]
        if not possible:
            continue
        best = None
        best_key = None
        for combo in product(*groups):
            ids = [item[0] for item in combo]
            if len(set(ids)) != count:
                continue
            span = max(ids) - min(ids)
            extra = span - (count - 1)
            if extra > proximity:
                continue
            key = (span, -sum(item[1] for item in combo))
            if best_key is None or key < best_key:
                best_key = key
                best = combo
        if best is None:
            continue
        ids = [item[0] for item in best]
        quals = [item[1] for item in best]
        extra = (max(ids) - min(ids)) - (count - 1)
        in_order = all(ids[left] < ids[right] for left in range(count) for right in range(left + 1, count))
        score = sum(quals) - extra * 14 + (18 if in_order else 4) + 15
        if all(item == 100 for item in quals):
            score += 16
        first = min(ids)
        found.append(
            Match(
                doc_index=doc_index,
                page=doc.words[first].page,
                sentence_index=sentence_index,
                hits=tuple(sorted(ids)),
                score=score,
                gap=extra,
            )
        )
        if len(found) >= _MAX_COLLECT:
            break
    return found


def preview_text(doc: Document, match: Match, limit: int) -> str:
    """Hit sentence plus the following one, cut to a character limit."""
    if limit < 1 or match.sentence_index < 0 or match.sentence_index >= len(doc.sentences):
        return ""
    parts = [doc.sentences[match.sentence_index].text]
    if match.sentence_index + 1 < len(doc.sentences):
        parts.append(doc.sentences[match.sentence_index + 1].text)
    text = " ".join(part for part in parts if part)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    clipped = text[:limit].rsplit(" ", 1)[0].rstrip(".,;:") or text[:limit].rstrip()
    return clipped + "…"


def search(prepared: list[Prepared], query: str, mode: str, proximity: int | None = None) -> SearchHits:
    started = time.perf_counter()
    terms = query_terms(query)
    if not terms or not prepared:
        return SearchHits([], False, 0.0)
    broad = mode == "broad"
    if proximity is None:
        gap_limit = _BROAD_GAP if broad else 0
        near = 8 if broad else 0
    else:
        gap_limit = max(0, proximity)
        near = gap_limit
    vocab = _combined_vocab(prepared)
    last = len(terms) - 1
    expansions = []
    for index, (token, whole_word) in enumerate(terms):
        if whole_word:
            expansions.append({token: 100})
            continue
        expansions.append(
            _expand(
                token,
                vocab,
                broad,
                _prefixes_for(token, prepared, index == last),
                _contains_for(token, prepared),
            )
        )
    matches: list[Match] = []
    truncated = False
    for doc_index, prep in enumerate(prepared):
        found, cut = _search_doc(doc_index, prep, expansions, gap_limit)
        matches.extend(found)
        if broad and near > 0:
            matches.extend(_near_matches(doc_index, prep, expansions, near))
        truncated = truncated or cut
        if len(matches) >= _MAX_COLLECT:
            truncated = True
            break
    matches = _dedupe(matches)
    matches.sort(key=lambda m: (-m.score, m.doc_index, m.page, m.hits[0] if m.hits else 0))
    if len(matches) > MAX_RESULTS:
        matches = matches[:MAX_RESULTS]
        truncated = True
    elapsed = (time.perf_counter() - started) * 1000
    return SearchHits(matches, truncated, elapsed)
