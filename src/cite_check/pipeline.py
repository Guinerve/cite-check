from __future__ import annotations

from dataclasses import dataclass

from .judge import UNREACHABLE, HeuristicJudge, Judge, Verdict
from .parse import Claim, parse_report
from .retrieve import best_passages
from .sources import Fetcher

_RANK = {"supported": 3, "partial": 2, "unsupported": 1, "unreachable": 0}


@dataclass
class Result:
    claim: Claim
    verdict: Verdict
    url: str
    others: list[tuple[str, Verdict]]


def _unresolved(label: str) -> Verdict:
    return Verdict(
        UNREACHABLE, reason=f"citation [{label}] has no matching reference entry", judge="parse"
    )


def check_claim(claim: Claim, fetcher: Fetcher, judge: Judge) -> Result:
    if not claim.urls:
        v = Verdict(
            UNREACHABLE,
            reason=f"citation [{', '.join(claim.unresolved)}] has no matching reference entry",
            judge="parse",
        )
        return Result(claim, v, "", [])
    missing = [(f"[{n}]", _unresolved(n)) for n in claim.unresolved]
    per_url: list[tuple[str, Verdict]] = []
    for url in claim.urls:
        src = fetcher.get(url)
        if not src.ok:
            per_url.append(
                (url, Verdict(UNREACHABLE, reason=src.error or "no text", judge="fetch"))
            )
            continue
        per_url.append((url, judge.judge(claim.text, best_passages(claim.text, src.chunks))))
    # A claim with several sources is as good as its best-supporting one.
    best_url, best = max(per_url, key=lambda uv: (_RANK[uv[1].label], uv[1].score))
    return Result(claim, best, best_url, [uv for uv in per_url if uv[0] != best_url] + missing)


def check_report(
    text: str, fetcher: Fetcher | None = None, judge: Judge | None = None, is_html: bool = False
) -> list[Result]:
    fetcher = fetcher or Fetcher()
    judge = judge or HeuristicJudge()
    return [check_claim(c, fetcher, judge) for c in parse_report(text, is_html)]


def fallback_count(results: list[Result]) -> int:
    """Verdicts where an LLM judge failed and the heuristic answered instead."""
    return sum(1 for r in results if "LLM judge failed" in r.verdict.reason)


def summarise(results: list[Result]) -> dict[str, int]:
    out = {"supported": 0, "partial": 0, "unsupported": 0, "unreachable": 0}
    for r in results:
        out[r.verdict.label] += 1
    return out
