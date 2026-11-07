# Minimax optimization experiment

**12 positions** · 6 per board · Seed `311`

Board sizes in dots are 3×3, 4×4. Each variant evaluated the same positions with the same depth, heuristic and budget. The first position on each board was empty. The others used increasingly long seeded legal move sequences. Ties between evaluations use the same edge order.

Depth 3, node limit 100,000, wall clock cap off, threat weight 0.35.
Measured on Darwin 27.2.0 arm64, Python 3.12.14. Each position was timed once per variant in the same process.

All three variants reached the target depth on **12/12** positions. They agreed on every candidate evaluation on **12/12** of those positions.

| Variant | Mean nodes | Node reduction vs Minimax | Mean decision (ms) |
| :-- | --: | --: | --: |
| Minimax | 2,882.6 | 0.0% | 3.244 |
| Alpha–Beta | 852.3 | 70.4% | 1.235 |
| Optimized | 686.8 | 76.2% | 2.676 |

The table includes only positions where all variants reached their target depth.

Node counts include each visit during iterative deepening, including leaves and cache hits. The comparison measures search work and decision time on these positions.

[Per-position CSV](positions.csv) · [Experiment settings](config.json)
