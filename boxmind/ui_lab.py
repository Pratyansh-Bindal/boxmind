"""The tournament workspace and its background job."""

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from queue import SimpleQueue
from threading import Event

import pygame as pg

from .agents import AgentKind, SearchSettings
from .engine import MAX_DOTS, MIN_DOTS
from .reports import default_report_path, write_tournament_report
from .tournament import Stats, TournamentCancelled, TournamentConfig, run_tournament, summarize
from .ui_widgets import DIM, LINE, MINT, MUTED, RAISED, TEXT, VIOLET, WELL, Painter


@dataclass(slots=True)
class LabSetup:
    agents: set[AgentKind] = field(default_factory=lambda: set(AgentKind))
    rows: int = 3
    cols: int = 3
    games: int = 8
    depth: int = 3
    seed: int = 311
    random_pairs: bool = False

    def config(self) -> TournamentConfig:
        return TournamentConfig(
            tuple(kind for kind in AgentKind if kind in self.agents),
            ((self.rows, self.cols),), self.games, self.seed,
            SearchSettings(depth=self.depth), self.random_pairs,
        )


@dataclass(frozen=True, slots=True)
class LabResult:
    rows: list[Stats]
    config: TournamentConfig
    path: Path


def _run(config: TournamentConfig, updates: SimpleQueue[int], stop: Event) -> LabResult:
    result = run_tournament(config, updates.put, stop.is_set)
    path = write_tournament_report(result, default_report_path("tournament"))
    return LabResult(summarize(result), config, path)


class Lab:
    def __init__(self, pool: ThreadPoolExecutor):
        self.pool = pool
        self.setup = LabSetup()
        self.job: Future[LabResult] | None = None
        self.updates: SimpleQueue[int] = SimpleQueue()
        self.stop = Event()
        self.total = self.completed = 0
        self.result: LabResult | None = None
        self.message = ""

    def start(self) -> None:
        if self.job:
            return
        try:
            config = self.setup.config()
        except ValueError as exc:
            self.message = str(exc)
            return
        self.total, self.completed = config.total_games, 0
        self.stop.clear()
        self.job = self.pool.submit(_run, config, self.updates, self.stop)
        self.message = ""
        self.result = None

    def poll(self) -> None:
        if not self.job:
            return
        while not self.updates.empty():
            self.completed = self.updates.get_nowait()
        if self.job.done():
            try:
                self.result = self.job.result()
            except TournamentCancelled:
                self.message = "Tournament stopped."
            except Exception as exc:
                self.message = f"Tournament failed. {exc}"
            self.job = None

    def _toggle(self, kind: AgentKind) -> None:
        if kind in self.setup.agents:
            self.setup.agents.remove(kind)
        else:
            self.setup.agents.add(kind)
        self.message = ""

    def _number(
        self, p: Painter, field_name: str, label: str, x: int, y: int, width: int,
        minimum: int | None = None, maximum: int | None = None, step: int = 1,
    ) -> None:
        value = getattr(self.setup, field_name)
        p.label(label, x, y)
        p.stepper(
            pg.Rect(x, y + 20, width, 36), str(value),
            lambda: setattr(self.setup, field_name, value - step),
            lambda: setattr(self.setup, field_name, value + step),
            back=self.job is None and (minimum is None or value > minimum),
            forward=self.job is None and (maximum is None or value < maximum),
        )

    def draw(self, p: Painter) -> None:
        if self.job:
            p.button(pg.Rect(1076, 58, 154, 43), "Stop run", self.stop.set,
                     enabled=not self.stop.is_set())
        else:
            p.button(pg.Rect(1058, 58, 172, 43), "Run tournament", self.start, style="primary")
        p.panel(pg.Rect(238, 153, 346, 649))
        p.text("Experiment setup", 258, 176, 22, bold=True)
        p.text("Set the lineup and game budget.", 258, 209, 14, MUTED)
        p.label("Schedule", 258, 249)
        for i, random_pairs in enumerate((False, True)):
            p.button(
                pg.Rect(258 + i * 155, 268, 151, 36),
                "Random pairs" if random_pairs else "Round robin",
                lambda value=random_pairs: setattr(self.setup, "random_pairs", value),
                style="selected" if self.setup.random_pairs == random_pairs else "normal",
                enabled=self.job is None,
            )
        p.label("Agent pool", 258, 329)
        for index, kind in enumerate(AgentKind):
            if index < 3:
                x, y, width = 258 + index * 103, 348, 100
            else:
                x, y, width = 258 + (index - 3) * 155, 389, 151
            p.button(
                pg.Rect(x, y, width, 35), kind.label, lambda value=kind: self._toggle(value),
                style="selected" if kind in self.setup.agents else "normal",
                enabled=self.job is None,
            )
        self._number(p, "rows", "Dot rows", 258, 451, 149, MIN_DOTS, MAX_DOTS)
        self._number(p, "cols", "Dot columns", 415, 451, 149, MIN_DOTS, MAX_DOTS)
        games_label = "Games per board" if self.setup.random_pairs else "Games per pair"
        self._number(p, "games", games_label, 258, 522, 149, 2, 80, 2)
        self._number(p, "depth", "Search depth", 415, 522, 149, 1, 8)
        self._number(p, "seed", "Seed", 258, 593, 149)
        p.label("Node cap / move", 415, 593)
        p.text("20,000", 415, 619, 17, bold=True)
        p.divider(258, 564, 670)
        try:
            total = self.setup.config().total_games
            p.text(f"{total} scheduled games", 258, 690, 17, MINT, bold=True)
        except ValueError:
            p.text("Select at least two agents", 258, 690, 17, VIOLET, bold=True)
        p.wrapped("Each two-game block shares a seed and switches the starting agent.",
                  258, 722, 300)
        self._draw_results(p)

    def _draw_results(self, p: Painter) -> None:
        p.panel(pg.Rect(602, 153, 628, 649))
        p.text("Results", 624, 176, 22, bold=True)
        status = "RUNNING" if self.job else "COMPLETE" if self.result else "READY"
        p.pill(status, 1207, 177, color=MINT if self.job or self.result else MUTED)
        p.divider(624, 1208, 218)
        if self.job:
            self._draw_progress(p)
        elif self.result:
            self._draw_summary(p, self.result)
        else:
            p.panel(pg.Rect(624, 242, 584, 209), WELL)
            p.symbol("lab", 654, 278, MINT)
            p.text("Run a comparison", 646, 310, 25, bold=True)
            p.wrapped("Play a balanced schedule, then compare outcomes and decision latency "
                      "for each agent.", 646, 355, 502, size=16, line_height=24)
            for y, number, title, detail in (
                (486, "01", "Set the lineup", "Select a pair or compare the full agent pool."),
                (568, "02", "Alternate the start", "Each agent gets one start per two-game block."),
                (650, "03", "Inspect the data", "Open the CSVs for opponents, board size and starter."),
            ):
                p.text(number, 626, y, 15, MINT, bold=True)
                p.text(title, 668, y - 3, 17, bold=True)
                p.text(detail, 668, y + 22, 14, MUTED)
            if self.message:
                p.text(self.message, 624, 760, 14, VIOLET, max_width=582)

    def _draw_progress(self, p: Painter) -> None:
        title = "Stopping tournament…" if self.stop.is_set() else "Playing headless matches"
        p.text(title, 624, 260, 24, bold=True)
        p.text(f"{self.completed} / {self.total} games complete", 624, 307, 16, MUTED)
        bar = pg.Rect(624, 347, 582, 10)
        p.panel(bar, WELL, None, radius=5)
        if self.completed:
            width = max(3, round(bar.w * self.completed / self.total))
            p.panel(pg.Rect(bar.x, bar.y, width, bar.h), MINT, None, radius=5)
        p.wrapped("The tournament runs in the background. You can keep playing or review "
                  "a match while the results are collected.", 624, 390, 540)

    def _draw_summary(self, p: Painter, result: LabResult) -> None:
        rows, cols = result.config.boards[0]
        p.text(f"{result.config.total_games} games  ·  {rows}×{cols} dots  ·  Seed {result.config.seed}",
               624, 238, 15, MUTED, max_width=584)
        for label, x in (("Agent", 639), ("W / L / D", 803), ("Win", 930),
                         ("Margin", 1005), ("P95 ms", 1105)):
            p.label(label, x, 285)
        for index, row in enumerate(result.rows):
            y = 306 + index * 55
            p.panel(pg.Rect(624, y, 584, 48), WELL if index % 2 == 0 else RAISED, None, radius=8)
            p.text(row.agent.label, 639, y + 11, 15, bold=True)
            p.text(f"{row.wins} / {row.losses} / {row.draws}", 803, y + 11, 15)
            p.text(f"{row.win_rate:.0%}", 930, y + 11, 15, MINT, bold=True)
            p.text(f"{row.mean_margin:+.2f}", 1005, y + 11, 15)
            p.text(f"{row.p95_ms:.3f}", 1105, y + 11, 15)
            start = 640
            for rate, color in ((row.win_rate, MINT), (row.draw_rate, DIM), (row.loss_rate, VIOLET)):
                width = round(rate * 128)
                if width:
                    p.panel(pg.Rect(start, y + 35, width, 3), color, None, radius=0)
                    start += width
        p.panel(pg.Rect(624, 625, 584, 143), WELL, LINE)
        p.label("Report saved", 642, 644, MINT)
        p.text(str(Path("reports") / result.path.name), 642, 668, 15, TEXT, bold=True,
               max_width=540)
        p.wrapped("The report includes summaries, opponent and starter splits, game seeds, "
                  "and decision logs.", 642, 706, 535)
