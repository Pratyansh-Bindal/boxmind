import random

import pytest

from boxmind.agents import AgentKind, SearchSettings, create_agent
from boxmind.engine import State
from boxmind.matches import MatchConfig, play_match


SEARCH = (AgentKind.MINIMAX, AgentKind.ALPHA_BETA, AgentKind.OPTIMIZED)


def solve(state, perspective):
    if state.terminal:
        return state.scores[perspective] - state.scores[1 - perspective]
    outcomes = [solve(state.play(edge), perspective) for edge in state.legal_edges()]
    return max(outcomes) if state.to_move == perspective else min(outcomes)


def test_greedy_prioritizes_captures_and_avoids_exposing_boxes():
    agent = create_agent(AgentKind.GREEDY, SearchSettings(), seed=12)
    state = State.new(2, 3).play(0).play(2)
    assert state.tactics(4).new_threats == state.tactics(5).new_threats == 1
    assert state.tactics(agent.choose_move(state).edge).new_threats == 0
    state = state.play(4)
    assert agent.choose_move(state).edge == 5


@pytest.mark.parametrize("kind", list(AgentKind))
def test_agents_play_complete_legal_games(kind):
    match = play_match(MatchConfig(3, 4, (kind, AgentKind.GREEDY)))
    assert len(match.moves) == len(match.state.board.edges)
    assert len({move.edge for move in match.moves}) == len(match.moves)
    assert sum(match.state.scores) == 6
    assert all(move.ai.elapsed_ms >= 0 for move in match.moves)


@pytest.mark.parametrize("kind", SEARCH)
def test_search_matches_full_game_solver_on_extra_turn_positions(kind):
    rng = random.Random(32)
    checked_captures = 0
    for _ in range(14):
        state = State.new(3, 3)
        for _ in range(7):
            state = state.play(rng.choice(state.legal_edges()))
        root = state.to_move
        moves = state.legal_edges()
        checked_captures += any(state.tactics(edge).captures for edge in moves)
        expected = {edge: solve(state.play(edge), root) for edge in moves}
        decision = create_agent(kind, SearchSettings(depth=len(moves)), seed=12).choose_move(state)
        assert decision.search.depth == len(moves)
        assert {row.edge: row.evaluation for row in decision.candidates} == expected
        assert decision.edge == max(expected, key=expected.get)
    assert checked_captures > 0


def test_pruning_and_cache_reduce_nodes_at_the_same_depth():
    state = State.new(4, 4).play(0)
    choices = [create_agent(kind, SearchSettings(), seed=12).choose_move(state) for kind in SEARCH]
    baseline, pruned, optimized = choices
    assert all(choice.candidates == baseline.candidates for choice in choices)
    assert pruned.search.cutoffs > 0
    assert optimized.search.cache_hits > 0
    assert optimized.search.nodes < pruned.search.nodes < baseline.search.nodes


@pytest.mark.parametrize("node_limit,expected_depth", [(7, 0), (26, 1)])
def test_budget_uses_only_fully_evaluated_depths(node_limit, expected_depth):
    state = State.new()
    agent = create_agent(AgentKind.MINIMAX, SearchSettings(depth=5, node_limit=node_limit), seed=12)
    decision = agent.choose_move(state)
    assert state.is_legal(decision.edge)
    assert decision.search.nodes == node_limit
    assert decision.search.limit_reached == "node limit"
    assert decision.search.depth == expected_depth
    assert all((row.evaluation is not None) == bool(expected_depth) for row in decision.candidates)
