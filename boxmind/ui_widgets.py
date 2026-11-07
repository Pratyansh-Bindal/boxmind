"""Drawing and hit targets for the Pygame interface."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pygame as pg

from .engine import Board, State

SIZE = (1260, 840)
BG = "#0e1522"
SIDEBAR = "#101a29"
CARD = "#172233"
WELL = "#111b2b"
RAISED = "#202f44"
LINE = "#2a3b51"
TEXT = "#f0f4fb"
MUTED = "#a2b2c9"
DIM = "#8093ae"
MINT = "#62e4bf"
VIOLET = "#bdadff"
INK = "#0d2425"
PLAYER_COLORS = (MINT, VIOLET)
PLAYER_FILLS = ("#20423f", "#3a3459")

Action = Callable[[], None]


@dataclass(frozen=True, slots=True)
class Hit:
    rect: pg.Rect
    action: Action


class Painter:
    def __init__(self, surface: pg.Surface):
        self.surface = surface
        self.pointer = (-1, -1)
        self.hits: list[Hit] = []
        self.fonts: dict[tuple[int, bool], pg.font.Font] = {}

    def font(self, size: int, bold: bool = False) -> pg.font.Font:
        key = (size, bold)
        if key not in self.fonts:
            family = Path("/System/Library/Fonts") / ("Avenir Next.ttc" if bold else "Avenir.ttc")
            self.fonts[key] = (
                pg.font.Font(family, size) if family.is_file()
                else pg.font.SysFont(("segoeui", "dejavusans", "arial"), size, bold=bold)
            )
        return self.fonts[key]

    def text(
        self, value: str, x: int, y: int, size: int = 16, color: str = TEXT, *,
        bold: bool = False, align: str = "left", max_width: int | None = None,
    ) -> pg.Rect:
        font = self.font(size, bold)
        if max_width is not None and font.size(value)[0] > max_width:
            while value and font.size(value + "…")[0] > max_width:
                value = value[:-1]
            value += "…"
        rendered = font.render(value, True, color)
        rect = rendered.get_rect()
        rect.y = y
        if align == "right":
            rect.right = x
        elif align == "center":
            rect.centerx = x
        else:
            rect.x = x
        self.surface.blit(rendered, rect)
        return rect

    def label(self, value: str, x: int, y: int, color: str = DIM) -> None:
        self.text(value.upper(), x, y, 11, color, bold=True)

    def wrapped(
        self, value: str, x: int, y: int, width: int, *, size: int = 14,
        color: str = MUTED, line_height: int = 20,
    ) -> int:
        font = self.font(size)
        line = ""
        for word in value.split():
            candidate = f"{line} {word}".strip()
            if line and font.size(candidate)[0] > width:
                self.text(line, x, y, size, color)
                y += line_height
                line = word
            else:
                line = candidate
        if line:
            self.text(line, x, y, size, color, max_width=width)
            y += line_height
        return y

    def panel(
        self, rect: pg.Rect, fill: str = CARD, border: str | None = LINE, radius: int = 14
    ) -> None:
        pg.draw.rect(self.surface, fill, rect, border_radius=radius)
        if border:
            pg.draw.rect(self.surface, border, rect, width=1, border_radius=radius)

    def divider(self, x1: int, x2: int, y: int) -> None:
        pg.draw.line(self.surface, LINE, (x1, y), (x2, y))

    def button(
        self, rect: pg.Rect, value: str, action: Action, *, style: str = "normal",
        enabled: bool = True, size: int = 14,
    ) -> None:
        hovered = enabled and rect.collidepoint(self.pointer)
        fill, border, color = {
            "primary": ("#8df0d4" if hovered else MINT, None, INK),
            "selected": ("#284c48" if hovered else "#213e3e", "#3d6c64", MINT),
            "normal": (RAISED if hovered else WELL, LINE, TEXT),
            "ghost": (RAISED if hovered else CARD, None, MUTED),
        }[style]
        if not enabled:
            fill, border, color = WELL, LINE, DIM
        self.panel(rect, fill, border, radius=8)
        font_height = self.font(size, True).get_height()
        self.text(value, rect.centerx, rect.centery - font_height // 2, size, color,
                  bold=True, align="center", max_width=rect.width - 10)
        if enabled:
            self.hits.append(Hit(rect, action))

    def pill(self, value: str, right: int, y: int, fill: str = WELL, color: str = MUTED) -> None:
        width = self.font(11, True).size(value)[0] + 18
        rect = pg.Rect(right - width, y, width, 23)
        self.panel(rect, fill, None, radius=6)
        self.text(value, rect.centerx, y + 4, 11, color, bold=True, align="center")

    def stepper(
        self, rect: pg.Rect, value: str, left: Action, right: Action, *,
        back: bool = True, forward: bool = True,
    ) -> None:
        self.panel(rect, WELL, LINE, radius=8)
        self.button(pg.Rect(rect.x, rect.y, 34, rect.h), "‹", left, enabled=back, size=18)
        self.button(pg.Rect(rect.right - 34, rect.y, 34, rect.h), "›", right, enabled=forward, size=18)
        self.text(value, rect.centerx, rect.centery - 10, 15, bold=True, align="center",
                  max_width=rect.w - 78)

    def symbol(self, name: str, x: int, y: int, color: str) -> None:
        if name == "play":
            pg.draw.polygon(self.surface, color, [(x - 5, y - 8), (x + 8, y), (x - 5, y + 8)], 2)
        elif name == "lab":
            for i, height in enumerate((7, 12, 17)):
                pg.draw.rect(self.surface, color, (x - 8 + i * 6, y + 8 - height, 4, height),
                             border_radius=1)
        elif name == "guide":
            pg.draw.circle(self.surface, color, (x, y), 9, 2)
            pg.draw.circle(self.surface, color, (x, y - 4), 1)
            pg.draw.line(self.surface, color, (x, y - 1), (x, y + 5), 2)
        else:
            points = [(x - 7, y - 7), (x + 7, y - 7), (x + 7, y + 7), (x - 7, y + 7)]
            pg.draw.lines(self.surface, color, False, points, 2)
            for point in points:
                pg.draw.circle(self.surface, color, point, 2)


@dataclass(frozen=True, slots=True)
class BoardView:
    board: Board
    step: float
    x: float
    y: float

    @classmethod
    def fit(cls, board: Board, rect: pg.Rect) -> "BoardView":
        step = min(111, (rect.w - 82) / (board.cols - 1), (rect.h - 63) / (board.rows - 1))
        return cls(
            board, step,
            rect.centerx + 7 - step * (board.cols - 1) / 2,
            rect.centery + 5 - step * (board.rows - 1) / 2,
        )

    def point(self, row: int, col: int) -> tuple[int, int]:
        return round(self.x + col * self.step), round(self.y + row * self.step)

    def segment(self, index: int) -> tuple[tuple[int, int], tuple[int, int]]:
        edge = self.board.edges[index]
        return (
            self.point(edge.row, edge.col),
            self.point(edge.row + (edge.axis == "v"), edge.col + (edge.axis == "h")),
        )

    def edge_at(self, state: State, pos: tuple[int, int]) -> int | None:
        px, py = pos
        tolerance = min(14, self.step * 0.24)
        for index in state.legal_edges():
            (x1, y1), (x2, y2) = self.segment(index)
            if y1 == y2 and x1 + 6 <= px <= x2 - 6 and abs(py - y1) <= tolerance:
                return index
            if x1 == x2 and y1 + 6 <= py <= y2 - 6 and abs(px - x1) <= tolerance:
                return index
        return None

    def draw(
        self, painter: Painter, state: State, *, last_edge: int | None = None,
        hover_edge: int | None = None,
    ) -> None:
        surface = painter.surface
        for row in range(self.board.rows - 1):
            for col in range(self.board.cols - 1):
                owner = state.box_owner(row * (self.board.cols - 1) + col)
                if owner is None:
                    continue
                x, y = self.point(row, col)
                x2, y2 = self.point(row + 1, col + 1)
                box = pg.Rect(x + 5, y + 5, x2 - x - 10, y2 - y - 10)
                painter.panel(box, PLAYER_FILLS[owner], None, radius=min(9, box.w // 3))
                size = min(23, max(10, int(self.step / 3)))
                painter.text("AB"[owner], box.centerx, box.centery - size // 2 - 2, size,
                             PLAYER_COLORS[owner], bold=True, align="center")

        for index, edge in enumerate(self.board.edges):
            start, end = self.segment(index)
            owner = state.edge_owner(index)
            if owner is not None or index == hover_edge:
                color = PLAYER_COLORS[state.to_move if owner is None else owner]
                width = 7 if index in (last_edge, hover_edge) else 5
                pg.draw.line(surface, color, start, end, width)
                if index == last_edge:
                    middle = ((start[0] + end[0]) // 2, (start[1] + end[1]) // 2)
                    pg.draw.circle(surface, TEXT, middle, 3)
            else:
                length = end[0] - start[0] if edge.axis == "h" else end[1] - start[1]
                for distance in range(7, length - 6, 10):
                    finish = min(distance + 4, length - 6)
                    if edge.axis == "h":
                        a, b = (start[0] + distance, start[1]), (start[0] + finish, start[1])
                    else:
                        a, b = (start[0], start[1] + distance), (start[0], start[1] + finish)
                    pg.draw.line(surface, "#3c516b", a, b, 2)

        for row in range(self.board.rows):
            for col in range(self.board.cols):
                point = self.point(row, col)
                pg.draw.circle(surface, "#293c55", point, 7 if self.step > 38 else 5)
                pg.draw.circle(surface, "#d2def0", point, 4 if self.step > 38 else 3)
            x, y = self.point(row, 0)
            painter.text(str(row + 1), x - 22, y - 7, 11, DIM, align="center")
        for col in range(self.board.cols):
            x, y = self.point(0, col)
            painter.text(chr(65 + col), x, y - 25, 11, DIM, align="center")
