# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""Build eval/real_dataset.json: real Wikipedia lead sections as sources, with claims made by:
  supported   - an LLM paraphrase (local Ollama) of a sentence from the source, facts and numbers kept
  partial     - a sentence from the source with one number changed programmatically
  unsupported - a sentence taken from a DIFFERENT article, cited against this one (wrong source)
Labels are therefore correct by construction. Run: uv run scripts/build_real_set.py
Text is from Wikipedia, CC BY-SA 4.0. Needs network and Ollama (llama3.2:3b)."""

import json
import random
import re

import httpx

PAGES = [
    "Sydney Harbour Bridge",
    "Uluru",
    "Murray River",
    "Snowy Mountains Scheme",
    "Canberra",
    "Great Barrier Reef",
    "Lake Eyre",
    "Mount Kosciuszko",
]
API = "https://en.wikipedia.org/w/api.php"
rng = random.Random(7)


def lead(title: str) -> str:
    r = httpx.get(
        API,
        params={
            "action": "query",
            "prop": "extracts",
            "explaintext": 1,
            "exintro": 1,
            "titles": title,
            "format": "json",
            "redirects": 1,
        },
        headers={"User-Agent": "cite-check-eval/0.1"},
        timeout=30,
    )
    r.raise_for_status()
    return next(iter(r.json()["query"]["pages"].values()))["extract"]


def sentences(text: str) -> list[str]:
    text = re.sub(r"\([^)]*\)", "", text)  # drop parentheticals (pronunciations, dates in brackets)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if 8 <= len(s.split()) <= 40]


def paraphrase(s: str) -> str:
    r = httpx.post(
        "http://localhost:11434/api/generate",
        timeout=120,
        json={
            "model": "llama3.2:3b",
            "stream": False,
            "options": {"temperature": 0.3},
            "prompt": f"Rewrite this sentence in clearly different words and sentence structure. Keep every fact and every number exactly. Output only the sentence.\n\n{s}",
        },
    )
    out = r.json()["response"].strip().strip('"').split("\n")[0].strip()
    if len(out.split()) < 5 or "rewrite" in out.lower() or "sentence" in out.lower()[:40]:
        raise ValueError(f"bad paraphrase: {out[:80]!r}")
    return out


def bump(s: str) -> str | None:
    nums = list(re.finditer(r"\b\d[\d,]*(?:\.\d+)?\b", s))
    nums = [
        m for m in nums if not re.fullmatch(r"(1[0-9]{3}|20[0-9]{2})", m.group())
    ]  # leave years alone
    if not nums:
        return None
    m = rng.choice(nums)
    v = float(m.group().replace(",", ""))
    new = f"{round(v * rng.choice([1.5, 2, 0.6]), 1):g}"
    return s[: m.start()] + new + s[m.end() :]


sources = {p: lead(p) for p in PAGES}
claims = []
for title, text in sources.items():
    ss = sentences(text)
    url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
    pick = rng.sample(ss, min(5, len(ss)))
    for s in pick[:2]:
        claims.append({"text": paraphrase(s), "url": url, "label": "supported", "origin": s})
    for s in pick:
        b = bump(s)
        if b and sum(c["label"] == "partial" and c["url"] == url for c in claims) < 1:
            claims.append({"text": b, "url": url, "label": "partial", "origin": s})
    other = rng.choice([t for t in PAGES if t != title])
    claims.append(
        {
            "text": rng.choice(sentences(sources[other])),
            "url": url,
            "label": "unsupported",
            "origin": f"from {other}",
        }
    )

out = {
    "note": "Real Wikipedia lead sections (CC BY-SA 4.0). Supported = LLM paraphrase of a source sentence; partial = source sentence with one number changed; unsupported = sentence from a different article. Labels are correct by construction, but the claims are not natural AI-report claims.",
    "sources": {
        f"https://en.wikipedia.org/wiki/{t.replace(' ', '_')}": x for t, x in sources.items()
    },
    "claims": claims,
}
with open("eval/real_dataset.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1, ensure_ascii=False)
from collections import Counter

print(len(claims), Counter(c["label"] for c in claims))
