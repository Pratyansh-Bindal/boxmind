"""Command line entry points for local play, experiments, and reports."""

import argparse
from pathlib import Path

from .agents import AgentKind, SearchSettings
from .benchmark import benchmark
from .engine import board_for
from .matches import MatchConfig, play_match, random_players
from .reports import default_report_path, match_outcome, write_match_report, write_tournament_report
from .tournament import TournamentConfig, run_tournament


def _board_size(value: str) -> tuple[int, int]:
    try:
        rows, cols = map(int, value.lower().replace("×", "x").split("x"))
        board_for(rows, cols)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Enter rows x columns (e.g. 3x4), each from 2 to 12") from exc
    return rows, cols


def _search_options(parser: argparse.ArgumentParser, *, node_limit: int = 20_000) -> None:
    parser.add_argument("--seed", type=int, default=311)
    parser.add_argument("--depth", type=int, default=3, help="Maximum edges searched ahead (default 3)")
    parser.add_argument("--node-limit", type=int, default=node_limit, help="Search node cap per move")
    parser.add_argument("--time-limit-ms", type=float, help="Optional wall clock cap per search move")
    parser.add_argument("--threat-weight", type=float, default=0.35, help="Heuristic weight for open boxes")


def _match_options(parser: argparse.ArgumentParser, *, gui: bool) -> None:
    agents = list(AgentKind)
    parser.add_argument("--board", type=_board_size, default=(4, 4) if gui else (3, 3))
    parser.add_argument("--p1", choices=["human", *agents] if gui else agents,
                        default="human" if gui else AgentKind.OPTIMIZED)
    parser.add_argument("--p2", choices=["human", *agents] if gui else agents, default=AgentKind.GREEDY)
    parser.add_argument("--starter", type=int, choices=(1, 2), default=1)
    parser.add_argument("--random", action="store_true", help="Sample two distinct AI agents")
    _search_options(parser)


def _settings(args: argparse.Namespace) -> SearchSettings:
    return SearchSettings(args.depth, args.node_limit, args.time_limit_ms, args.threat_weight)


def _match_config(args: argparse.Namespace) -> MatchConfig:
    if args.random:
        players = random_players(args.seed)
    else:
        p1 = None if args.p1 == "human" else AgentKind(args.p1)
        p2 = None if args.p2 == "human" else AgentKind(args.p2)
        players = (p1, p2)
    return MatchConfig(*args.board, players, args.starter - 1, args.seed, _settings(args))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="boxmind", description="Dots and Boxes strategy lab")
    sub = parser.add_subparsers(dest="command")
    play = sub.add_parser("play", help="Open the Pygame strategy lab")
    _match_options(play, gui=True)
    play.set_defaults(p2=AgentKind.OPTIMIZED, time_limit_ms=220.0)
    match = sub.add_parser("match", help="Play and export one headless AI match")
    _match_options(match, gui=False)
    match.add_argument("--out", type=Path)

    tournament = sub.add_parser("tournament", help="Run and export a seeded AI tournament")
    tournament.add_argument("--agents", nargs="+", choices=list(AgentKind), default=list(AgentKind))
    tournament.add_argument("--boards", nargs="+", type=_board_size, default=[(3, 3)])
    tournament.add_argument("--games", type=int, default=8, help="Even game count per pairing and board")
    tournament.add_argument("--random-pairs", action="store_true", help="Sample pairings, with --games per board")
    tournament.add_argument("--out", type=Path)
    _search_options(tournament)

    compare = sub.add_parser("benchmark", help="Compare Minimax variants on identical positions")
    compare.add_argument("--boards", nargs="+", type=_board_size, default=[(3, 3), (4, 4)])
    compare.add_argument("--samples", type=int, default=6, help="Positions per board")
    compare.add_argument("--out", type=Path)
    _search_options(compare, node_limit=100_000)

    chart = sub.add_parser("plot", help="Plot a tournament summary as a PNG")
    chart.add_argument("report", type=Path, help="Tournament report folder or summary.csv")
    chart.add_argument("--out", type=Path)

    args = parser.parse_args(argv)
    if args.command is None:
        args = parser.parse_args(["play"])
    try:
        if args.command == "play":
            from .ui import run_app
            run_app(_match_config(args), randomized=args.random)
        elif args.command == "plot":
            from .charts import plot_summary
            source = args.report / "summary.csv" if args.report.is_dir() else args.report
            path = plot_summary(source, args.out or source.with_name("overview.png"))
            print(path)
        else:
            destination = args.out or default_report_path(args.command)
            if destination.exists():
                raise FileExistsError(f"Report folder already exists: {destination}")
            if args.command == "match":
                result = play_match(_match_config(args))
                path = write_match_report(result, destination)
                first, second = result.state.scores
                print(f"{match_outcome(result)} · {first}–{second}")
            elif args.command == "tournament":
                config = TournamentConfig(
                    tuple(map(AgentKind, args.agents)), tuple(args.boards), args.games,
                    args.seed, _settings(args), args.random_pairs,
                )
                print(f"Running {config.total_games} games…", flush=True)
                path = write_tournament_report(run_tournament(config), destination)
            else:
                path = benchmark(tuple(args.boards), args.samples, args.seed, _settings(args), destination)
            print(f"Report saved to {path}")
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    except KeyboardInterrupt:
        return 130
    return 0
