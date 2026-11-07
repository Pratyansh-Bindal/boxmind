"""Compare search variants on identical, seeded positions at a fixed depth."""

from dataclasses import asdict
from pathlib import Path
import random
from statistics import mean

from .agents import AgentKind, SearchSettings, create_agent, time_decision
from .engine import State
from .reports import environment, report_directory, write_csv, write_json

VARIANTS = (AgentKind.MINIMAX, AgentKind.ALPHA_BETA, AgentKind.OPTIMIZED)
COLUMNS = (
    "position", "board", "starter", "prefix_edge_ids", "agent", "edge", "evaluation",
    "depth", "target_depth", "nodes", "cutoffs", "cache_hits", "decision_ms",
    "limit_reached", "comparable", "agreed_on_all_evaluations",
)


def benchmark(
    boards: tuple[tuple[int, int], ...],
    samples: int,
    seed: int,
    settings: SearchSettings,
    destination: Path,
) -> Path:
    if samples < 1:
        raise ValueError("Sample count must be positive")
    if not boards or len(set(boards)) != len(boards):
        raise ValueError("Select one or more distinct board sizes")
    rng = random.Random(seed)
    rows = []
    for height, width in boards:
        for sample in range(samples):
            starter = sample % 2
            state = State.new(height, width, starter)
            prefix = []
            # Include the opening and progressively later seeded positions.
            for _ in range(int(state.remaining * 0.9 * sample / samples)):
                edge = rng.choice(state.legal_edges())
                prefix.append(edge)
                state = state.play(edge)
            measurements = []
            signatures = []
            for kind in VARIANTS:
                choice = time_decision(create_agent(kind, settings, seed), state)
                decision = choice.decision
                stats = decision.search
                assert stats is not None
                signatures.append(tuple(sorted(
                    (candidate.edge, candidate.evaluation) for candidate in decision.candidates
                )))
                measurements.append({
                    "position": f"{state.board.size}/{sample + 1}",
                    "board": state.board.size,
                    "starter": starter + 1,
                    "prefix_edge_ids": " ".join(map(str, prefix)),
                    "agent": kind,
                    "edge": state.board.edges[decision.edge].label,
                    "evaluation": decision.candidates[0].evaluation,
                    "depth": stats.depth,
                    "target_depth": stats.target_depth,
                    "nodes": stats.nodes,
                    "cutoffs": stats.cutoffs,
                    "cache_hits": stats.cache_hits,
                    "decision_ms": choice.elapsed_ms,
                    "limit_reached": stats.limit_reached,
                })
            comparable = all(row["depth"] == row["target_depth"] for row in measurements)
            agreement = len(set(signatures)) == 1 if comparable else None
            rows.extend({
                **row, "comparable": comparable, "agreed_on_all_evaluations": agreement
            } for row in measurements)

    comparable = [row for row in rows if row["comparable"]]
    eligible = len(comparable) // len(VARIANTS)
    agreed = sum(row["agreed_on_all_evaluations"] for row in comparable) // len(VARIANTS)
    total = len(boards) * samples
    wall = "off" if settings.time_limit_ms is None else f"{settings.time_limit_ms:g} ms"
    lines = [
        "# Minimax optimization experiment", "",
        f"**{total} positions** · {samples} per board · Seed `{seed}`", "",
        f"Board sizes in dots are {', '.join(f'{height}×{width}' for height, width in boards)}. "
        "Each variant evaluated the same positions with the same depth, heuristic and budget. "
        "The first position on each board was empty. The others used increasingly long seeded "
        "legal move sequences. Ties between evaluations use the same edge order.",
        "", f"Depth {settings.depth}, node limit {settings.node_limit:,}, "
        f"wall clock cap {wall}, threat weight {settings.threat_weight:g}.",
        f"Measured on {environment()}. Each position was timed once per variant in the same process.",
        "", f"All three variants reached the target depth on **{eligible}/{total}** positions. "
        f"They agreed on every candidate evaluation on **{agreed}/{eligible}** of those positions.",
        "",
    ]
    if comparable:
        baseline = mean(row["nodes"] for row in comparable if row["agent"] == AgentKind.MINIMAX)
        lines += [
            "| Variant | Mean nodes | Node reduction vs Minimax | Mean decision (ms) |",
            "| :-- | --: | --: | --: |",
        ]
        for kind in VARIANTS:
            subset = [row for row in comparable if row["agent"] == kind]
            nodes = mean(row["nodes"] for row in subset)
            elapsed = mean(row["decision_ms"] for row in subset)
            lines.append(
                f"| {kind.label} | {nodes:,.1f} | {1 - nodes / baseline:.1%} | {elapsed:.3f} |"
            )
        lines += ["", "The table includes only positions where all variants reached their target depth."]
    lines += [
        "", "Node counts include each visit during iterative deepening, including leaves and cache hits. "
        "The comparison measures search work and decision time on these positions.",
        "", "[Per-position CSV](positions.csv) · [Experiment settings](config.json)",
    ]
    with report_directory(destination) as folder:
        write_csv(folder / "positions.csv", COLUMNS, rows)
        write_json(folder / "config.json", {
            "format_version": 1,
            "boards": boards,
            "samples": samples,
            "seed": seed,
            "search": asdict(settings),
            "environment": environment(),
        })
        (folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination.resolve()
