"""The contact sheet: one static page listing a run's clips, best first.

It is for the human who has to watch the output, so it shows what they need to judge a
clip and nothing they would have to decode: the player, the words, where it sits in the
source, and the scores that ranked it. The gate's Nouls are there too, folded away --
when a clip is bad, they are the first place to look for why it shipped.

Plain HTML, no scripts, no network: it has to open from a directory on disk.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from jevcut.edl import Clip

#: Gate Nouls in the order a reader would check them: drop reason first, then the edges.
GATE_NOULS = (
    "needs_the_room",
    "starts_mid_thought",
    "dangling_reference",
    "ends_mid_thought",
    "standalone",
)

STYLE = """
:root { --bg:#fafafa; --card:#fff; --fg:#1a1a1a; --muted:#666; --line:#e2e2e2;
  --accent:#2457d6; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#141414; --card:#1e1e1e; --fg:#eaeaea; --muted:#9a9a9a; --line:#333;
    --accent:#7aa2ff; }
}
* { box-sizing: border-box; }
body { margin:0; padding:24px 16px; background:var(--bg); color:var(--fg);
  font:15px/1.5 system-ui, sans-serif; }
main { max-width:980px; margin:0 auto; }
h1 { font-size:20px; margin:0 0 4px; }
.sub { color:var(--muted); margin:0 0 24px; overflow-wrap:anywhere; }
article { display:grid; grid-template-columns:minmax(0,360px) minmax(0,1fr); gap:16px;
  background:var(--card); border:1px solid var(--line); border-radius:8px; padding:16px;
  margin-bottom:16px; }
@media (max-width:720px) { article { grid-template-columns:1fr; } }
video { width:100%; max-height:480px; background:#000; border-radius:4px; }
.none { color:var(--muted); font-style:italic; }
h2 { font-size:16px; margin:0 0 4px; }
.rank { color:var(--accent); }
.meta { color:var(--muted); font-size:13px; margin:0 0 8px; }
.scores { display:flex; flex-wrap:wrap; gap:6px 16px; font-size:13px; margin:0 0 8px; }
.scores b { font-variant-numeric:tabular-nums; }
blockquote { margin:0 0 8px; padding-left:12px; border-left:3px solid var(--line); }
details { font-size:13px; color:var(--muted); }
table { border-collapse:collapse; margin-top:4px; }
td { padding:1px 12px 1px 0; font-variant-numeric:tabular-nums; }
"""


def _clock(t: float) -> str:
    m, s = divmod(round(t), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _card(clip: Clip, video: Path | None) -> str:
    sc = clip.scores
    player = (
        f'<video src="{escape(video.name)}" controls preload="metadata"></video>'
        if video
        else '<p class="none">not rendered</p>'
    )
    gate = "".join(
        f"<tr><td>{escape(name)}</td><td>{sc[name]:.2f}</td></tr>"
        for name in GATE_NOULS
        if name in sc
    )
    return f"""<article id="{escape(clip.id)}">
<div>{player}</div>
<div>
<h2><span class="rank">#{clip.rank}</span> {escape(clip.id)}</h2>
<p class="meta">{_clock(clip.t0)}&ndash;{_clock(clip.t1)} in the source · {clip.duration:.1f}s ·
anchor {escape(clip.anchor_id)} · {escape(clip.kind)}</p>
<p class="scores"><span>composite <b>{sc.get("composite", 0):.2f}</b></span>
<span>hook <b>{sc.get("hook", 0):.1f}</b>/3</span>
<span>payoff <b>{sc.get("payoff", 0):.1f}</b>/2</span></p>
<blockquote>{escape(clip.text)}</blockquote>
<details><summary>gate</summary><table>{gate}</table></details>
</div>
</article>"""


def write_sheet(clips: list[Clip], path: str | Path, *, source: str = "") -> Path:
    """Write ``index.html`` for ``clips``; a clip gets a player if its mp4 sits beside it."""
    path = Path(path)
    ranked = sorted(clips, key=lambda c: c.rank or len(clips) + 1)
    cards = []
    for c in ranked:
        mp4 = path.parent / f"{c.id}.mp4"
        cards.append(_card(c, mp4 if mp4.exists() else None))
    count = f"{len(clips)} clip{'s' if len(clips) != 1 else ''}, best first"
    body = "\n".join(cards) or '<p class="none">No clip passed the gate.</p>'
    path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>jevcut clips</title>
<style>{STYLE}</style>
</head>
<body>
<main>
<h1>jevcut clips</h1>
<p class="sub">{count}{" from " + escape(source) if source else ""}</p>
{body}
</main>
</body>
</html>
"""
    )
    return path
