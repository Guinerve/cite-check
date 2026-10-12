"""Fetch and chunk sources. Everything fails soft into `Source.error` so one bad URL never stops a run."""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

import httpx

UA = "cite-check/0.1 (+https://github.com/; research tool)"
_SKIP = {"script", "style", "noscript", "nav", "footer", "header", "svg", "form"}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        if tag in _SKIP:
            self._skip += 1
        elif tag in {"p", "br", "li", "h1", "h2", "h3", "h4", "tr", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):  # noqa: ANN001
        if tag in _SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):  # noqa: ANN001
        if not self._skip:
            self.parts.append(data)


def html_to_text(src: str) -> str:
    p = _Text()
    p.feed(src)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", "".join(p.parts))).strip()


def pdf_to_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


@dataclass
class Source:
    url: str
    text: str = ""
    error: str | None = None
    chunks: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.text.strip())


def chunk_text(text: str, sentences_per_chunk: int = 3, stride: int = 1) -> list[str]:
    """Overlapping windows of consecutive sentences, so a claim can match across a sentence boundary."""
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip().split()) >= 3]
    if not sents:
        return []
    if len(sents) <= sentences_per_chunk:
        return [" ".join(sents)]
    return [" ".join(sents[i : i + sentences_per_chunk]) for i in range(0, len(sents) - sentences_per_chunk + 1, stride)]


class Fetcher:
    def __init__(self, cache_dir: str | Path | None = None, http: httpx.Client | None = None, max_bytes: int = 15_000_000):
        self.cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".cache" / "cite-check"
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.cache_dir = None  # no cache: still works, just refetches
        self.http = http or httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": UA})
        self.max_bytes = max_bytes
        self._mem: dict[str, Source] = {}

    def get(self, url: str) -> Source:
        if url in self._mem:
            return self._mem[url]
        src = self._fetch(url)
        src.chunks = chunk_text(src.text) if src.ok else []
        self._mem[url] = src
        return src

    def _fetch(self, url: str) -> Source:
        key = self.cache_dir / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".txt") if self.cache_dir else None
        if key is not None and key.exists():
            return Source(url, key.read_text(encoding="utf-8"))
        try:
            r = self.http.get(url)
        except httpx.HTTPError as exc:
            return Source(url, error=f"unreachable: {type(exc).__name__}")
        if r.status_code in (401, 402, 403, 451):
            return Source(url, error=f"blocked or paywalled (HTTP {r.status_code})")
        if r.status_code >= 400:
            return Source(url, error=f"HTTP {r.status_code}")
        if len(r.content) > self.max_bytes:
            return Source(url, error="too large")
        ctype = r.headers.get("content-type", "").lower()
        try:
            text = pdf_to_text(r.content) if "pdf" in ctype or url.lower().endswith(".pdf") else html_to_text(r.text)
        except Exception as exc:  # noqa: BLE001 - malformed PDFs raise assorted errors
            return Source(url, error=f"could not parse: {type(exc).__name__}")
        if len(text.split()) < 30:
            return Source(url, text, error="page has almost no readable text (JavaScript or paywall?)")
        if key is not None:
            try:
                key.write_text(text, encoding="utf-8")
            except OSError:
                pass  # cache is an optimisation only
        return Source(url, text)
