from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .judge import HeuristicJudge, OllamaJudge
from .pipeline import check_report, fallback_count, summarise
from .report import render_html


def main(argv: list[str] | None = None) -> int:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    p = argparse.ArgumentParser(prog="cite-check", description="Check that a report's citations support its claims.")
    p.add_argument("report", help="Markdown or HTML file")
    p.add_argument("-o", "--output", default=None, help="HTML report path (default: <report>.check.html)")
    p.add_argument("--llm", nargs="?", const="qwen3:4b", default=None, metavar="MODEL", help="Use a local Ollama model as judge (default qwen3:4b)")
    args = p.parse_args(argv)

    path = Path(args.report)
    judge = OllamaJudge(args.llm) if args.llm else HeuristicJudge()
    results = check_report(path.read_text(encoding="utf-8"), judge=judge, is_html=path.suffix in {".html", ".htm"})
    out = Path(args.output) if args.output else path.with_suffix(".check.html")
    out.write_text(render_html(results, title=f"Citation check: {path.name}"), encoding="utf-8")
    counts = summarise(results)
    print(f"{len(results)} cited claims: " + ", ".join(f"{v} {k}" for k, v in counts.items()), file=sys.stderr)
    print(f"report: {out}", file=sys.stderr)
    if args.llm and (n := fallback_count(results)):
        print(f"WARNING: the LLM judge failed on {n} claim(s); the heuristic judged those instead.", file=sys.stderr)
    if not results:
        print("ERROR: no cited claims were found. Is the citation style supported?", file=sys.stderr)
        return 2
    if counts["unreachable"]:
        print(f"WARNING: {counts['unreachable']} claim(s) could not be checked (unreachable source or unresolved reference).", file=sys.stderr)
    if counts["unsupported"]:
        return 1
    return 3 if counts["unreachable"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
