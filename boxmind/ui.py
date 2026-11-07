"""The local Pygame playground and match inspector."""

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from time import monotonic

import pygame as pg

from .agents import AgentKind
from .engine import MAX_DOTS, MIN_DOTS, State
from .matches import Match, MatchConfig, MoveRecord, PlannedMove, Players, random_players
from .reports import default_report_path, match_outcome, write_match_report
from .ui_lab import Lab
from .ui_widgets import (
    BG, CARD, DIM, INK, LINE, MINT, MUTED, PLAYER_COLORS, PLAYER_FILLS,
    RAISED, SIDEBAR, SIZE, TEXT, VIOLET, WELL, BoardView, Hit, Painter,
)

BOARD = pg.Rect(238, 272, 590, 531)
FIELD = pg.Rect(258, 352, 550, 369)
INSPECTOR = pg.Rect(846, 272, 384, 531)
HISTORY_ROWS = 11
MODES = (
    ("human-ai", "Human vs AI"),
    ("local", "Two players"),
    ("ai-ai", "AI vs AI"),
    ("random", "Random"),
)


@dataclass(slots=True)
class MatchSetup:
    mode: str
    rows: int
    cols: int
    first: AgentKind
    second: AgentKind
    human_seat: int
    starter: int
    seed: int
    depth: int

    @classmethod
    def from_match(cls, config: MatchConfig, randomized: bool) -> "MatchSetup":
        p1, p2 = config.players
        if randomized:
            mode = "random"
        elif p1 is None and p2 is None:
            mode = "local"
        elif None in config.players:
            mode = "human-ai"
        else:
            mode = "ai-ai"
        return cls(
            mode, config.rows, config.cols,
            p1 or AgentKind.GREEDY, p2 or AgentKind.OPTIMIZED,
            int(p1 is not None and p2 is None), config.starter,
            config.seed + int(randomized), config.search.depth,
        )

    def players(self) -> Players:
        if self.mode == "random":
            return random_players(self.seed)
        if self.mode == "local":
            return None, None
        if self.mode == "human-ai":
            return (None, self.second) if self.human_seat == 0 else (self.first, None)
        return self.first, self.second


class App:
    def __init__(self, config: MatchConfig, *, randomized: bool = False):
        self.canvas = pg.Surface(SIZE)
        self.p = Painter(self.canvas)
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="boxmind")
        self.lab = Lab(self.pool)
        self.page = "play"
        self.setup: MatchSetup | None = None
        self.ai_job: Future[PlannedMove] | None = None
        self.reset(config, randomized)

    def reset(self, config: MatchConfig, randomized: bool = False) -> None:
        if self.ai_job:
            self.ai_job.cancel()
        self.ai_job = None
        self.game = Match(config)
        self.randomized = randomized
        self.replay: int | None = None
        self.tab = "decision"
        self.history_offset = self.candidate_offset = self.candidate_max = 0
        self.next_ai_at = monotonic() + 0.45
        self.paused = self.single_step = False
        self.notice = ""
        self.notice_until = 0.0

    def close(self) -> None:
        self.lab.stop.set()
        self.pool.shutdown(cancel_futures=True)

    @property
    def displayed_move(self) -> int:
        return len(self.game.moves) if self.replay is None else self.replay

    def update(self) -> None:
        self.lab.poll()
        if (
            self.page != "play" or self.setup or self.replay is not None
            or self.game.state.terminal or self.game.human_turn
            or (self.paused and not self.single_step)
        ):
            return
        if self.ai_job and self.ai_job.done():
            job, self.ai_job = self.ai_job, None
            try:
                self.game.apply_ai_move(job.result())
            except Exception as exc:
                self.paused = True
                self._notify(f"AI move failed. {exc}")
            self.single_step = False
            self.candidate_offset = 0
            self.next_ai_at = monotonic() + 0.44
        elif self.ai_job is None and monotonic() >= self.next_ai_at:
            self.ai_job = self.pool.submit(self.game.plan_ai_move)

    def _notify(self, message: str) -> None:
        self.notice, self.notice_until = message, monotonic() + 8

    def _export(self) -> None:
        try:
            path = write_match_report(self.game, default_report_path("match"))
            self._notify(f"Saved to reports/{path.name}")
        except OSError as exc:
            self._notify(f"Could not save report. {exc}")

    def _open_setup(self) -> None:
        self.setup = MatchSetup.from_match(self.game.config, self.randomized)

    def _start_match(self) -> None:
        setup = self.setup
        if setup is None:
            return
        search = replace(self.game.config.search, depth=setup.depth)
        self.reset(
            MatchConfig(setup.rows, setup.cols, setup.players(), setup.starter, setup.seed, search),
            setup.mode == "random",
        )
        self.setup = None

    def _restart(self) -> None:
        self.reset(self.game.config, self.randomized)

    def _set_replay(self, index: int | None) -> None:
        self.replay = index
        self.candidate_offset = 0

    def _review(self, step: int) -> None:
        index = min(len(self.game.moves), max(0, self.displayed_move + step))
        self._set_replay(index)

    def _select_history(self, index: int) -> None:
        self._set_replay(index)
        self.tab = "decision"

    def _toggle_pause(self) -> None:
        self.paused = not self.paused
        self.single_step = False
        self.next_ai_at = monotonic()

    def _step(self) -> None:
        self.paused = self.single_step = True
        self.next_ai_at = monotonic()

    def click(self, pos: tuple[int, int]) -> None:
        for hit in reversed(self.p.hits):
            if hit.rect.collidepoint(pos):
                hit.action()
                return
        if (
            self.page == "play" and self.setup is None and self.replay is None
            and self.game.human_turn and FIELD.collidepoint(pos)
        ):
            state = self.game.state
            edge = BoardView.fit(state.board, FIELD).edge_at(state, pos)
            if edge is not None:
                self.game.play_human(edge)
                self.candidate_offset = 0
                self.next_ai_at = monotonic() + 0.26

    def key(self, key: int) -> None:
        if self.setup:
            if key == pg.K_ESCAPE:
                self.setup = None
            elif key == pg.K_RETURN:
                self._start_match()
            return
        if self.page != "play":
            if key == pg.K_ESCAPE:
                self.page = "play"
            return
        if key == pg.K_n:
            self._open_setup()
        elif key == pg.K_r:
            self._restart()
        elif key in (pg.K_END, pg.K_ESCAPE):
            self._set_replay(None)
        elif key in (pg.K_LEFT, pg.K_RIGHT) and self.game.moves:
            self._review(1 if key == pg.K_RIGHT else -1)
        elif key == pg.K_SPACE and any(self.game.agents) and not self.game.state.terminal:
            self._toggle_pause()

    def scroll(self, amount: int, pos: tuple[int, int]) -> None:
        if self.page != "play" or self.setup or not INSPECTOR.collidepoint(pos):
            return
        if self.tab == "history":
            maximum = max(0, len(self.game.moves) - HISTORY_ROWS)
            self.history_offset = min(maximum, max(0, self.history_offset - 3 * amount))
        else:
            self.candidate_offset = min(self.candidate_max, max(0, self.candidate_offset - 2 * amount))

    def draw(self, pointer: tuple[int, int], *, render_size: tuple[int, int] | None = None) -> None:
        if render_size is not None and self.canvas.get_size() != render_size:
            self.canvas = pg.Surface(render_size)
            self.p.resize(self.canvas)
        p = self.p
        p.pointer = pointer if self.setup is None else (-1, -1)
        p.hits.clear()
        self.canvas.fill(BG)
        self._sidebar()
        if self.page == "play":
            self._playground()
        elif self.page == "lab":
            self._heading("02   /   EXPERIMENTS", "Tournament lab",
                          "Compare classical agents across seeded games and alternating starts.")
            self.lab.draw(p)
        else:
            self._guide()
        if self.setup:
            p.pointer = pointer
            p.hits.clear()
            self._draw_setup(self.setup)

    def _sidebar(self) -> None:
        p = self.p
        p.panel(pg.Rect(0, 0, 208, SIZE[1]), SIDEBAR, None, radius=0)
        p.line(LINE, (207, 0), (207, SIZE[1]))
        p.panel(pg.Rect(23, 27, 37, 37), MINT, None, radius=10)
        p.symbol("board", 41, 45, INK)
        p.text("BoxMind", 72, 23, 25, bold=True)
        p.label("Strategy lab", 73, 57, MUTED)

        p.label("Workspace", 24, 118)
        for index, (page, icon, title) in enumerate((
            ("play", "play", "Playground"),
            ("lab", "lab", "Tournament lab"),
            ("guide", "guide", "Field guide"),
        )):
            rect = pg.Rect(14, 141 + index * 52, 180, 45)
            active = self.page == page
            if active or rect.collidepoint(p.pointer):
                p.panel(rect, "#203b3c" if active else RAISED, "#325d58" if active else None, radius=9)
            color = MINT if active else MUTED
            p.symbol(icon, 36, rect.centery, color)
            p.text(title, 55, rect.y + 12, 15, color, bold=active)
            p.hits.append(Hit(rect, lambda value=page: setattr(self, "page", value)))

        p.panel(pg.Rect(18, 346, 172, 159), WELL, LINE, radius=11)
        p.circle(MINT, (34, 369), 3)
        p.label("Local session", 45, 362, MINT)
        p.divider(32, 176, 390)
        cfg = self.game.config
        for y, label, value in (
            (403, "Board", f"{cfg.rows}×{cfg.cols} dots"),
            (434, "Seed", str(cfg.seed)),
            (465, "Depth cap", str(cfg.search.depth)),
        ):
            p.text(label, 32, y, 13, MUTED)
            p.text(value, 176, y, 13, bold=True, align="right", max_width=86)
        p.divider(24, 185, 751)
        p.label("Dots & Boxes", 24, 770, TEXT)
        p.text("Local play · v0.1", 24, 792, 12, DIM)

    def _heading(self, kicker: str, title: str, detail: str) -> None:
        self.p.label(kicker, 238, 27, MINT)
        self.p.text(title, 236, 49, 43, bold=True)
        self.p.text(detail, 238, 112, 16, MUTED)

    def _playground(self) -> None:
        p = self.p
        self._heading("01   /   MATCH ROOM", "Playground", "Connect dots, claim boxes, and review every move.")
        p.button(pg.Rect(976, 58, 102, 43), "Export", self._export, enabled=bool(self.game.moves))
        p.button(pg.Rect(1088, 58, 142, 43), "+ New match", self._open_setup, style="primary")
        move_index = self.displayed_move
        state = self.game.positions[move_index]
        record = self.game.moves[move_index - 1] if move_index else None
        self._scorecards(state)
        self._game_board(state, record)
        self._inspect(record)
        if monotonic() < self.notice_until:
            p.text(self.notice, 238, 813, 13, MINT, max_width=992)
        else:
            p.text("Left / Right  Review moves     ·     Space  Pause AI     ·     N  New match     ·     R  Restart",
                   238, 813, 12, DIM)

    def _scorecards(self, state: State) -> None:
        p = self.p
        for seat, x in enumerate((238, 743)):
            color = PLAYER_COLORS[seat]
            active = state.to_move == seat and not state.terminal
            p.panel(pg.Rect(x, 153, 487, 101), CARD,
                    ("#3f7168" if seat == 0 else "#615680") if active else LINE)
            p.panel(pg.Rect(x + 18, 174, 49, 55), PLAYER_FILLS[seat], None, radius=10)
            p.text("AB"[seat], x + 42, 184, 24, color, bold=True, align="center")
            p.label(f"Player {seat + 1:02}", x + 82, 169, color)
            p.text(self.game.config.player_name(seat), x + 82, 190, 23, bold=True)
            agent = self.game.config.players[seat]
            role = "Human" if agent is None else "Search agent" if agent.searches else "Baseline agent"
            p.text(role, x + 82, 223, 13, MUTED)
            if active:
                p.pill("TO MOVE" if self.replay is None else "NEXT", x + 396, 191, PLAYER_FILLS[seat], color)
            p.text(str(state.scores[seat]), x + 463, 169, 47, color, bold=True, align="right")

    def _board_status(self, state: State) -> str:
        if self.replay is not None:
            return f"Replay · Position after {self.replay} edge{'s' if self.replay != 1 else ''}"
        if state.terminal:
            return f"{match_outcome(self.game)} · All boxes claimed"
        name = self.game.config.player_name(state.to_move)
        if self.game.human_turn:
            return f"{name} to move · Select a dashed edge."
        if self.paused and not self.single_step:
            return f"{name} to move · AI paused"
        return f"{name} is thinking…" if self.ai_job else f"{name} to move"

    def _game_board(self, state: State, record: MoveRecord | None) -> None:
        p = self.p
        p.panel(BOARD)
        p.text("Game board", 258, 287, 22, bold=True)
        p.text(self._board_status(state), 258, 319, 14, MUTED)
        p.pill(f"{state.board.rows}×{state.board.cols} DOTS", 807, 291)
        p.panel(FIELD, WELL, LINE, radius=12)
        view = BoardView.fit(state.board, FIELD)
        hover = (
            view.edge_at(state, p.pointer)
            if self.replay is None and self.game.human_turn else None
        )
        view.draw(p, state, last_edge=record.edge if record else None, hover_edge=hover)

        y = 738
        p.button(pg.Rect(258, y, 35, 34), "‹", lambda: self._review(-1),
                 enabled=self.displayed_move > 0, size=19)
        p.button(pg.Rect(299, y, 35, 34), "›", lambda: self._review(1),
                 enabled=self.displayed_move < len(self.game.moves), size=19)
        p.button(pg.Rect(340, y, 55, 34), "Live", lambda: self._set_replay(None),
                 style="selected" if self.replay is None else "normal")
        p.text(f"{self.displayed_move} / {len(state.board.edges)} edges", 408, y + 8, 14, MUTED)
        ai_available = any(self.game.agents) and not self.game.state.terminal and self.replay is None
        if ai_available:
            if self.paused and not self.game.human_turn:
                p.button(pg.Rect(586, y, 55, 34), "Step", self._step, enabled=not self.single_step)
            p.button(pg.Rect(648, y, 83, 34), "Resume" if self.paused else "Pause AI", self._toggle_pause)
        p.button(pg.Rect(738, y, 70, 34), "Restart", self._restart)
        progress = pg.Rect(258, 788, 550, 4)
        p.panel(progress, LINE, None, radius=2)
        if self.displayed_move:
            width = round(progress.w * self.displayed_move / len(state.board.edges))
            p.panel(pg.Rect(progress.x, progress.y, width, 4), MINT, None, radius=2)

    def _inspect(self, record: MoveRecord | None) -> None:
        p = self.p
        p.panel(INSPECTOR)
        p.text("Move inspector", 865, 287, 22, bold=True)
        p.pill("REPLAY" if self.replay is not None else "LIVE", 1210, 291,
               color=VIOLET if self.replay is not None else MINT)
        for i, tab in enumerate(("decision", "history")):
            p.button(pg.Rect(865 + i * 175, 328, 170, 36), tab.title(),
                     lambda value=tab: setattr(self, "tab", value),
                     style="selected" if self.tab == tab else "normal")
        if self.tab == "history":
            self._history()
        elif record:
            self._decision(record)
        else:
            self._empty_inspector()

    def _empty_inspector(self) -> None:
        p = self.p
        p.panel(pg.Rect(865, 385, 345, 224), WELL, LINE)
        p.panel(pg.Rect(884, 407, 44, 44), "#213d3d", None, radius=10)
        p.symbol("board", 906, 429, MINT)
        p.text("No moves yet", 884, 470, 24, bold=True)
        p.wrapped("Draw an edge to start the log. AI turns show decision time and the "
                  "evidence used to pick a move.", 884, 516, 299, line_height=22)
        p.label("Rule of the board", 865, 652, MINT)
        p.wrapped("Draw the fourth side of a box to claim it and take another turn.",
                  865, 679, 326, size=16, line_height=24)

    def _history(self) -> None:
        p = self.p
        count = len(self.game.moves)
        if not count:
            self._empty_inspector()
            return
        p.text("Select a move to replay that position.", 865, 380, 13, MUTED)
        for label, x in (("#", 875), ("Player", 918), ("Edge", 1053), ("Score", 1139)):
            p.label(label, x, 407)
        end = count - self.history_offset
        start = max(0, end - HISTORY_ROWS)
        for index, move in enumerate(reversed(self.game.moves[start:end])):
            y = 430 + index * 30
            rect = pg.Rect(865, y, 345, 27)
            selected = move.number == self.displayed_move
            fill = "#213e3e" if selected else RAISED if rect.collidepoint(p.pointer) else WELL
            p.panel(rect, fill, None, radius=5)
            color = PLAYER_COLORS[move.player]
            p.text(f"{move.number:02}", 875, y + 5, 12, DIM)
            p.text(self.game.config.player_name(move.player), 918, y + 5, 13, color, bold=True)
            p.text(self.game.state.board.edges[move.edge].label, 1053, y + 5, 13)
            p.text(f"{move.score_after[0]}–{move.score_after[1]}", 1139, y + 5, 13, bold=True)
            p.hits.append(Hit(rect, lambda number=move.number: self._select_history(number)))
        p.text(f"Moves {start + 1}–{end} of {count}  ·  Scroll for older moves",
               865, 773, 12, DIM, max_width=345)

    def _decision(self, record: MoveRecord) -> None:
        p = self.p
        board = self.game.state.board
        label = self.game.config.player_name(record.player)
        color = PLAYER_COLORS[record.player]
        p.label(f"Move {record.number:02}   /   {label}", 865, 382, color)
        p.text(f"Drew {board.edges[record.edge].label}", 865, 401, 23, bold=True)
        if record.captured:
            p.pill(f"+{len(record.captured)} BOX" + ("ES" if len(record.captured) > 1 else ""),
                   1210, 406, PLAYER_FILLS[record.player], color)
        a, b = record.score_before
        c, d = record.score_after
        turn = "kept the turn" if record.extra_turn else "game finished" if record.next_player is None else "turn passed"
        p.text(f"Score {a}–{b} to {c}–{d}  ·  {turn}", 865, 436, 14, MUTED)
        if record.ai is None:
            p.panel(pg.Rect(865, 475, 345, 82), WELL)
            p.label("Human input", 881, 493, color)
            p.text("Edge drawn directly on the board.", 881, 518, 14, MUTED)
            return

        decision = record.ai.decision
        y = p.wrapped(decision.explanation, 865, 465, 345, line_height=18)
        y += 9
        metrics = [("Time", f"{record.ai.elapsed_ms:.2f} ms")]
        stats = decision.search
        if stats:
            metrics.extend((("Nodes", f"{stats.nodes:,}"), ("Depth", f"{stats.depth}/{stats.target_depth}")))
        width = (345 - (len(metrics) - 1) * 6) // len(metrics)
        for index, (metric, value) in enumerate(metrics):
            x = 865 + index * (width + 6)
            p.panel(pg.Rect(x, y, width, 52), WELL, LINE, radius=8)
            p.label(metric, x + 10, y + 7)
            p.text(value, x + 10, y + 23, 16, bold=True, max_width=width - 20)
        y += 63
        if stats and stats.cutoffs is not None:
            more = f"Cutoffs {stats.cutoffs:,}"
            if stats.cache_hits is not None:
                more += f"   ·   Cache hits {stats.cache_hits:,}"
            p.text(more, 865, y - 3, 12, MUTED)
            y += 18
        if decision.candidates:
            self._candidates(record, y)

    def _candidates(self, record: MoveRecord, y: int) -> None:
        p = self.p
        decision = record.ai.decision
        candidates = decision.candidates
        estimates = candidates[0].evaluation is not None
        p.label("Candidate edges", 865, y, TEXT)
        for label, x in (("Edge", 874), ("Close", 970), ("Open", 1041),
                         ("Eval" if estimates else "Pick", 1129)):
            p.label(label, x, y + 22)
        y += 41
        visible = max(1, (767 - y) // 24)
        self.candidate_max = max(0, len(candidates) - visible)
        self.candidate_offset = min(self.candidate_offset, self.candidate_max)
        start = self.candidate_offset
        shown = candidates[start:start + visible]
        for i, item in enumerate(shown):
            row = y + 24 * i
            picked = item.edge == decision.edge
            p.panel(pg.Rect(865, row, 345, 22), "#213e3e" if picked else WELL, None, radius=5)
            p.text(self.game.state.board.edges[item.edge].label, 874, row + 2, 13,
                   MINT if picked else TEXT, bold=picked)
            p.text(str(item.captures), 975, row + 2, 13)
            p.text(str(item.new_threats), 1047, row + 2, 13)
            evaluation = f"{item.evaluation:+.2f}" if estimates else "Chosen" if picked else "—"
            p.text(evaluation, 1129, row + 2, 13, MINT if picked else MUTED)
        note = f"{start + 1}–{start + len(shown)} of {len(candidates)}"
        if self.candidate_max:
            note += "  ·  Scroll to inspect"
        p.text(note, 865, 773, 12, DIM)

    def _setup_number(
        self, setup: MatchSetup, field: str, label: str, x: int, y: int, width: int,
        low: int | None = None, high: int | None = None,
    ) -> None:
        p = self.p
        value = getattr(setup, field)
        p.label(label, x, y)
        p.stepper(pg.Rect(x, y + 19, width, 36), str(value),
                  lambda: setattr(setup, field, value - 1), lambda: setattr(setup, field, value + 1),
                  back=low is None or value > low, forward=high is None or value < high)

    def _setup_player(self, setup: MatchSetup, seat: int, x: int) -> None:
        p = self.p
        player = setup.players()[seat]
        p.label(f"Player {seat + 1}", x, 289, PLAYER_COLORS[seat])
        rect = pg.Rect(x, 308, 244, 36)
        if player is None or setup.mode == "random":
            p.panel(rect, WELL, LINE, radius=8)
            p.text("Human" if player is None else player.label, rect.centerx, 316, 15,
                   bold=True, align="center")
            return
        choices = list(AgentKind)
        index = choices.index(player)
        field = ("first", "second")[seat]
        p.stepper(rect, player.label, lambda: setattr(setup, field, choices[(index - 1) % len(choices)]),
                  lambda: setattr(setup, field, choices[(index + 1) % len(choices)]))

    def _draw_setup(self, setup: MatchSetup) -> None:
        p = self.p
        overlay = pg.Surface(self.canvas.get_size(), pg.SRCALPHA)
        overlay.fill((4, 8, 14, 191))
        self.canvas.blit(overlay, (0, 0))
        p.panel(pg.Rect(350, 106, 560, 628), CARD, "#485b77", radius=17)
        p.label("Match setup", 378, 128, MINT)
        p.text("New match", 377, 151, 32, bold=True)
        p.text("Choose the players, board and starting seat.", 378, 195, 15, MUTED)
        p.button(pg.Rect(852, 129, 31, 31), "×", lambda: setattr(self, "setup", None), size=17)
        for index, (mode, label) in enumerate(MODES):
            p.button(pg.Rect(378 + index * 127, 233, 121, 35), label,
                     lambda value=mode: setattr(setup, "mode", value),
                     style="selected" if setup.mode == mode else "normal", size=13)
        self._setup_player(setup, 0, 378)
        self._setup_player(setup, 1, 638)
        self._setup_number(setup, "rows", "Dot rows", 378, 369, 244, MIN_DOTS, MAX_DOTS)
        self._setup_number(setup, "cols", "Dot columns", 638, 369, 244, MIN_DOTS, MAX_DOTS)
        self._setup_number(setup, "depth", "AI search depth", 378, 444, 244, 1, 12)
        p.label("Starting seat", 638, 444)
        for seat in (0, 1):
            p.button(pg.Rect(638 + seat * 124, 463, 120, 36), f"Player {seat + 1}",
                     lambda value=seat: setattr(setup, "starter", value),
                     style="selected" if setup.starter == seat else "normal")
        self._setup_number(setup, "seed", "Seed", 378, 518, 244)
        if setup.mode == "human-ai":
            p.label("Human seat", 638, 518)
            for seat in (0, 1):
                p.button(pg.Rect(638 + seat * 124, 537, 120, 36), f"Player {seat + 1}",
                         lambda value=seat: setattr(setup, "human_seat", value),
                         style="selected" if setup.human_seat == seat else "normal")
        elif setup.mode == "random":
            p.wrapped("The seed draws two different agents from the pool.", 638, 530, 244)
        p.divider(378, 882, 608)
        boxes = (setup.rows - 1) * (setup.cols - 1)
        p.text(f"{setup.rows}×{setup.cols} dots  ·  {boxes} box{'es' if boxes != 1 else ''}",
               378, 655, 14, MUTED)
        p.button(pg.Rect(646, 641, 99, 44), "Cancel", lambda: setattr(self, "setup", None))
        p.button(pg.Rect(755, 641, 127, 44), "Start match", self._start_match, style="primary")

    def _guide(self) -> None:
        p = self.p
        self._heading("03   /   RULES & AGENTS", "Field guide", "Learn the rules and what each opponent measures.")
        rules = (
            ("01", "Draw one edge", "Join two neighboring dots with a horizontal or vertical edge."),
            ("02", "Close a box", "Claim any box whose fourth side you draw. One edge can close two boxes."),
            ("03", "Keep the turn", "After a capture, move again. The most boxes wins when the board is full."),
        )
        for i, (number, title, detail) in enumerate(rules):
            x = 238 + 337 * i
            p.panel(pg.Rect(x, 153, 318, 193))
            p.label(number, x + 20, 173, MINT)
            p.text(title, x + 20, 206, 23, bold=True)
            p.wrapped(detail, x + 20, 250, 278, size=16, line_height=24)
        p.panel(pg.Rect(238, 367, 992, 435))
        p.text("Agent roster", 258, 389, 24, bold=True)
        p.text("All agents play by the same rules. Search evaluations estimate box margin.",
               258, 428, 15, MUTED)
        for i, (kind, detail) in enumerate(zip(AgentKind, (
            "Samples uniformly from the open edges.",
            "Takes the most boxes now, then favors opening fewer three-sided boxes.",
            "Searches possible replies up to a chosen depth and accounts for extra turns.",
            "Skips branches that cannot change a Minimax value.",
            "Adds tactical move ordering and reuses exact results for repeated positions.",
        ), strict=True)):
            y = 473 + i * 58
            p.panel(pg.Rect(258, y, 952, 49), WELL if i % 2 == 0 else RAISED, None, radius=8)
            p.text(kind.label, 277, y + 13, 16, MINT if kind.searches else VIOLET, bold=True)
            p.text(detail, 444, y + 14, 15)


def _viewport(size: tuple[int, int]) -> pg.Rect:
    width, height = size
    scale = min(width / SIZE[0], height / SIZE[1])
    scaled = (max(1, round(SIZE[0] * scale)), max(1, round(SIZE[1] * scale)))
    return pg.Rect((width - scaled[0]) // 2, (height - scaled[1]) // 2, *scaled)


def _logical(pos: tuple[int, int], viewport: pg.Rect) -> tuple[int, int]:
    return (
        (pos[0] - viewport.x) * SIZE[0] // viewport.w,
        (pos[1] - viewport.y) * SIZE[1] // viewport.h,
    )


def run_app(config: MatchConfig, *, randomized: bool = False) -> None:
    pg.display.init()
    pg.font.init()
    app = None
    window = None
    try:
        desktop_width, desktop_height = pg.display.get_desktop_sizes()[0]
        scale = min(1, max(0.4, min((desktop_width - 80) / SIZE[0], (desktop_height - 150) / SIZE[1])))
        window = pg.Window(
            "BoxMind · Dots and Boxes Strategy Lab",
            size=tuple(round(dimension * scale) for dimension in SIZE),
            position=pg.WINDOWPOS_CENTERED, resizable=True, allow_high_dpi=True,
        )
        app = App(config, randomized=randomized)
        clock = pg.time.Clock()
        while True:
            for event in pg.event.get():
                if event.type in (pg.QUIT, pg.WINDOWCLOSE):
                    return
                if event.type == pg.KEYDOWN:
                    app.key(event.key)
                elif event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
                    app.click(_logical(event.pos, _viewport(window.size)))
                elif event.type == pg.MOUSEWHEEL:
                    app.scroll(event.y, _logical(pg.mouse.get_pos(), _viewport(window.size)))
            app.update()
            surface = window.get_surface()
            viewport = _viewport(surface.get_size())
            pointer = _logical(pg.mouse.get_pos(), _viewport(window.size))
            app.draw(pointer, render_size=viewport.size)
            surface.fill(BG)
            surface.blit(app.canvas, viewport.topleft)
            window.flip()
            clock.tick(60)
    finally:
        if app:
            app.close()
        if window:
            window.destroy()
        pg.quit()
