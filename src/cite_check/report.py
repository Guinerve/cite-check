from __future__ import annotations

import html

from .pipeline import Result, summarise

COLORS = {"supported": ("#1a7f4b", "Green"), "partial": ("#b35900", "Amber"), "unsupported": ("#cf222e", "Red"), "unreachable": ("#6e7781", "Grey")}
LABEL = {"supported": "Supported", "partial": "Partial", "unsupported": "Unsupported", "unreachable": "Source unreachable"}


def render_html(results: list[Result], title: str = "Citation check") -> str:
    counts = summarise(results)
    chips = " ".join(f'<span class="chip" style="--c:{COLORS[k][0]}">{LABEL[k]} {v}</span>' for k, v in counts.items())
    items = []
    for r in results:
        c = COLORS[r.verdict.label][0]
        passage = f'<blockquote>{html.escape(r.verdict.passage)}</blockquote>' if r.verdict.passage else ""
        others = "".join(f'<li>{html.escape(u)}: {LABEL[v.label]}</li>' for u, v in r.others)
        items.append(f'''<article style="--c:{c}"><div class="tag">{LABEL[r.verdict.label]}</div>
<p class="claim">{html.escape(r.claim.text)}</p>
<p class="src"><a href="{html.escape(r.url)}">{html.escape(r.url)}</a> · line {r.claim.line} · judge: {html.escape(r.verdict.judge)}</p>
<p class="why">{html.escape(r.verdict.reason)}</p>{passage}{f"<ul>{others}</ul>" if others else ""}</article>''')
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
:root{{--bg:#fafafa;--fg:#1f2328;--muted:#656d76;--card:#fff;--line:#d8dee4}}
@media(prefers-color-scheme:dark){{:root{{--bg:#0d1117;--fg:#e6edf3;--muted:#8b949e;--card:#161b22;--line:#30363d}}}}
body{{margin:0 auto;max-width:820px;padding:24px 16px 64px;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}}
h1{{margin:0 0 8px}}.chip{{display:inline-block;border:1px solid var(--c);color:var(--c);border-radius:99px;padding:2px 10px;font-size:13px;margin-right:6px}}
article{{background:var(--card);border:1px solid var(--line);border-left:6px solid var(--c);border-radius:8px;padding:10px 14px;margin:12px 0}}
.tag{{color:var(--c);font-weight:700;font-size:12px;text-transform:uppercase;letter-spacing:.05em}}.claim{{margin:4px 0;font-weight:600}}
.src,.why{{margin:2px 0;font-size:13px;color:var(--muted);word-break:break-all}}blockquote{{margin:8px 0 0;padding:6px 10px;border-left:3px solid var(--line);color:var(--muted);font-size:14px}}
.note{{font-size:13px;color:var(--muted)}}</style>
<h1>{html.escape(title)}</h1><p>{chips}</p>
<p class="note">Green means the cited page contains text supporting the claim. It does not mean the claim is true, only that it is faithfully cited.</p>
{"".join(items)}</html>'''
