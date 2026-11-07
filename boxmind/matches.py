"""Shared match runner, replay history, and move logging."""

from dataclasses import dataclass, field
import random
from typing import Callable

from .agents import AgentKind, SearchSettings, TimedDecision, create_agent, time_decision
from .engine import State, bit_indices

Players = tuple[AgentKind | None, AgentKind | None]


@dataclass(frozen=True, slots=True)
class MatchConfig:
    rows: int = 4
    cols: int = 4
    players: Players = (None, AgentKind.OPTIMIZED)
    starter: int = 0
    seed: int = 311
    search: SearchSettings = field(default_factory=SearchSettings)

    def player_name(self, player: int) -> str:
        kind = self.players[player]
        return kind.label if kind else f"Player {player + 1}"


@dataclass(frozen=True, slots=True)
class MoveRecord:
    number: int
    edge: int
    player: int
    score_before: tuple[int, int]
    score_after: tuple[int, int]
    captured: tuple[int, ...]
    next_player: int | None
    ai: TimedDecision | None

    @property
    def extra_turn(self) -> bool:
        return self.next_player == self.player


@dataclass(frozen=True, slots=True)
class PlannedMove:
    state: State
    choice: TimedDecision


class Match:
    def __init__(self, config: MatchConfig):
        self.config = config
        self.positions = [State.new(config.rows, config.cols, config.starter)]
        self.moves: list[MoveRecord] = []
        rng = random.Random(config.seed)
        self.agent_seeds = (rng.getrandbits(64), rng.getrandbits(64))
        self.agents = tuple(
            create_agent(kind, config.search, seed) if kind is not None else None
            for kind, seed in zip(config.players, self.agent_seeds, strict=True)
        )

    @property
    def state(self) -> State:
        return self.positions[-1]

    @property
    def human_turn(self) -> bool:
        return not self.state.terminal and self.agents[self.state.to_move] is None

    def play_human(self, edge: int) -> MoveRecord:
        if not self.human_turn:
            raise ValueError("A human player cannot move in this position")
        return self._play(edge, None)

    def plan_ai_move(self) -> PlannedMove:
        state = self.state
        agent = self.agents[state.to_move]
        if state.terminal or agent is None:
            raise ValueError("An AI player cannot move in this position")
        return PlannedMove(state, time_decision(agent, state))

    def apply_ai_move(self, move: PlannedMove) -> MoveRecord:
        if move.state is not self.state or self.human_turn:
            raise ValueError("The planned AI move belongs to a different position")
        return self._play(move.choice.decision.edge, move.choice)

    def _play(self, edge: int, ai: TimedDecision | None) -> MoveRecord:
        before = self.state
        after = before.play(edge)
        new_boxes = (after.first_boxes | after.second_boxes) ^ (
            before.first_boxes | before.second_boxes
        )
        record = MoveRecord(
            len(self.moves) + 1,
            edge,
            before.to_move,
            before.scores,
            after.scores,
            bit_indices(new_boxes),
            None if after.terminal else after.to_move,
            ai,
        )
        self.positions.append(after)
        self.moves.append(record)
        return record


def random_players(seed: int) -> tuple[AgentKind, AgentKind]:
    first, second = random.Random(seed).sample(list(AgentKind), k=2)
    return first, second


def play_match(config: MatchConfig, *, before_move: Callable[[], None] | None = None) -> Match:
    if None in config.players:
        raise ValueError("Headless play needs two AI players")
    match = Match(config)
    while not match.state.terminal:
        if before_move:
            before_move()
        match.apply_ai_move(match.plan_ai_move())
    return match
