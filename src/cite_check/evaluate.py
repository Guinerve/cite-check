"""Score a judge against a labelled dataset: precision/recall per label plus a confusion matrix.

  uv run python -m cite_check.evaluate eval/seed_dataset.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import httpx

from .judge import HeuristicJudge, Judge, OllamaJudge
from .parse import Claim
from .pipeline import check_claim
from .sources import Fetcher

LABELS = ["supported", "partial", "unsupported"]


def fetcher_for(sources: dict[str, str], cache: Path) -> Fetcher:
    def handler(req: httpx.Request) -> httpx.Response:
        body = sources.get(str(req.url))
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, text=f"<html><body><p>{body}</p></body></html>", headers={"content-type": "text/html"})

    return Fetcher(cache_dir=cache, http=httpx.Client(transport=httpx.MockTransport(handler)))


def evaluate(data: dict, judge: Judge, cache: Path) -> dict:
    fetcher = fetcher_for(data["sources"], cache)
    confusion: Counter[tuple[str, str]] = Counter()
    errors = []
    for i, item in enumerate(data["claims"], 1):
        r = check_claim(Claim(i, item["text"], [item["url"]], 0), fetcher, judge)
        confusion[(item["label"], r.verdict.label)] += 1
        if r.verdict.label != item["label"]:
            errors.append({"claim": item["text"], "expected": item["label"], "got": r.verdict.label, "reason": r.verdict.reason})
    per = {}
    for lab in LABELS:
        tp = confusion[(lab, lab)]
        pred = sum(v for (e, g), v in confusion.items() if g == lab)
        act = sum(v for (e, g), v in confusion.items() if e == lab)
        per[lab] = {"precision": tp / pred if pred else None, "recall": tp / act if act else None, "n": act}
    total = len(data["claims"])
    return {"accuracy": sum(confusion[(lab, lab)] for lab in LABELS) / total, "n": total, "per_label": per,
            "confusion": {f"{e}->{g}": v for (e, g), v in sorted(confusion.items())}, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    path = Path(argv[0])
    judge: Judge = OllamaJudge(argv[argv.index("--llm") + 1]) if "--llm" in argv else HeuristicJudge()
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        res = evaluate(json.loads(path.read_text()), judge, Path(tmp))
    print(f"judge: {judge.name}   claims: {res['n']}   accuracy: {res['accuracy']:.1%}")
    for lab, m in res["per_label"].items():
        p = "n/a" if m["precision"] is None else f"{m['precision']:.0%}"
        r = "n/a" if m["recall"] is None else f"{m['recall']:.0%}"
        print(f"  {lab:12s} precision {p:>4s}  recall {r:>4s}  (n={m['n']})")
    print("confusion (expected->got):", res["confusion"])
    for e in res["errors"]:
        print(f"  MISS expected {e['expected']}, got {e['got']}: {e['claim']}  [{e['reason']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
