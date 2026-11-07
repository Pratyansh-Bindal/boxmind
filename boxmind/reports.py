"""Portable reports for matches and tournaments."""

from contextlib import contextmanager
import csv
from dataclasses import asdict, fields
from datetime import datetime
import json
from pathlib import Path
import platform
from statistics import mean
from tempfile import TemporaryDirectory
from typing import Iterable
from uuid import uuid4

from .matches import Match, MoveRecord
from .tournament import Stats, TournamentResult, summarize

MOVE_COLUMNS = (
    "move", "player", "name", "agent", "edge", "edge_id", "axis", "row", "col",
    "before_p1", "before_p2", "after_p1", "after_p2", "captures", "captured_boxes",
    "extra_turn", "next_player", "decision_ms", "depth", "target_depth", "nodes",
    "cutoffs", "cache_hits", "limit_reached", "evaluation", "explanation",
)


def default_report_path(kind: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("reports") / f"{kind}-{stamp}-{uuid4().hex[:6]}"


@contextmanager
def report_directory(destination: Path):
    """Publish a finished report folder and protect existing reports."""
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"Report folder already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".boxmind-", dir=destination.parent) as staging:
        folder = Path(staging) / "report"
        folder.mkdir()
        yield folder
        if destination.exists():
            raise FileExistsError(f"Report folder already exists: {destination}")
        folder.rename(destination)


def write_csv(path: Path, columns: Iterable[str], rows: Iterable[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=tuple(columns))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def environment() -> str:
    return f"{platform.system()} {platform.release()} {platform.machine()}, Python {platform.python_version()}"


def _move_row(game: Match, move: MoveRecord) -> dict:
    board = game.state.board
    edge = board.edges[move.edge]
    agent = game.config.players[move.player]
    decision = move.ai.decision if move.ai else None
    search = decision.search if decision else None
    selected = next(
        (candidate for candidate in decision.candidates if candidate.edge == move.edge), None
    ) if decision else None
    return {
        "move": move.number,
        "player": move.player + 1,
        "name": game.config.player_name(move.player),
        "agent": agent or "human",
        "edge": edge.label,
        "edge_id": move.edge,
        "axis": edge.axis,
        "row": edge.row + 1,
        "col": edge.col + 1,
        "before_p1": move.score_before[0],
        "before_p2": move.score_before[1],
        "after_p1": move.score_after[0],
        "after_p2": move.score_after[1],
        "captures": len(move.captured),
        "captured_boxes": " | ".join(
            f"{box // (board.cols - 1) + 1},{box % (board.cols - 1) + 1}"
            for box in move.captured
        ),
        "extra_turn": move.extra_turn,
        "next_player": None if move.next_player is None else move.next_player + 1,
        "decision_ms": move.ai.elapsed_ms if move.ai else None,
        "depth": search.depth if search else None,
        "target_depth": search.target_depth if search else None,
        "nodes": search.nodes if search else None,
        "cutoffs": search.cutoffs if search else None,
        "cache_hits": search.cache_hits if search else None,
        "limit_reached": search.limit_reached if search else None,
        "evaluation": selected.evaluation if selected else None,
        "explanation": decision.explanation if decision else "",
    }


def match_outcome(game: Match) -> str:
    if not game.state.terminal:
        return "In progress"
    winner = game.state.winner
    return "Draw" if winner is None else f"{game.config.player_name(winner)} (P{winner + 1}) wins"


def _search_description(settings) -> str:
    wall = "off" if settings.time_limit_ms is None else f"{settings.time_limit_ms:g} ms"
    return (
        f"Depth {settings.depth}, {settings.node_limit:,} nodes per move, "
        f"wall clock cap {wall}, threat weight {settings.threat_weight:g}."
    )


def write_match_report(game: Match, destination: Path) -> Path:
    rows = [_move_row(game, move) for move in game.moves]
    full_moves = []
    for row, move in zip(rows, game.moves, strict=True):
        candidates = [
            {**asdict(candidate), "label": game.state.board.edges[candidate.edge].label}
            for candidate in move.ai.decision.candidates
        ] if move.ai else []
        full_moves.append({**row, "candidates": candidates})

    score = game.state.scores
    lines = [
        "# BoxMind match report", "",
        f"**{match_outcome(game)}** · Score **{score[0]}–{score[1]}** · "
        f"Margin **{abs(score[0] - score[1])}**", "",
        f"{game.state.board.size} dots. P1 is {game.config.player_name(0)} and "
        f"P2 is {game.config.player_name(1)}. P{game.config.starter + 1} started.",
        f"Match seed `{game.config.seed}`. {_search_description(game.config.search)}",
        f"Measured on {environment()}.", "",
        "| Player | Moves | Mean AI decision (ms) | Mean search nodes |",
        "| :-- | --: | --: | --: |",
    ]
    for player in (0, 1):
        player_rows = [row for row in rows if row["player"] == player + 1]
        times = [row["decision_ms"] for row in player_rows if row["decision_ms"] is not None]
        nodes = [row["nodes"] for row in player_rows if row["nodes"] is not None]
        time_text = f"{mean(times):.3f}" if times else "—"
        node_text = f"{mean(nodes):.1f}" if nodes else "—"
        lines.append(
            f"| P{player + 1} · {game.config.player_name(player)} | {len(player_rows)} | "
            f"{time_text} | {node_text} |"
        )
    captures = [row for row in rows if row["captures"]]
    if captures:
        lines += ["", "## Capture highlights", ""]
        for row in sorted(captures, key=lambda item: -item["captures"])[:4]:
            lines.append(
                f"- Move {row['move']}, P{row['player']} drew `{row['edge']}` and claimed "
                f"{row['captures']} box{'es' if row['captures'] != 1 else ''}. "
                f"The score became {row['after_p1']}–{row['after_p2']}."
            )
    lines += [
        "", "[Full move log](moves.csv) · [Configuration and candidate evaluations](match.json)",
        "", "An evaluation measures estimated box margin from the moving player's perspective.",
    ]
    with report_directory(destination) as folder:
        write_csv(folder / "moves.csv", MOVE_COLUMNS, rows)
        write_json(folder / "match.json", {
            "format_version": 1,
            "environment": environment(),
            "config": asdict(game.config),
            "player_seeds": game.agent_seeds,
            "complete": game.state.terminal,
            "scores": score,
            "winner": None if game.state.winner is None else game.state.winner + 1,
            "moves": full_moves,
        })
        (folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination.resolve()


GAME_COLUMNS = (
    "game", "board", "p1", "p2", "starter", "starting_agent", "seed",
    "p1_seed", "p2_seed", "p1_score", "p2_score", "winner", "p1_margin",
)


def _game_row(index: int, game: Match) -> dict:
    p1, p2 = game.state.scores
    winner = game.state.winner
    return {
        "game": index,
        "board": game.state.board.size,
        "p1": game.config.players[0],
        "p2": game.config.players[1],
        "starter": game.config.starter + 1,
        "starting_agent": game.config.players[game.config.starter],
        "seed": game.config.seed,
        "p1_seed": game.agent_seeds[0],
        "p2_seed": game.agent_seeds[1],
        "p1_score": p1,
        "p2_score": p2,
        "winner": "draw" if winner is None else game.config.players[winner],
        "p1_margin": p1 - p2,
    }


def write_tournament_report(result: TournamentResult, destination: Path) -> Path:
    overall = summarize(result)
    split = summarize(result, by_matchup=True)
    setups = result.config
    boards = ", ".join(f"{rows}×{cols}" for rows, cols in setups.boards)
    agents = ", ".join(agent.label for agent in setups.agents)
    schedule = (
        f"{setups.games} games per board with sampled pairings"
        if setups.random_pairs else f"{setups.games} games per pairing on each board"
    )
    lines = [
        "# BoxMind tournament report", "",
        f"**{len(result.matches)} games** · {boards} dots · Seed `{setups.seed}`", "",
        f"{agents} played {schedule}. Each two-game block used the same seed and "
        "gave each agent one start.",
        _search_description(setups.search),
        f"Measured on {environment()}.", "",
        "| Agent | Games | W / L / D | Win % | Mean margin | Mean ms | P95 ms | Mean nodes |",
        "| :-- | --: | --: | --: | --: | --: | --: | --: |",
    ]
    for row in overall:
        nodes = f"{row.mean_nodes:,.1f}" if row.mean_nodes is not None else "—"
        lines.append(
            f"| {row.agent.label} | {row.games} | {row.wins} / {row.losses} / {row.draws} | "
            f"{row.win_rate:.1%} | {row.mean_margin:+.2f} | {row.mean_ms:.3f} | "
            f"{row.p95_ms:.3f} | {nodes} |"
        )
    lines += [
        "", "Rates use all games as the denominator. Latency percentiles use pooled "
        "decisions per agent. P95 uses the nearest rank. Node counts include leaves "
        "and cache lookups, plus work in any unfinished search depth.", "",
        "- [Summary CSV](summary.csv)",
        "- [Breakdown by opponent, board and starter](by_matchup.csv)",
        "- [Games and seeds](games.csv)",
        "- [Decision log](moves.csv)",
        "- [Tournament configuration](config.json)",
    ]
    with report_directory(destination) as folder:
        columns = [field.name for field in fields(Stats)]
        write_csv(folder / "summary.csv", columns, (asdict(row) for row in overall))
        write_csv(folder / "by_matchup.csv", columns, (asdict(row) for row in split))
        write_csv(folder / "games.csv", GAME_COLUMNS, (
            _game_row(index, game) for index, game in enumerate(result.matches, 1)
        ))
        write_csv(folder / "moves.csv", ("game", "board", *MOVE_COLUMNS), (
            {"game": index, "board": game.state.board.size, **_move_row(game, move)}
            for index, game in enumerate(result.matches, 1)
            for move in game.moves
        ))
        write_json(folder / "config.json", {
            "format_version": 1,
            "environment": environment(),
            **asdict(setups),
        })
        (folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination.resolve()
