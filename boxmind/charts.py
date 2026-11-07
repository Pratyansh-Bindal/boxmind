"""Optional pandas and Matplotlib visualization of a tournament summary."""

from pathlib import Path

from .agents import AgentKind


def plot_summary(source: Path, destination: Path) -> Path:
    try:
        import matplotlib
        import pandas as pd
    except ImportError as exc:
        raise ValueError("Install the analysis dependencies with pip install '.[analysis]'") from exc
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.ticker import PercentFormatter

    data = pd.read_csv(source)
    columns = {"agent", "games", "win_rate", "loss_rate", "draw_rate", "mean_ms", "p95_ms"}
    if data.empty or not columns <= set(data):
        raise ValueError("Choose a nonempty BoxMind summary.csv")
    if destination.exists():
        raise FileExistsError(f"Chart already exists: {destination}")
    data["label"] = [f"{AgentKind(name).label}  ·  {games} games"
                     for name, games in zip(data["agent"], data["games"], strict=True)]
    data = data.set_index("label")
    fig, (outcome, latency) = plt.subplots(1, 2, figsize=(12.6, 5.6), layout="constrained")
    fig.set_facecolor("#f4f6fa")
    fig.suptitle("BoxMind  /  Tournament comparison", fontsize=19, fontweight="bold",
                 color="#172343", x=0.02, ha="left")
    data[["win_rate", "draw_rate", "loss_rate"]].rename(columns={
        "win_rate": "Win", "draw_rate": "Draw", "loss_rate": "Loss",
    }).plot.barh(stacked=True, ax=outcome, color=["#218771", "#b8c4d9", "#8664cf"], width=0.58)
    data[["mean_ms", "p95_ms"]].rename(columns={
        "mean_ms": "Mean", "p95_ms": "95th percentile",
    }).plot.barh(ax=latency, color=["#4981cb", "#323d72"], width=0.62)
    outcome.set_title("Game outcomes", loc="left", fontweight="bold")
    outcome.set_xlabel("Share of games")
    outcome.set_xlim(0, 1)
    outcome.xaxis.set_major_formatter(PercentFormatter(xmax=1))
    latency.set_title("Decision latency", loc="left", fontweight="bold")
    latency.set_xlabel("Milliseconds per decision")
    for axis in (outcome, latency):
        axis.set_ylabel("")
        axis.invert_yaxis()
        axis.spines[["top", "right", "left"]].set_visible(False)
        axis.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13), ncols=3, frameon=False)
        axis.grid(axis="x", alpha=0.22)
        axis.set_axisbelow(True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        fig.savefig(destination, dpi=170)
    finally:
        plt.close(fig)
    return destination.resolve()
