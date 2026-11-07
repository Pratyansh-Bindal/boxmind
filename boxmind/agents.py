"""Interchangeable classical agents and measured search decisions."""

from dataclasses import dataclass
from enum import StrEnum
import math
import random
from time import perf_counter
from typing import Protocol

from .engine import State


class AgentKind(StrEnum):
    RANDOM = "random"
    GREEDY = "greedy"
    MINIMAX = "minimax"
    ALPHA_BETA = "alpha-beta"
    OPTIMIZED = "optimized"

    @property
    def label(self) -> str:
        return AGENT_LABELS[self]

    @property
    def searches(self) -> bool:
        return self in (self.MINIMAX, self.ALPHA_BETA, self.OPTIMIZED)


AGENT_LABELS = {
    AgentKind.RANDOM: "Random",
    AgentKind.GREEDY: "Greedy",
    AgentKind.MINIMAX: "Minimax",
    AgentKind.ALPHA_BETA: "Alpha–Beta",
    AgentKind.OPTIMIZED: "Optimized",
}


@dataclass(frozen=True, slots=True)
class SearchSettings:
    depth: int = 3
    node_limit: int = 20_000
    time_limit_ms: float | None = None
    threat_weight: float = 0.35

    def __post_init__(self) -> None:
        if not 1 <= self.depth <= 12:
            raise ValueError("Search depth must be between 1 and 12")
        if self.node_limit < 1:
            raise ValueError("Node limit must be positive")
        if self.time_limit_ms is not None and (
            not math.isfinite(self.time_limit_ms) or self.time_limit_ms <= 0
        ):
            raise ValueError("Time limit must be a positive number of milliseconds")
        if not 0 <= self.threat_weight <= 1:
            raise ValueError("Threat weight must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class Candidate:
    edge: int
    captures: int
    new_threats: int
    evaluation: float | None = None


@dataclass(frozen=True, slots=True)
class SearchStats:
    depth: int
    target_depth: int
    nodes: int
    cutoffs: int | None
    cache_hits: int | None
    limit_reached: str | None


@dataclass(frozen=True, slots=True)
class Decision:
    edge: int
    explanation: str
    candidates: tuple[Candidate, ...] = ()
    search: SearchStats | None = None


class Agent(Protocol):
    def choose_move(self, state: State) -> Decision: ...


@dataclass(frozen=True, slots=True)
class TimedDecision:
    decision: Decision
    elapsed_ms: float


def time_decision(agent: Agent, state: State) -> TimedDecision:
    start = perf_counter()
    decision = agent.choose_move(state)
    return TimedDecision(decision, (perf_counter() - start) * 1000)


def _legal_edges(state: State) -> tuple[int, ...]:
    legal = state.legal_edges()
    if not legal:
        raise ValueError("Cannot choose a move from a finished game")
    return legal


def _candidate(state: State, edge: int, evaluation: float | None = None) -> Candidate:
    tactics = state.tactics(edge)
    return Candidate(edge, tactics.captures, tactics.new_threats, evaluation)


def _greedy_rank(candidate: Candidate) -> tuple[int, int]:
    return candidate.captures, -candidate.new_threats


def _greedy_reason(candidate: Candidate) -> str:
    if candidate.captures:
        return (
            f"Claims {candidate.captures} now, the most boxes available, "
            "then favors opening fewer three-sided boxes."
        )
    if not candidate.new_threats:
        return "Draws an edge without leaving a new three-sided box."
    return (
        f"Every legal edge opens a box. This move opens {candidate.new_threats}, "
        "the fewest available."
    )


class RandomAgent:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)

    def choose_move(self, state: State) -> Decision:
        legal = _legal_edges(state)
        return Decision(self.rng.choice(legal), f"Sampled uniformly from {len(legal)} legal edges.")


class GreedyAgent:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)

    def choose_move(self, state: State) -> Decision:
        candidates = tuple(
            sorted(
                (_candidate(state, edge) for edge in _legal_edges(state)),
                key=_greedy_rank,
                reverse=True,
            )
        )
        best_rank = _greedy_rank(candidates[0])
        tied = [candidate for candidate in candidates if _greedy_rank(candidate) == best_rank]
        picked = self.rng.choice(tied)
        ordered = (picked,) + tuple(candidate for candidate in candidates if candidate != picked)
        reason = _greedy_reason(picked)
        if len(tied) > 1:
            reason += f" Sampled among {len(tied)} equally ranked edges."
        return Decision(picked.edge, reason, ordered)


class _BudgetReached(Exception):
    pass


class _Search:
    """One decision's search. The cache stores only exact values at a given depth."""

    def __init__(self, kind: AgentKind, settings: SearchSettings, perspective: int):
        self.settings = settings
        self.perspective = perspective
        self.pruning = kind != AgentKind.MINIMAX
        self.cache: dict[tuple[int, int, int, int], float] | None = (
            {} if kind == AgentKind.OPTIMIZED else None
        )
        self.deadline = (
            None if settings.time_limit_ms is None else perf_counter() + settings.time_limit_ms / 1000
        )
        self.nodes = self.cutoffs = self.cache_hits = 0

    def value(self, state: State, depth: int, alpha: float, beta: float) -> float:
        if self.nodes >= self.settings.node_limit:
            raise _BudgetReached("node limit")
        if self.deadline is not None and perf_counter() >= self.deadline:
            raise _BudgetReached("time limit")
        self.nodes += 1

        first, second = state.scores
        key = (state.drawn, first - second, state.to_move, depth)
        if self.cache is not None and key in self.cache:
            self.cache_hits += 1
            return self.cache[key]
        if depth == 0 or state.terminal:
            margin = first - second if self.perspective == 0 else second - first
            ready = sum((state.drawn & box).bit_count() == 3 for box in state.board.box_masks)
            tempo = 1 if state.to_move == self.perspective else -1
            value = margin + tempo * self.settings.threat_weight * ready
            if self.cache is not None:
                self.cache[key] = value
            return value

        alpha_start, beta_start = alpha, beta
        moves = state.legal_edges()
        if self.cache is not None:
            moves = tuple(
                candidate.edge
                for candidate in sorted(
                    (_candidate(state, edge) for edge in moves), key=_greedy_rank, reverse=True
                )
            )
        maximizing = state.to_move == self.perspective
        value = -math.inf if maximizing else math.inf
        for index, edge in enumerate(moves):
            child = self.value(state.play(edge), depth - 1, alpha, beta)
            if maximizing:
                value = max(value, child)
                if self.pruning:
                    alpha = max(alpha, value)
            else:
                value = min(value, child)
                if self.pruning:
                    beta = min(beta, value)
            if self.pruning and alpha >= beta and index + 1 < len(moves):
                self.cutoffs += 1
                break

        # A fail-low or fail-high value is a bound and cannot be reused as exact.
        if self.cache is not None and alpha_start < value < beta_start:
            self.cache[key] = value
        return value


class SearchAgent:
    def __init__(self, kind: AgentKind, settings: SearchSettings):
        if not kind.searches:
            raise ValueError("SearchAgent requires a Minimax variant")
        self.kind = kind
        self.settings = settings

    def choose_move(self, state: State) -> Decision:
        legal = _legal_edges(state)
        target = min(self.settings.depth, len(legal))
        search = _Search(self.kind, self.settings, state.to_move)
        completed = 0
        limit = None
        candidates: tuple[Candidate, ...] = ()
        for depth in range(1, target + 1):
            try:
                # A full window per root edge gives exact values at the chosen depth
                # for the inspector, even when an edge is worse than the best so far.
                values = tuple(
                    _candidate(state, edge, search.value(state.play(edge), depth - 1, -math.inf, math.inf))
                    for edge in legal
                )
            except _BudgetReached as exc:
                limit = str(exc)
                break
            candidates = tuple(sorted(values, key=lambda item: -float(item.evaluation)))
            completed = depth

        if completed:
            picked = candidates[0]
            reason = (
                f"Best evaluation {picked.evaluation:+.2f} at depth {completed} "
                f"across {len(legal)} legal edges."
            )
            if limit:
                reason += f" Reached the {limit} before finishing depth {completed + 1}."
        else:
            candidates = tuple(
                sorted((_candidate(state, edge) for edge in legal), key=_greedy_rank, reverse=True)
            )
            picked = candidates[0]
            reason = f"The {limit} stopped depth 1. Used the capture-first rule. " + _greedy_reason(picked)

        return Decision(
            picked.edge,
            reason,
            candidates,
            SearchStats(
                completed,
                target,
                search.nodes,
                search.cutoffs if search.pruning else None,
                search.cache_hits if search.cache is not None else None,
                limit,
            ),
        )


def create_agent(kind: AgentKind, settings: SearchSettings, seed: int) -> Agent:
    if kind == AgentKind.RANDOM:
        return RandomAgent(seed)
    if kind == AgentKind.GREEDY:
        return GreedyAgent(seed)
    return SearchAgent(kind, settings)
