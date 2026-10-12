"""Find the passage in a source that best matches a claim."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

STOP = set("""a an the and or but of to in on for with by from as at is are was were be been being it its this that these
those which who whom has have had do does did not no can could will would should may might also than then so such
into over under about more most less least very per via their there they them he she his her we our you your i""".split())


def content_words(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[a-z0-9][a-z0-9\-.%$]*", text.lower()) if w not in STOP and len(w) > 1]


def stem(w: str) -> str:
    w = w.strip(".-")
    for suf in ("ings", "ing", "edly", "ed", "es", "s", "ly"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def numbers(text: str) -> list[str]:
    return [n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,]*\.?\d*", text) if n.strip(",.")]


def score(claim: str, passage: str) -> float:
    """0..1 lexical match: content-word overlap blended with rapidfuzz token-set similarity."""
    cw = set(content_words(claim))
    if not cw:
        return 0.0
    pw = set(content_words(passage))
    overlap = len(cw & pw) / len(cw)
    fuzzy = fuzz.token_set_ratio(claim, passage) / 100
    return 0.7 * overlap + 0.3 * fuzzy


def best_passages(claim: str, chunks: list[str], k: int = 3) -> list[tuple[float, str]]:
    scored = sorted(((score(claim, c), c) for c in chunks), key=lambda x: -x[0])
    return scored[:k]
