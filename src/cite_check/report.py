from __future__ import annotations

import html

from .pipeline import Result, summarise

LABEL = {
    "supported": "Supported",
    "partial": "Partial",
    "unsupported": "Unsupported",
    "unreachable": "Source unreachable",
}

# Verdict colours meet WCAG AA (4.5:1 or more) on the card and page background in both themes.
CSS = """
:root{--bg:#f6f8fa;--fg:#1f2328;--muted:#59636e;--card:#fff;--line:#d1d9e0;--link:#0969da;
--supported:#1a7f37;--partial:#9a6700;--unsupported:#cf222e;--unreachable:#59636e}
@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#9198a1;--card:#161b22;
--line:#30363d;--link:#58a6ff;--supported:#3fb950;--partial:#d29922;--unsupported:#f85149;--unreachable:#9198a1}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:820px;margin:0 auto;padding:32px 16px 64px}
h1{margin:0 0 4px;font-size:clamp(22px,4vw,30px);line-height:1.25;overflow-wrap:anywhere}
.count{margin:0 0 14px;color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 14px;padding:0;list-style:none}
.chip{border:1px solid var(--c);color:var(--c);border-radius:99px;padding:3px 12px;font-size:14px;font-weight:600}
.chip b{font-variant-numeric:tabular-nums}
.chip.zero{border-color:var(--line);color:var(--muted);font-weight:400}
.note{margin:0 0 20px;font-size:14px;color:var(--muted)}
article{background:var(--card);border:1px solid var(--line);border-left:6px solid var(--c);border-radius:8px;
padding:14px 16px;margin:0 0 14px}
.supported{--c:var(--supported)}.partial{--c:var(--partial)}.unsupported{--c:var(--unsupported)}
.unreachable{--c:var(--unreachable)}
.tag{color:var(--c);font-weight:700;font-size:13px;text-transform:uppercase;letter-spacing:.05em}
.claim{margin:4px 0 8px;font-size:17px;font-weight:600}
.src,.why{margin:2px 0;font-size:14px;color:var(--muted)}
.src a{color:var(--link);overflow-wrap:anywhere}
.why{color:var(--fg)}
blockquote{margin:10px 0 0;padding:8px 12px;border-left:3px solid var(--line);color:var(--muted);font-size:14px}
.others{margin:10px 0 0;padding-left:20px;font-size:14px;color:var(--muted);overflow-wrap:anywhere}
"""


def _claim_html(r: Result) -> str:
    label = r.verdict.label
    if r.url:
        src = f'<a href="{html.escape(r.url)}">{html.escape(r.url)}</a>'
    else:
        src = "no source URL"
    passage = (
        f"<blockquote>{html.escape(r.verdict.passage)}</blockquote>" if r.verdict.passage else ""
    )
    others = "".join(f"<li>{html.escape(u)}: {LABEL[v.label]}</li>" for u, v in r.others)
    others_html = f'<ul class="others">{others}</ul>' if others else ""
    return (
        f'<article class="{label}"><div class="tag">{LABEL[label]}</div>\n'
        f'<p class="claim">{html.escape(r.claim.text)}</p>\n'
        f'<p class="src">{src} · line {r.claim.line} · judge: {html.escape(r.verdict.judge)}</p>\n'
        f'<p class="why">{html.escape(r.verdict.reason)}</p>{passage}{others_html}</article>'
    )


def render_html(results: list[Result], title: str = "Citation check") -> str:
    counts = summarise(results)
    chips = "".join(
        f'<li class="chip {k}{" zero" if not v else ""}">{LABEL[k]} <b>{v}</b></li>'
        for k, v in counts.items()
    )
    noun = "claim" if len(results) == 1 else "claims"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{html.escape(title)}</title><style>{CSS}</style></head>
<body><main>
<h1>{html.escape(title)}</h1>
<p class="count">{len(results)} cited {noun} checked</p>
<ul class="chips">{chips}</ul>
<p class="note">Supported means the cited page has text that supports the claim. \
It does not mean that the claim is true. It means only that the source says it.</p>
{"".join(_claim_html(r) for r in results)}
</main></body></html>"""
