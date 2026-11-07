"""Board geometry and immutable Dots and Boxes positions."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

MIN_DOTS = 2
MAX_DOTS = 12
Axis = Literal["h", "v"]


class IllegalMove(ValueError):
    """The edge cannot be drawn in the current position."""


@dataclass(frozen=True, slots=True)
class Edge:
    axis: Axis
    row: int
    col: int

    @property
    def label(self) -> str:
        return f"{self.axis.upper()}{self.row + 1},{self.col + 1}"


@dataclass(frozen=True, slots=True)
class Board:
    rows: int
    cols: int
    edges: tuple[Edge, ...]
    box_masks: tuple[int, ...]
    adjacent_boxes: tuple[tuple[int, ...], ...]
    full_mask: int

    @property
    def size(self) -> str:
        return f"{self.rows}x{self.cols}"

    @property
    def box_count(self) -> int:
        return len(self.box_masks)

    def edge_id(self, axis: Axis, row: int, col: int) -> int:
        if axis == "h" and 0 <= row < self.rows and 0 <= col < self.cols - 1:
            return row * (self.cols - 1) + col
        if axis == "v" and 0 <= row < self.rows - 1 and 0 <= col < self.cols:
            return self.rows * (self.cols - 1) + row * self.cols + col
        raise IllegalMove(f"Invalid edge {axis!r} at ({row}, {col}) on {self.size} dots")


@lru_cache(maxsize=128)
def board_for(rows: int, cols: int) -> Board:
    if not all(type(n) is int and MIN_DOTS <= n <= MAX_DOTS for n in (rows, cols)):
        raise ValueError(f"Each board dimension must be {MIN_DOTS}–{MAX_DOTS} dots")

    horizontal = tuple(Edge("h", r, c) for r in range(rows) for c in range(cols - 1))
    vertical = tuple(Edge("v", r, c) for r in range(rows - 1) for c in range(cols))
    edges = horizontal + vertical
    masks = []
    neighbors: list[list[int]] = [[] for _ in edges]
    for row in range(rows - 1):
        for col in range(cols - 1):
            top = row * (cols - 1) + col
            left = len(horizontal) + row * cols + col
            sides = (top, top + cols - 1, left, left + 1)
            for edge in sides:
                neighbors[edge].append(len(masks))
            masks.append(sum(1 << edge for edge in sides))
    return Board(
        rows, cols, edges, tuple(masks), tuple(map(tuple, neighbors)), (1 << len(edges)) - 1
    )


@dataclass(frozen=True, slots=True)
class Tactics:
    captures: int
    new_threats: int


@dataclass(frozen=True, slots=True)
class State:
    board: Board
    drawn: int = 0
    first_edges: int = 0
    first_boxes: int = 0
    second_boxes: int = 0
    to_move: int = 0

    @classmethod
    def new(cls, rows: int = 4, cols: int = 4, starter: int = 0) -> "State":
        if starter not in (0, 1):
            raise ValueError("The starting player must be 0 or 1")
        return cls(board_for(rows, cols), to_move=starter)

    @property
    def scores(self) -> tuple[int, int]:
        return self.first_boxes.bit_count(), self.second_boxes.bit_count()

    @property
    def remaining(self) -> int:
        return len(self.board.edges) - self.drawn.bit_count()

    @property
    def terminal(self) -> bool:
        return self.drawn == self.board.full_mask

    @property
    def winner(self) -> int | None:
        first, second = self.scores
        if not self.terminal or first == second:
            return None
        return int(second > first)

    def legal_edges(self) -> tuple[int, ...]:
        return bit_indices(self.board.full_mask ^ self.drawn)

    def is_legal(self, edge: int) -> bool:
        return (
            type(edge) is int
            and 0 <= edge < len(self.board.edges)
            and not self.drawn & (1 << edge)
        )

    def edge_owner(self, edge: int) -> int | None:
        bit = 1 << edge
        if self.drawn & bit:
            return 0 if self.first_edges & bit else 1
        return None

    def box_owner(self, box: int) -> int | None:
        bit = 1 << box
        if self.first_boxes & bit:
            return 0
        if self.second_boxes & bit:
            return 1
        return None

    def tactics(self, edge: int) -> Tactics:
        """Count boxes closed and boxes made capturable by a legal edge."""
        self._check_edge(edge)
        captures = threats = 0
        for box in self.board.adjacent_boxes[edge]:
            sides = (self.drawn & self.board.box_masks[box]).bit_count()
            captures += sides == 3
            threats += sides == 2
        return Tactics(captures, threats)

    def play(self, edge: int) -> "State":
        self._check_edge(edge)
        bit = 1 << edge
        drawn = self.drawn | bit
        captures = 0
        for box in self.board.adjacent_boxes[edge]:
            mask = self.board.box_masks[box]
            if drawn & mask == mask:
                captures |= 1 << box
        first = self.to_move == 0
        return State(
            self.board,
            drawn,
            self.first_edges | bit if first else self.first_edges,
            self.first_boxes | captures if first else self.first_boxes,
            self.second_boxes if first else self.second_boxes | captures,
            self.to_move if captures else 1 - self.to_move,
        )

    def _check_edge(self, edge: int) -> None:
        if not self.is_legal(edge):
            raise IllegalMove(f"Edge {edge!r} is out of bounds or already drawn")


def bit_indices(mask: int) -> tuple[int, ...]:
    indices = []
    while mask:
        bit = mask & -mask
        indices.append(bit.bit_length() - 1)
        mask ^= bit
    return tuple(indices)
