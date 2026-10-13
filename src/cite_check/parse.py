"""Pull (claim, citation) pairs out of a Markdown or HTML report.

Supported citation styles: inline links `[text](https://...)`, numeric refs `[1]` / `[^1]` with a
definition `[1]: https://...` or a "References" list line like `1. Title. https://...`, and bare URLs
in parentheses. A claim is the sentence a citation sits in.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

URL = r"https?://[^\s)\]>\"']+"
_INLINE = re.compile(rf"\[([^\]]+)\]\(({URL})[^)]*\)")
_REF_USE = re.compile(r"\[\^?(\d+)\]")
_REF_DEF = re.compile(r"^\s*\[\^?(\d+)\]:\s*(.*?)\s*$", re.MULTILINE)
_LIST_REF = re.compile(r"^\s*(\d+)[.)]\s+(.*?)\s*$", re.MULTILINE)
_BARE = re.compile(rf"\((?:see\s+)?({URL})\)")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'\[(])")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s")


@dataclass
class Claim:
    id: int
    text: str
    urls: list[str]
    line: int
    context: str = ""
    cite_labels: list[str] = field(default_factory=list)
    unresolved: list[str] = field(
        default_factory=list
    )  # [n] markers with no reference entry in the report


def html_to_markdown(src: str) -> str:
    """Very small HTML -> Markdown for reports saved as HTML: keeps paragraphs and links."""
    s = re.sub(r"(?is)<(script|style).*?</\1>", "", src)
    s = re.sub(r'(?is)<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"[\2](\1)", s)
    s = re.sub(r"(?i)</(p|div|li|h\d|tr)>|<br\s*/?>", "\n\n", s)
    s = re.sub(r"(?s)<[^>]+>", "", s)
    return html.unescape(s)


_REF_HEADING = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*)?(?:references|sources|bibliography|works cited|citations)[ \t]*:?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
_ANY_HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]", re.MULTILINE)


def _reference_section(text: str) -> str | None:
    """The text under the last "References" style heading, up to the next Markdown heading."""
    heads = list(_REF_HEADING.finditer(text))
    if heads:
        body = text[heads[-1].end() :]
        nxt = _ANY_HEADING.search(body)
        return body[: nxt.start()] if nxt else body
    low = text.lower()
    if "reference" in low or "sources" in low or "bibliography" in low:
        return text[low.rfind("\n#") :] if "\n#" in low else text
    return None


def _find_refs(text: str) -> dict[str, str]:
    refs: dict[str, str] = {}
    for m in _REF_DEF.finditer(text):
        u = re.search(URL, m.group(2))
        if u:
            refs[m.group(1)] = u.group(0).rstrip(".,;")
    section = _reference_section(text)
    if section is not None:
        for m in _LIST_REF.finditer(section):
            u = re.search(URL, m.group(2))
            if u and m.group(1) not in refs:
                refs[m.group(1)] = u.group(0).rstrip(".,;")
    return refs


_TRAILING_CITE = re.compile(rf"\s*\[[^\]]{{1,40}}\]\({URL}[^)]*\)(?=\s*[.!?]?\s*$)")


def _clean(sentence: str) -> str:
    # A short link at the very end of the sentence is a citation ("[Wikipedia](url)"), not part of the claim.
    # A link in the middle ("the [IEA](url) reported...") keeps its words.
    s = _TRAILING_CITE.sub("", sentence)
    s = _INLINE.sub(r"\1", s)
    s = _REF_USE.sub("", s)
    s = _BARE.sub("", s)
    s = re.sub(r"[*_`]+", "", s)
    s = re.sub(r"\s+([.,;:!?])", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_report(text: str, is_html: bool = False) -> list[Claim]:
    if is_html:
        text = html_to_markdown(text)
    refs = _find_refs(text)
    claims: list[Claim] = []
    pos = 0
    blocks = []
    for sep in re.finditer(r"\n\s*\n", text):
        blocks.append((text[pos : sep.start()], pos))
        pos = sep.end()
    blocks.append((text[pos:], pos))
    for block, offset in blocks:
        line = text[:offset].count("\n") + 1
        if _HEADING_RE.match(block) or _REF_DEF.match(block):
            continue
        if (
            re.match(r"^\s*\d+[.)]\s+.*" + URL, block)
            and "reference" not in block.lower()
            and block.count("\n") == 0
            and len(block.split()) < 30
            and not _INLINE.search(block)
            and not _REF_USE.search(block)
        ):
            continue  # bibliography entry, not a claim
        flat = re.sub(
            r"([.!?])((?:\[\^?\d+\])+)", r"\2\1", block.replace("\n", " ")
        )  # "year.[1]" -> "year[1]."
        for sent in _SENT_SPLIT.split(flat):
            urls = [m.group(2) for m in _INLINE.finditer(sent)] + _BARE.findall(sent)
            labels = _REF_USE.findall(sent)
            urls += [refs[n] for n in labels if n in refs]
            missing = [n for n in labels if n not in refs]
            urls = list(dict.fromkeys(u.rstrip(".,;") for u in urls))
            if not urls and not missing:
                continue
            clean = _clean(sent)
            if len(clean.split()) < 3:
                continue
            claims.append(
                Claim(
                    len(claims) + 1,
                    clean,
                    urls,
                    line,
                    context=_clean(block),
                    cite_labels=labels,
                    unresolved=missing,
                )
            )
    return claims
