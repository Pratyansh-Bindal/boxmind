# BoxMind

BoxMind is a local Dots and Boxes game and a lab for comparing classical AI agents. Play on the same device, face an agent, watch two agents, or run a seeded tournament without opening a window.

## Run locally

Use Python 3.11 or newer. From this directory, create a virtual environment and install the app. The optional `dev` and `analysis` extras add tests and tournament charts.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,analysis]'
python -m boxmind
```

If the environment is already set up, launch with `.venv/bin/python -m boxmind`. On Windows, use `.venv\Scripts\activate` to activate the environment. BoxMind uses Pygame Community Edition for the desktop interface.

The Playground starts with a human facing Optimized on a 4×4 dot grid. Click a dashed edge to draw it. Closing the fourth side claims a box and keeps the turn. A shared edge can close two boxes. When all boxes are claimed, the larger score wins.

- **New match** sets the mode, board, agents, starting seat, seed, and depth. Random mode draws two distinct agents from the pool using the seed.
- **Pause AI** stops automatic play. **Step** makes a single AI move while paused.
- **History** lists moves and scores. Select a row to replay that position, or use Left and Right to step through the board. **Live** returns to the current game.
- **Decision** shows the selected move, score change, explanation, and AI metrics. Scroll over the inspector to see more candidates.
- **Export** saves the match, including its configuration, move log, and candidate data. **Restart** plays the same setup from the beginning.

The board size always counts dots. A 4×4 dot grid has nine boxes. Edge labels use a direction and one-based row and column, so `H1,2` joins the second and third dots on the top row.

## Run headless

```sh
# One AI game
python -m boxmind match --board 4x4 --p1 optimized --p2 greedy --seed 311

# One sampled pairing
python -m boxmind match --random --board 3x4 --seed 73

# Round robin on two board sizes
python -m boxmind tournament --agents random greedy minimax alpha-beta optimized \
  --boards 3x3 4x4 --games 8 --depth 3 --seed 311 --out reports/round-robin

# A series of sampled pairings
python -m boxmind tournament --random-pairs --boards 3x3 --games 12 --seed 73

# Outcome and latency charts
python -m boxmind plot reports/round-robin

# More options
python -m boxmind tournament --help
```

The tournament screen offers the same round robin and random pair schedules. It runs games in the background and saves the reports when the run completes.

Round robin schedules `--games` games for every pairing on every board. Random pair scheduling uses that count for the entire board, sampling two agents for each two-game block. The count must be even. Both games in a block use the same seed, and each agent starts one game.

For reproducible moves, keep the seed, board, depth, agent choices and node budget fixed. The headless default is a node budget with the wall clock cap off. Setting `--time-limit-ms` lets runtime affect the depth reached. Tournament timing measures AI decision time and includes all work spent on a partially searched depth.

## Reports

The app and CLI save reports under `reports/` by default. Use a new output folder for each named run.

| Report | Files |
| --- | --- |
| Match | `report.md` gives the score and capture highlights. `moves.csv` includes score transitions, captures, turns, latency, and search metrics. `match.json` also includes candidate details and replayable edge IDs. |
| Tournament | `summary.csv` gives wins, losses, draws, score margin and latency. `by_matchup.csv` splits the metrics by opponent, board and starting seat. `games.csv`, `moves.csv` and `config.json` contain the raw results and seeds. |
| Benchmark | `positions.csv` gives each agent's results on the same positions. `report.md` compares evaluations, nodes, and time. |

## Agents and experiment

| Agent | Decision rule |
| --- | --- |
| Random | Uniform sampling over legal edges. |
| Greedy | Maximize immediate captures, then minimize new three-sided boxes. Sample among tied edges. |
| Minimax | Search legal continuations with the same player moving again after a capture. |
| Alpha–Beta | Apply alpha-beta pruning to the same search. |
| Optimized | Order tactical moves first and cache exact values for repeated positions at the same depth. |

Search evaluates the score margin plus a weighted count of boxes ready to capture, signed by whose turn it is. It uses iterative deepening and keeps the last completed depth if a budget is reached. If depth one cannot finish, it applies the capture-first rule. The evaluator uses box units, with full terminal searches returning the actual final margin. Compare heuristic weights with `--threat-weight`.

The included [Minimax experiment](experiments/minimax-comparison/report.md) uses 12 positions across two board sizes. Reproduce it with:

```sh
python -m boxmind benchmark --boards 3x3 4x4 --samples 6 --seed 311 \
  --depth 3 --node-limit 100000 --out reports/minimax-comparison
```

The variants use the same heuristic, depth, node budget and tie break. The report compares node counts and timings on positions where all variants reach the target depth. Use tournaments against named opponents to measure playing strength. For tuning, choose separate seeds for tuning and evaluation.

## Tests

```sh
python -m pytest
```

The tests cover rectangular boards, single and double captures, extra turns, draws, AI legality, search against a complete solver, search budgets, reproducible schedules, report replay, and Pygame controls with a dummy display.
