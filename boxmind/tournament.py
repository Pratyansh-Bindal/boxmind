"""Seeded schedules and aggregate metrics for completed games."""

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
import math
import random
from statistics import mean, median
from typing import Callable, Iterable

from .agents import AgentKind, SearchSettings
from .engine import board_for
from .matches import Match, MatchConfig, play_match


@dataclass(frozen=True, slots=True)
class TournamentConfig:
    agents: tuple[AgentKind, ...] = tuple(AgentKind)
    boards: tuple[tuple[int, int], ...] = ((3, 3),)
    games: int = 8
    seed: int = 311
    search: SearchSettings = field(default_factory=SearchSettings)
    random_pairs: bool = False

    def __post_init__(self) -> None:
        if len(set(self.agents)) != len(self.agents) or len(self.agents) < 2:
            raise ValueError("Select at least two distinct agents")
        if self.games < 2 or self.games % 2:
            raise ValueError("Games must be a positive even count of at least two")
        if not self.boards or len(set(self.boards)) != len(self.boards):
            raise ValueError("Select one or more distinct board sizes")
        for rows, cols in self.boards:
            board_for(rows, cols)

    @property
    def total_games(self) -> int:
        pairs = 1 if self.random_pairs else math.comb(len(self.agents), 2)
        return len(self.boards) * pairs * self.games

    def schedule(self) -> Iterable[MatchConfig]:
        rng = random.Random(self.seed)
        for rows, cols in self.boards:
            if self.random_pairs:
                blocks = (tuple(rng.sample(self.agents, 2)) for _ in range(self.games // 2))
            else:
                blocks = (
                    pair
                    for pair in combinations(self.agents, 2)
                    for _ in range(self.games // 2)
                )
            for players in blocks:
                seed = rng.getrandbits(64)
                for starter in (0, 1):
                    yield MatchConfig(rows, cols, players, starter, seed, self.search)


@dataclass(frozen=True, slots=True)
class TournamentResult:
    config: TournamentConfig
    matches: tuple[Match, ...]


class TournamentCancelled(Exception):
    """The user stopped a tournament before export."""


def run_tournament(
    config: TournamentConfig,
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> TournamentResult:
    def check_cancelled():
        if cancelled and cancelled():
            raise TournamentCancelled

    matches = []
    for setup in config.schedule():
        matches.append(play_match(setup, before_move=check_cancelled))
        if progress:
            progress(len(matches))
    check_cancelled()
    return TournamentResult(config, tuple(matches))


@dataclass(frozen=True, slots=True)
class Stats:
    agent: AgentKind
    opponent: AgentKind | None
    board: str | None
    started: bool | None
    games: int
    wins: int
    losses: int
    draws: int
    win_rate: float
    loss_rate: float
    draw_rate: float
    mean_margin: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    mean_nodes: float | None
    mean_depth: float | None
    mean_cutoffs: float | None
    mean_cache_hits: float | None
    budget_limited_moves: int


def _mean(values: list[int]) -> float | None:
    return mean(values) if values else None


def _stats(
    agent: AgentKind,
    opponent: AgentKind | None,
    board: str | None,
    started: bool | None,
    seats: list[tuple[Match, int]],
) -> Stats:
    margins = [game.state.scores[seat] - game.state.scores[1 - seat] for game, seat in seats]
    wins = sum(margin > 0 for margin in margins)
    losses = sum(margin < 0 for margin in margins)
    draws = len(seats) - wins - losses
    choices = [
        move.ai
        for game, seat in seats
        for move in game.moves
        if move.player == seat and move.ai is not None
    ]
    times = sorted(choice.elapsed_ms for choice in choices)
    searches = [choice.decision.search for choice in choices if choice.decision.search is not None]
    return Stats(
        agent, opponent, board, started, len(seats), wins, losses, draws,
        wins / len(seats), losses / len(seats), draws / len(seats), mean(margins),
        mean(times) if times else 0.0,
        median(times) if times else 0.0,
        times[math.ceil(0.95 * len(times)) - 1] if times else 0.0,
        _mean([search.nodes for search in searches]),
        _mean([search.depth for search in searches]),
        _mean([search.cutoffs for search in searches if search.cutoffs is not None]),
        _mean([search.cache_hits for search in searches if search.cache_hits is not None]),
        sum(search.limit_reached is not None for search in searches),
    )


def summarize(result: TournamentResult, *, by_matchup: bool = False) -> list[Stats]:
    groups = defaultdict(list)
    for game in result.matches:
        for seat, kind in enumerate(game.config.players):
            opponent = game.config.players[1 - seat]
            if by_matchup:
                key = (kind, opponent, game.state.board.size, game.config.starter == seat)
            else:
                key = (kind, None, None, None)
            groups[key].append((game, seat))
    rows = [_stats(*key, seats) for key, seats in groups.items()]
    return sorted(rows, key=lambda row: (-row.win_rate, -row.mean_margin, row.agent))
