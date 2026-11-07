import random

import pytest

from boxmind.engine import IllegalMove, State


def play(state, edges):
    for edge in edges:
        state = state.play(edge)
    return state


def test_rectangular_board_geometry_and_illegal_moves():
    start = State.new(2, 4, starter=1)
    assert len(start.legal_edges()) == 2 * 3 + 1 * 4
    assert start.board.box_count == 3
    assert start.board.edge_id("v", 0, 3) == 9
    assert start.board.adjacent_boxes[start.board.edge_id("v", 0, 2)] == (1, 2)
    with pytest.raises(IllegalMove):
        start.board.edge_id("h", 0, 3)
    with pytest.raises(IllegalMove):
        start.board.edge_id("v", 1, 0)
    for edge in (-1, 10, True):
        with pytest.raises(IllegalMove):
            start.play(edge)
    next_state = start.play(0)
    assert start.edge_owner(0) is None
    assert next_state.edge_owner(0) == 1
    assert next_state.to_move == 0
    with pytest.raises(IllegalMove):
        next_state.play(0)


def test_closing_a_box_keeps_the_turn_and_two_boxes_can_draw():
    start = State.new(2, 3)
    before = play(start, (0, 2, 4, 1))
    assert before.to_move == 0
    assert before.tactics(5).captures == 1
    after = before.play(5)
    assert after.scores == (1, 0)
    assert after.to_move == 0
    assert after.box_owner(0) == 0 and after.box_owner(1) is None
    end = play(after, (3, 6))
    assert end.scores == (1, 1)
    assert end.winner is None and end.terminal
    assert end.legal_edges() == ()


def test_shared_edge_claims_both_boxes():
    state = play(State.new(2, 3, starter=1), (0, 1, 2, 3, 4, 6))
    assert state.legal_edges() == (5,)
    assert state.tactics(5).captures == 2
    end = state.play(5)
    assert end.scores == (0, 2)
    assert end.box_owner(0) == end.box_owner(1) == end.winner == 1
    assert end.terminal and end.remaining == 0
    with pytest.raises(IllegalMove):
        end.play(5)


@pytest.mark.parametrize("rows,cols", [(2, 2), (3, 5), (5, 3), (12, 12)])
def test_every_closed_box_is_claimed_during_a_game(rows, cols):
    state = State.new(rows, cols)
    rng = random.Random(32)
    while not state.terminal:
        state = state.play(rng.choice(state.legal_edges()))
        for index, mask in enumerate(state.board.box_masks):
            assert (state.box_owner(index) is not None) == (state.drawn & mask == mask)
    assert sum(state.scores) == (rows - 1) * (cols - 1)
