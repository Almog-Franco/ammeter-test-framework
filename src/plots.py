import logging
import math
from pathlib import Path

log = logging.getLogger(__name__)


def _pyplot():
    try:
        import matplotlib
    except ImportError:
        log.warning("matplotlib is not installed, skipping plots")
        return None
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _save(plt, fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def _spans_decades(values) -> bool:
    """Long-tailed readings (Greenlee) or spikes are unreadable on a linear axis."""
    return min(values) > 0 and max(values) / min(values) > 100


def plot_run(run: dict, samples, out_dir: Path, plot_types: list[str]) -> list[Path]:
    plt = _pyplot()
    points = [(s.time_s, s.value) for s in samples if s.value is not None]
    if plt is None or not points:
        return []
    times, values = zip(*points)
    stats, name = run["statistics"], run["ammeter"]["name"]
    mean, std = stats["mean"], stats["std_dev"]
    log_scale = _spans_decades(values)
    paths = []

    if "timeseries" in plot_types:
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.plot(times, values, marker=".", linewidth=0.8, label="reading")
        ax.axhline(mean, color="tab:red", label=f"mean {mean:.4g} A")
        ax.axhspan(max(mean - std, min(values) / 2), mean + std, color="tab:red", alpha=0.1, label="mean ± 1 std")
        failed = [s.time_s for s in samples if s.error]
        if failed:
            ax.scatter(failed, [stats["min"]] * len(failed), marker="x", color="black", label=f"failed ({len(failed)})")
        if log_scale:
            ax.set_yscale("log")
        ax.set(title=f"{name}: readings over time ({run['status']})", xlabel="time (s)", ylabel="current (A)")
        ax.legend(fontsize=8)
        paths.append(_save(plt, fig, out_dir / "timeseries.png"))

    if "histogram" in plot_types:
        fig, ax = plt.subplots(figsize=(6, 4))
        bins = "auto"
        if log_scale:
            low, high = min(values), max(values)
            bins = [low * (high / low) ** (i / 30) for i in range(31)]
            ax.set_xscale("log")
        ax.hist(values, bins=bins, color="tab:blue", alpha=0.8)
        ax.axvline(mean, color="tab:red", label=f"mean {mean:.4g} A")
        ax.axvline(stats["median"], color="tab:green", linestyle="--", label=f"median {stats['median']:.4g} A")
        ax.set(title=f"{name}: distribution", xlabel="current (A)", ylabel="count")
        ax.legend(fontsize=8)
        paths.append(_save(plt, fig, out_dir / "histogram.png"))
    return paths


def plot_comparison(runs_with_samples: list, path: Path) -> Path | None:
    """Readings divided by each ammeter's expected mean, so ranges 1000x apart fit on one chart."""
    plt = _pyplot()
    if plt is None:
        return None
    names, data, cvs, errors = [], [], [], [[], []]
    for run, samples in runs_with_samples:
        values = [s.value for s in samples if s.value is not None and s.value > 0]
        if not values:
            continue
        reference = run["ammeter"].get("expected_mean") or run["statistics"]["median"]
        names.append(run["ammeter"]["name"])
        data.append([v / reference for v in values])
        cv, interval = run["statistics"].get("cv") or 0, run["statistics"].get("cv_ci95") or [0, 0]
        cvs.append(cv)
        errors[0].append(max(0, cv - interval[0]))
        errors[1].append(max(0, interval[1] - cv))
    if not data:
        return None

    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4))
    left.boxplot(data)
    left.set_xticks(range(1, len(names) + 1), names)
    left.set_yscale("log")
    left.axhline(1, color="tab:red", linewidth=0.8, label="expected mean")
    left.set(title="Readings / expected mean (log scale)", ylabel="relative current")
    left.legend(fontsize=8)
    right.bar(names, cvs, yerr=errors, capsize=6, color="tab:orange")
    right.set(title="Precision: CV with 95% interval (lower is better)", ylabel="CV")
    return _save(plt, fig, path)


def plot_history(entries: list[dict], path: Path) -> Path | None:
    plt = _pyplot()
    entries = [e for e in entries if e.get("mean") is not None]
    if plt is None or not entries:
        return None
    means = [e["mean"] for e in entries]
    margins = [1.96 * (e["std_dev"] or 0) / math.sqrt(e["count"]) for e in entries]
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.errorbar(range(len(entries)), means, yerr=margins, fmt="o-", capsize=4)
    ax.set_xticks(range(len(entries)), [e["started_at"][:19].replace("T", "\n") for e in entries], fontsize=7)
    ax.set(title=f"{entries[0]['ammeter']}: mean and 95% CI per run", ylabel="current (A)")
    return _save(plt, fig, path)
