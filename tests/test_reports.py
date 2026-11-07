from collections import Counter
import csv
import json

import pytest

from boxmind.agents import AgentKind
from boxmind.matches import Match, MatchConfig, play_match
from boxmind.reports import write_match_report, write_tournament_report
from boxmind.tournament import TournamentCancelled, TournamentConfig, run_tournament, summarize


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def test_move_log_replays_final_scores_and_captures(tmp_path):
    game = play_match(MatchConfig(3, 3, (AgentKind.OPTIMIZED, AgentKind.GREEDY)))
    folder = write_match_report(game, tmp_path / "match")
    data = json.loads((folder / "match.json").read_text())
    assert data["config"]["seed"] == 311
    assert data["complete"]
    assert data["scores"] == list(game.state.scores)
    replay = Match(game.config).state
    for row in data["moves"]:
        assert [row["before_p1"], row["before_p2"]] == list(replay.scores)
        assert row["player"] == replay.to_move + 1
        assert row["decision_ms"] >= 0 and row["explanation"]
        assert row["edge_id"] in {candidate["edge"] for candidate in row["candidates"]}
        assert replay.tactics(row["edge_id"]).captures == row["captures"]
        replay = replay.play(row["edge_id"])
        assert row["next_player"] == (None if replay.terminal else replay.to_move + 1)
        assert [row["after_p1"], row["after_p2"]] == list(replay.scores)
    assert replay == game.state
    assert len(read_csv(folder / "moves.csv")) == len(game.moves)
    with pytest.raises(FileExistsError):
        write_match_report(game, folder)


def test_human_and_ai_turns_are_separate_and_stale_moves_are_rejected():
    game = Match(MatchConfig(2, 3, (None, AgentKind.RANDOM)))
    human = game.play_human(0)
    assert human.ai is None
    with pytest.raises(ValueError):
        game.play_human(1)
    planned = game.plan_ai_move()
    game.apply_ai_move(planned)
    with pytest.raises(ValueError):
        game.apply_ai_move(planned)
    assert len(game.moves) == 2


def test_tournament_alternates_starts_and_replays_deterministically(tmp_path):
    agents = (AgentKind.RANDOM, AgentKind.GREEDY, AgentKind.MINIMAX)
    config = TournamentConfig(agents, ((2, 3), (3, 3)), games=4, seed=2026)
    tournament = run_tournament(config)
    repeated = run_tournament(config)
    for first, second in zip(tournament.matches, repeated.matches, strict=True):
        assert first.config == second.config
        assert [move.edge for move in first.moves] == [move.edge for move in second.moves]
        assert first.state == second.state
    assert len(tournament.matches) == config.total_games == 24

    rows = summarize(tournament, by_matchup=True)
    for row in rows:
        assert row.games == 2
        assert row.wins + row.draws + row.losses == row.games
        assert row.win_rate + row.draw_rate + row.loss_rate == pytest.approx(1)
        assert row.p95_ms >= row.p50_ms >= 0
    folder = write_tournament_report(tournament, tmp_path / "tournament")
    games = read_csv(folder / "games.csv")
    starts = Counter((row["p1"], row["p2"], row["board"], row["starter"]) for row in games)
    assert set(starts.values()) == {2}
    assert len(games) == config.total_games
    assert len(read_csv(folder / "moves.csv")) == sum(len(game.moves) for game in tournament.matches)


def test_random_pair_schedule_and_cancellation():
    config = TournamentConfig(games=10, random_pairs=True)
    schedule = list(config.schedule())
    assert schedule == list(config.schedule())
    for first, second in zip(schedule[::2], schedule[1::2], strict=True):
        assert first.players == second.players
        assert first.players[0] != first.players[1]
        assert first.seed == second.seed
        assert (first.starter, second.starter) == (0, 1)
    with pytest.raises(TournamentCancelled):
        run_tournament(config, cancelled=lambda: True)
