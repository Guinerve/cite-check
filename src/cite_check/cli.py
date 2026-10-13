from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .judge import HeuristicJudge, OllamaJudge
from .pipeline import check_report, fallback_count, summarise
from .report import render_html
from .sources import Fetcher

EPILOG = """exit codes:
  0  every cited claim is supported or partly supported
  1  one or more claims are unsupported
  2  no cited claims were found, or the report could not be read
  3  some claims could not be checked (source unreachable or reference missing)"""


def main(argv: list[str] | None = None) -> int:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    p = argparse.ArgumentParser(
        prog="cite-check",
        description="Check that the sources cited in a report say what the report claims.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("report", help="the report to check, as a Markdown or HTML file")
    p.add_argument(
        "-o",
        "--output",
        default=None,
        help="where to write the HTML result (default: <report>.check.html)",
    )
    p.add_argument(
        "--llm",
        nargs="?",
        const="qwen3:4b",
        default=None,
        metavar="MODEL",
        help="use a local Ollama model as the judge (default model: qwen3:4b)",
    )
    p.add_argument(
        "--allow-private",
        action="store_true",
        help="also fetch sources on local or private network addresses (blocked by default)",
    )
    args = p.parse_args(argv)

    path = Path(args.report)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"ERROR: cannot read {path}: {exc}", file=sys.stderr)
        return 2
    judge = OllamaJudge(args.llm) if args.llm else HeuristicJudge()
    fetcher = Fetcher(allow_private=args.allow_private)
    results = check_report(
        text, fetcher=fetcher, judge=judge, is_html=path.suffix.lower() in {".html", ".htm"}
    )
    out = Path(args.output) if args.output else path.with_suffix(".check.html")
    out.write_text(render_html(results, title=f"Citation check: {path.name}"), encoding="utf-8")
    counts = summarise(results)
    print(
        f"{len(results)} cited claims: " + ", ".join(f"{v} {k}" for k, v in counts.items()),
        file=sys.stderr,
    )
    print(f"report: {out}", file=sys.stderr)
    if args.llm and (n := fallback_count(results)):
        print(
            f"WARNING: the LLM judge failed on {n} claim(s). The heuristic judged those claims.",
            file=sys.stderr,
        )
    if not results:
        print(
            "ERROR: no cited claims found. Check that the report uses a supported citation style.",
            file=sys.stderr,
        )
        return 2
    if counts["unreachable"]:
        print(
            f"WARNING: {counts['unreachable']} claim(s) could not be checked "
            "(source unreachable or reference missing).",
            file=sys.stderr,
        )
    if counts["unsupported"]:
        return 1
    return 3 if counts["unreachable"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
