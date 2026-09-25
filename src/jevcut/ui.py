"""What `jevcut clip` and `jevcut run` show while they work.

The pipeline reports events -- transcript loaded, a scan window done, a moment kept or
dropped, a clip rendered -- and a reporter decides how they look. Two exist:

* **Plain** prints the lines jevcut has always printed, one event per line. It is what a
  pipe, a script, a log file or a test gets, and `--plain` forces it.
* **Live** is for a person at a terminal: a header, progress bars that fill as the scan,
  the search and the render run, a log of every moment kept or dropped and why, then the
  clips as a ranked table and a summary with the drop reasons, the Jev requests and what
  they cost.

Nothing here decides anything. Take the reporter away and the pipeline does the same work.
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from jevcut.edl import Clip
from jevcut.models import Transcript


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


class Plain:
    """One line per event, exactly as jevcut printed before reporters existed."""

    def transcribing(self, media: str, model: str):
        return nullcontext()

    def loaded(self, transcript: Transcript, cuts: int, media: str | None) -> None:
        print(f"{len(transcript)} sentences, {cuts} cut points")

    def scan_begin(self, windows: int) -> None:
        pass

    def scan_window(self, done: int, total: int, anchors: int) -> None:
        pass

    def anchors(self, n: int, *, source: str | None = None, requests: int = 0) -> None:
        print(f"{n} anchors from {source}" if source else f"{n} anchors, {requests} requests")

    def incomplete(self, failed: int, total: int, coverage: float) -> None:
        print(
            f"INCOMPLETE SCAN: {failed}/{total} windows failed ({coverage:.0%} covered). "
            "Clips below are a floor, not a result."
        )

    def search_begin(self, anchors: int) -> None:
        pass

    def dropped(self, anchor: Any, reasons: list[str]) -> None:
        print(f"  {anchor.sentence_id}: dropped -- {', '.join(reasons)}")

    def kept(self, anchor: Any, clip: Clip) -> None:
        print(f"  {anchor.sentence_id}: kept ({clip.duration:.0f}s)")

    def gate(self, requests: int, failed: int) -> None:
        print(f"gate: {requests} requests" + (f", {failed} failed and skipped" if failed else ""))

    def clips(self, kept: list[Clip], edl: Path) -> None:
        print(f"\n{len(kept)} clips -> {edl}")
        for c in kept:
            sc = c.scores
            print(
                f"  {c.id}  {sc['composite']:.2f}  {c.t0:7.1f}-{c.t1:7.1f}s ({c.duration:4.1f}s) "
                f"hook {sc.get('hook', 0):.1f} payoff {sc.get('payoff', 0):.1f}  {c.text[:44]}"
            )

    def render_begin(self, n: int) -> None:
        pass

    def rendered(self, clip: Clip) -> None:
        pass

    def render_done(self, n: int, out_dir: Path) -> None:
        print(f"rendered {n} mp4s into {out_dir}/")

    def no_render(self) -> None:
        print("no --media, so nothing rendered; the EDL is enough to re-render later")

    def sheet(self, path: Path) -> None:
        print(f"contact sheet -> {path}")

    def finish(self, *, requests: int, cost: float, out_dir: Path) -> None:
        pass


class Live:
    """Progress bars, a streaming log of moments kept and dropped, and a summary."""

    def __init__(self) -> None:
        from rich.console import Console
        from rich.progress import (
            BarColumn,
            MofNCompleteColumn,
            Progress,
            SpinnerColumn,
            TextColumn,
            TimeElapsedColumn,
        )

        self.console = Console(highlight=False)
        self.progress = Progress(
            SpinnerColumn(style="cyan"),
            TextColumn("[bold]{task.description:<16}"),
            BarColumn(bar_width=36, complete_style="cyan", finished_style="green"),
            MofNCompleteColumn(),
            TextColumn("[dim]{task.fields[note]}"),
            TimeElapsedColumn(),
            console=self.console,
            transient=False,
        )
        self.started = time.monotonic()
        self.tasks: dict[str, Any] = {}
        self.reasons: Counter[str] = Counter()
        self.moments = 0
        self.shipped: list[Clip] = []

    def _task(self, name: str, total: int, note: str = "") -> None:
        if not self.progress.live.is_started:
            self.progress.start()
        self.tasks[name] = self.progress.add_task(name, total=total, note=note)

    def _update(self, name: str, **kw: Any) -> None:
        if name in self.tasks:
            self.progress.update(self.tasks[name], **kw)

    def transcribing(self, media: str, model: str):
        """A spinner while the transcript is made; the slowest step without a count."""
        where = "Lemonfox" if model == "lemonfox" else f"Whisper {model}"
        return self.console.status(
            f"[bold]Transcribing[/] {Path(media).name} [dim]with {where}[/]", spinner="dots"
        )

    def loaded(self, transcript: Transcript, cuts: int, media: str | None) -> None:
        from rich.panel import Panel
        from rich.text import Text

        title = Path(media).name if media else "transcript only"
        body = Text.assemble(
            (f"{_mmss(transcript.duration)}", "bold"),
            " of video  ·  ",
            (f"{len(transcript)}", "bold"),
            " sentences  ·  ",
            (f"{cuts}", "bold"),
            " places it could cut",
        )
        self.console.print(
            Panel(
                body,
                title=f"[bold cyan]jevcut[/]  [white]{title}[/]",
                title_align="left",
                border_style="cyan",
            )
        )

    def scan_begin(self, windows: int) -> None:
        self._task("Finding moments", windows, "reading ~5-minute windows")

    def scan_window(self, done: int, total: int, anchors: int) -> None:
        self._update("Finding moments", completed=done, note=f"{anchors} moments so far")

    def anchors(self, n: int, *, source: str | None = None, requests: int = 0) -> None:
        self.moments = n
        if source:
            self.console.print(f"[dim]{n} moments reused from {source}[/]")
        else:
            self._update("Finding moments", note=f"{n} moments")

    def incomplete(self, failed: int, total: int, coverage: float) -> None:
        self.console.print(
            f"[bold yellow]⚠ {failed} of {total} scan windows failed[/] "
            f"[yellow]({coverage:.0%} covered) — the clips below are a floor.[/]"
        )

    def search_begin(self, anchors: int) -> None:
        self._task("Cutting clips", anchors, "choosing starts and endings")

    def _advance(self) -> None:
        kept = len(self.shipped)
        dropped = sum(self.reasons.values())
        self._update("Cutting clips", advance=1, note=f"{kept} kept · {dropped} dropped")

    def dropped(self, anchor: Any, reasons: list[str]) -> None:
        self.reasons.update(reasons)
        self.progress.console.print(
            f"  [red]✗[/] [dim]{_mmss(anchor.t0):>5}  dropped — {', '.join(reasons)}[/]"
        )
        self._advance()

    def kept(self, anchor: Any, clip: Clip) -> None:
        self.shipped.append(clip)
        sc = clip.scores
        opening = clip.text[:58].rstrip() + ("…" if len(clip.text) > 58 else "")
        self.progress.console.print(
            f"  [green]✓[/] [bold]{_mmss(clip.t0):>5}–{_mmss(clip.t1):<5}[/] "  # noqa: RUF001 - a time range
            f"[cyan]{clip.duration:3.0f}s[/]  hook [bold]{sc.get('hook', 0):.1f}[/] "
            f"payoff [bold]{sc.get('payoff', 0):.1f}[/]  [dim italic]“{opening}”[/]"
        )
        self._advance()

    def gate(self, requests: int, failed: int) -> None:
        if failed:
            self.progress.console.print(f"[yellow]{failed} requests failed and were skipped[/]")

    def clips(self, kept: list[Clip], edl: Path) -> None:
        # Shown with the summary, once the render is done, so the progress display runs
        # from the scan to the last mp4 without being torn down in between.
        self.ranked, self.edl = kept, edl

    def _table(self, kept: list[Clip], edl: Path) -> None:
        from rich.table import Table

        table = Table(
            title=f"[bold]{len(kept)} clips, best first[/]",
            title_justify="left",
            border_style="dim",
            header_style="bold cyan",
            expand=False,
        )
        for col, kw in (
            ("#", {"justify": "right"}),
            ("when", {}),
            ("len", {"justify": "right"}),
            ("score", {}),
            ("hook", {"justify": "right"}),
            ("payoff", {"justify": "right"}),
            ("opens with", {"max_width": 56, "no_wrap": True, "overflow": "ellipsis"}),
        ):
            table.add_column(col, **kw)
        best = max((c.scores.get("composite", 0.0) for c in kept), default=1.0) or 1.0
        for c in kept[:15]:
            sc = c.scores
            bar = "█" * max(1, round(10 * sc.get("composite", 0.0) / best))
            table.add_row(
                str(c.rank),
                f"{_mmss(c.t0)}–{_mmss(c.t1)}",  # noqa: RUF001 - a time range
                f"{c.duration:.0f}s",
                f"[green]{bar:<10}[/] {sc.get('composite', 0.0):.2f}",
                f"{sc.get('hook', 0):.1f}",
                f"{sc.get('payoff', 0):.1f}",
                f"[dim]{c.text}[/]",
            )
        if len(kept) > 15:
            table.caption = f"[dim]…and {len(kept) - 15} more in {edl}[/]"
        self.console.print()
        self.console.print(table)

    def render_begin(self, n: int) -> None:
        self._task("Rendering", n, "ffmpeg, frame-accurate")

    def rendered(self, clip: Clip) -> None:
        self._update("Rendering", advance=1, note=f"{clip.id}.mp4")

    def render_done(self, n: int, out_dir: Path) -> None:
        pass

    def no_render(self) -> None:
        pass

    def sheet(self, path: Path) -> None:
        self.sheet_path = path

    def finish(self, *, requests: int, cost: float, out_dir: Path) -> None:
        from rich.columns import Columns
        from rich.panel import Panel
        from rich.table import Table

        self._stop()
        if hasattr(self, "ranked"):
            self._table(self.ranked, self.edl)
        elapsed = time.monotonic() - self.started
        final = getattr(self, "ranked", self.shipped)  # after overlapping clips are merged
        merged = len(self.shipped) - len(final)
        dropped = sum(self.reasons.values())

        stats = Table.grid(padding=(0, 2))
        stats.add_column(style="dim")
        stats.add_column(style="bold")
        stats.add_row("moments found", str(self.moments or len(self.shipped) + dropped))
        stats.add_row("clips shipped", f"[green]{len(final)}[/]")
        if merged:
            stats.add_row("overlaps merged", str(merged))
        if final:
            lengths = sorted(c.duration for c in final)
            stats.add_row("median length", f"{lengths[len(lengths) // 2]:.0f}s")
        stats.add_row("Jev requests", f"{requests:,}")
        stats.add_row("cost", f"${cost:.3f}")
        stats.add_row("time", f"{elapsed:.0f}s")

        reasons = Table.grid(padding=(0, 1))
        reasons.add_column(style="dim", justify="right")
        reasons.add_column()
        top = max(self.reasons.values(), default=1)
        for reason, n in self.reasons.most_common(6):
            reasons.add_row(reason, f"[red]{'▇' * max(1, round(18 * n / top))}[/] {n}")
        if not self.reasons:
            reasons.add_row("", "[dim]nothing dropped[/]")

        self.console.print()
        self.console.print(
            Columns(
                [
                    Panel(stats, title="[bold]run[/]", border_style="cyan"),
                    Panel(reasons, title="[bold]why moments were dropped[/]", border_style="red"),
                ]
            )
        )
        sheet = getattr(self, "sheet_path", out_dir / "index.html")
        self.console.print(
            f"[bold green]✓[/] clips in [bold]{out_dir}/[/]  ·  "
            f"watch them: [bold cyan]{sheet}[/]  ·  edit the cut: [bold]{out_dir / 'edl.json'}[/]"
        )

    def _stop(self) -> None:
        if self.progress.live.is_started:
            self.progress.stop()


def reporter(plain: bool = False) -> Plain | Live:
    """Live for a person at a terminal; Plain for pipes, files, tests, or on request."""
    if plain or not sys.stdout.isatty():
        return Plain()
    try:
        return Live()
    except ImportError:  # pragma: no cover - rich is a dependency, but never fail a run on looks
        return Plain()
