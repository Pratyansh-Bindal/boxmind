from pathlib import Path

import pytest

from boxmind.agents import AgentKind
from boxmind.matches import MatchConfig
from boxmind.ui import App, FIELD, SIZE
from boxmind.ui_widgets import BoardView

import pygame as pg


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.chdir(tmp_path)
    pg.display.init()
    pg.font.init()
    pg.display.set_mode(SIZE)
    instance = App(MatchConfig(2, 3, (None, None)))
    yield instance
    instance.close()
    pg.quit()


def click(app, pos):
    app.draw(pos)
    app.click(pos)


def test_two_humans_can_finish_replay_and_export_a_match(app):
    view = BoardView.fit(app.game.state.board, FIELD)
    for edge in (0, 2, 4, 1, 5, 3, 6):
        a, b = view.segment(edge)
        click(app, ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2))
    assert app.game.state.terminal
    assert app.game.state.scores == (1, 1)

    click(app, (1080, 346))
    assert app.tab == "history"
    click(app, (970, 502))
    assert app.tab == "decision" and app.displayed_move == 5
    assert app.game.positions[app.displayed_move].scores == (1, 0)
    click(app, (368, 756))
    assert app.replay is None and app.displayed_move == 7

    click(app, (1027, 79))
    assert len(list(Path("reports").glob("match-*/match.json"))) == 1


def test_random_match_setup_and_ai_single_step(app):
    click(app, (1159, 79))
    click(app, (820, 253))
    click(app, (820, 663))
    assert app.randomized
    assert set(app.game.config.players) <= set(AgentKind)
    assert app.game.config.players[0] != app.game.config.players[1]

    click(app, (691, 755))
    app.update()
    assert app.paused and app.ai_job is None
    click(app, (613, 755))
    app.update()
    app.ai_job.result(timeout=3)
    app.update()
    assert app.paused and len(app.game.moves) == 1
    app.update()
    assert app.ai_job is None
