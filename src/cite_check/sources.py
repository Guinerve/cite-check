"""Fetch and chunk sources. Everything fails soft into `Source.error` so one bad URL never stops a run.

The URLs come from the report being checked, so treat them as untrusted. The default client only
connects to public addresses (checked on every redirect hop) and stops reading a body at `max_bytes`.
"""

from __future__ import annotations

import hashlib
import io
import ipaddress
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

import httpx

UA = "cite-check/0.1 (+https://github.com/Guinerve/cite-check)"
_TEXT_TYPES = ("text/", "html", "xml", "json")
_SKIP = {"script", "style", "noscript", "nav", "footer", "header", "svg", "form"}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip += 1
        elif tag in {"p", "br", "li", "h1", "h2", "h3", "h4", "tr", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
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


class BlockedHostError(httpx.TransportError):
    """The URL points at a private, local or reserved address, or uses a scheme other than http(s)."""


def _system_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise httpx.ConnectError(f"could not resolve {host}") from exc
    return [str(info[4][0]) for info in infos]


def _is_public(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class PublicOnlyTransport(httpx.BaseTransport):
    """Refuse requests to non public addresses, then connect to the exact address that passed the check.

    Pinning the checked address closes the gap where DNS answers differently on the second lookup.
    TLS still verifies the certificate against the real host name (sent as `sni_hostname`).
    httpx calls the transport once per redirect hop, so every hop is checked.
    """

    def __init__(
        self,
        inner: httpx.BaseTransport | None = None,
        resolver: Callable[[str, int], list[str]] = _system_resolver,
        allow_private: bool = False,
    ):
        self.inner = inner or httpx.HTTPTransport()
        self.resolver = resolver
        self.allow_private = allow_private

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.scheme not in ("http", "https"):
            raise BlockedHostError(f"scheme {url.scheme!r} is not allowed", request=request)
        port = url.port or (443 if url.scheme == "https" else 80)
        addrs = self.resolver(url.host, port)
        if not addrs:
            raise httpx.ConnectError(f"could not resolve {url.host}", request=request)
        if not self.allow_private and not all(_is_public(a) for a in addrs):
            raise BlockedHostError(f"{url.host} is a private or local address", request=request)
        headers = request.headers.copy()
        headers["Host"] = url.netloc.decode("ascii")
        extensions = dict(request.extensions)
        if url.scheme == "https":
            extensions.setdefault("sni_hostname", url.host)
        pinned = httpx.Request(
            request.method,
            url.copy_with(host=addrs[0].split("%")[0]),
            headers=headers,
            stream=request.stream,
            extensions=extensions,
        )
        return self.inner.handle_request(pinned)

    def close(self) -> None:
        self.inner.close()


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
    return [
        " ".join(sents[i : i + sentences_per_chunk])
        for i in range(0, len(sents) - sentences_per_chunk + 1, stride)
    ]


class Fetcher:
    def __init__(
        self,
        cache_dir: str | Path | None = None,
        http: httpx.Client | None = None,
        max_bytes: int = 15_000_000,
        allow_private: bool = False,
    ):
        self.cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".cache" / "cite-check"
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.cache_dir = None  # no cache: still works, just refetches
        self.http = http or httpx.Client(
            timeout=30,
            follow_redirects=True,
            max_redirects=5,
            headers={"User-Agent": UA},
            transport=PublicOnlyTransport(allow_private=allow_private),
        )
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
        key = (
            self.cache_dir / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".txt")
            if self.cache_dir
            else None
        )
        if key is not None and key.exists():
            return Source(url, key.read_text(encoding="utf-8"))
        try:
            with self.http.stream("GET", url) as r:
                if r.status_code in (401, 402, 403, 451):
                    return Source(url, error=f"blocked or paywalled (HTTP {r.status_code})")
                if r.status_code >= 400:
                    return Source(url, error=f"HTTP {r.status_code}")
                ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype and "pdf" not in ctype and not any(t in ctype for t in _TEXT_TYPES):
                    return Source(url, error=f"unsupported content type: {ctype}")
                too_large = Source(url, error=f"too large (over {self.max_bytes} bytes)")
                declared = r.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > self.max_bytes:
                    return too_large
                body = bytearray()
                for part in r.iter_bytes():  # decoded bytes, so a compressed bomb is caught too
                    body += part
                    if len(body) > self.max_bytes:
                        return too_large
                encoding = r.encoding or "utf-8"
        except BlockedHostError as exc:
            return Source(url, error=f"blocked: {exc}")
        except httpx.HTTPError as exc:
            return Source(url, error=f"unreachable: {type(exc).__name__}")
        try:
            "".encode(encoding)
        except LookupError:
            encoding = "utf-8"  # the server named a charset Python does not know
        try:
            if body[:5] == b"%PDF-" or "pdf" in ctype:
                text = pdf_to_text(bytes(body))
            else:
                text = html_to_text(body.decode(encoding, errors="replace"))
        except Exception as exc:  # noqa: BLE001 - malformed PDFs raise assorted errors
            return Source(url, error=f"could not parse: {type(exc).__name__}")
        if len(text.split()) < 30:
            return Source(
                url,
                text,
                error="page has almost no readable text (it may need JavaScript or a login)",
            )
        if key is not None:
            try:
                key.write_text(text, encoding="utf-8")
            except OSError:
                pass  # cache is an optimisation only
        return Source(url, text)
