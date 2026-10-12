"""Verdicts: supported / partial / unsupported / unreachable, with the passage that justifies it."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from .retrieve import content_words, numbers, score  # noqa: F401

SUPPORTED, PARTIAL, UNSUPPORTED, UNREACHABLE = "supported", "partial", "unsupported", "unreachable"
NEGATIONS = {"not", "no", "never", "without", "neither", "nor", "cannot", "fails", "failed", "decline", "declined", "decreased", "fell"}


@dataclass
class Verdict:
    label: str
    passage: str = ""
    score: float = 0.0
    reason: str = ""
    judge: str = ""


class Judge(Protocol):
    name: str

    def judge(self, claim: str, passages: list[tuple[float, str]]) -> Verdict: ...


class HeuristicJudge:
    """Offline judge. Cheap and transparent, and deliberately conservative about 'supported'.

    supported   : most claim words appear in one passage, and every number in the claim does too
    partial     : topic matches but a number is missing/different, or only some words match
    unsupported : nothing in the source resembles the claim
    """

    name = "heuristic"

    def __init__(self, support: float = 0.72, partial: float = 0.55):
        self.support, self.partial = support, partial

    def judge(self, claim: str, passages: list[tuple[float, str]]) -> Verdict:
        if not passages:
            return Verdict(UNSUPPORTED, reason="source has no usable text", judge=self.name)
        sc, passage = passages[0]
        cnums, pnums = set(numbers(claim)), set(numbers(passage))
        missing = sorted(cnums - pnums)
        cw, pw = set(content_words(claim)), set(content_words(passage))
        # A claim that says "not/no/never" needs a negation in the passage sentence it best matches.
        best_sentence = max(re.split(r"(?<=[.!?])\s+", passage), key=lambda x: score(claim, x))
        neg_mismatch = bool(set(re.findall(r"[a-z]+", claim.lower())) & NEGATIONS) and not (
            set(re.findall(r"[a-z]+", best_sentence.lower())) & NEGATIONS)
        if missing:
            label = PARTIAL if sc >= self.partial else UNSUPPORTED
            reason = f"numbers not found in the passage: {', '.join(missing)}"
        elif sc >= self.support and not neg_mismatch:
            label, reason = SUPPORTED, f"{len(cw & pw)}/{len(cw)} claim terms found in one passage"
        elif sc >= self.support and neg_mismatch:
            label, reason = PARTIAL, "wording matches but negation/direction words differ"
        elif sc >= self.partial:
            label, reason = PARTIAL, f"only {len(cw & pw)}/{len(cw)} claim terms found"
        else:
            label, reason = UNSUPPORTED, "no passage resembles the claim"
        return Verdict(label, passage, sc, reason, self.name)


class OllamaJudge:
    """Ask a local LLM whether the passages entail the claim. Falls back to the heuristic if the model errors."""

    def __init__(self, model: str = "qwen3:4b", host: str = "http://localhost:11434", http: httpx.Client | None = None):
        self.model, self.host = model, host.rstrip("/")
        self.http = http or httpx.Client(timeout=120)
        self.name = f"ollama:{model}"
        self._fallback = HeuristicJudge()

    PROMPT = (
        "You check citations. Decide whether the SOURCE PASSAGES support the CLAIM.\n"
        "Answer with JSON only: {{\"verdict\": \"supported|partial|unsupported\", \"reason\": \"<one sentence>\"}}.\n"
        "supported = the passages state or directly imply everything in the claim, including numbers.\n"
        "partial = the passages support part of the claim, or the numbers/scope differ.\n"
        "unsupported = the passages do not say this, or contradict it.\n\n"
        "CLAIM: {claim}\n\nSOURCE PASSAGES:\n{passages}\n"
    )

    def judge(self, claim: str, passages: list[tuple[float, str]]) -> Verdict:
        base = self._fallback.judge(claim, passages)
        if not passages:
            return base
        text = "\n---\n".join(p for _, p in passages)
        try:
            r = self.http.post(f"{self.host}/api/generate", json={
                "model": self.model, "prompt": self.PROMPT.format(claim=claim, passages=text),
                "stream": False, "format": "json", "think": False, "options": {"temperature": 0},
            })
            r.raise_for_status()
            out = json.loads(r.json()["response"])
            label = str(out.get("verdict", "")).lower()
            if label not in {SUPPORTED, PARTIAL, UNSUPPORTED}:
                raise ValueError(f"bad verdict {label!r}")
            return Verdict(label, passages[0][1], passages[0][0], str(out.get("reason", "")), self.name)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
            base.reason += f" (LLM judge failed: {type(exc).__name__}; used heuristic)"
            return base
