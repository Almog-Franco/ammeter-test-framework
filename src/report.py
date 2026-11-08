LABELS = {
    "mean": "Mean",
    "median": "Median",
    "std_dev": "Std deviation",
    "min": "Min",
    "max": "Max",
    "cv": "CV (std / mean)",
    "geo_mean": "Geometric mean",
    "ci95": "95% CI of the mean",
    "outliers": "Outliers (1.5 IQR rule)",
}


def fmt(value, unit: str = "") -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4g}{unit}"
    return f"{value}{unit}"


def pct(value, signed: bool = False) -> str:
    if value is None:
        return "-"
    return f"{value:+.1%}" if signed else f"{value:.1%}"


def run_report(run: dict, metrics: list[str]) -> str:
    ammeter, stats, timing = run["ammeter"], run["statistics"], run["consistency"]
    planned = run["sampling"]["measurements_count"]
    failed = f"{run['error_count']} failed, {run['missed']} missed (their time slot had passed)"
    if run["stop_reason"]:
        failed += f", {run['stop_reason']}"
    lines = [
        f"## {ammeter['name']}: {run['status']}",
        "",
        f"Run `{run['run_id']}`, {ammeter['host']}:{ammeter['port']}, started {run['started_at']}",
        f"{stats['count']} valid readings of {planned} planned, {failed}",
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    for metric in metrics:
        if metric not in stats:
            continue
        value = stats[metric]
        if metric == "ci95":
            text = f"{fmt(value[0])} to {fmt(value[1])} A"
        elif metric in ("cv", "outliers"):
            text = fmt(value)
        else:
            text = fmt(value, " A")
        lines.append(f"| {LABELS[metric]} | {text} |")

    lines += [
        "",
        "| Timing and stability | Value |",
        "|---|---|",
        f"| Sampling rate | {fmt(timing['achieved_hz'])} Hz (requested {fmt(timing['requested_hz'])} Hz), "
        f"{timing['taken']} of {timing['planned']} readings taken |",
        f"| Interval jitter (std) | {fmt(timing['interval_jitter_ms'])} ms |",
        f"| Max delay vs schedule | {fmt(timing['max_lag_ms'])} ms |",
        f"| Response time mean / p95 / max | {fmt(timing['latency_mean_ms'])} / {fmt(timing['latency_p95_ms'])} / "
        f"{fmt(timing['latency_max_ms'])} ms |",
        f"| Drift over the run | {_drift(timing)} |",
        "",
        "| Check | Result | Detail |",
        "|---|---|---|",
    ]
    lines += [f"| {c['name']} | {_result(c)} | {c['detail']} |" for c in run["checks"]]
    if run["errors"]:
        lines += ["", "Errors: " + ", ".join(f"{name} x{count}" for name, count in run["errors"].items())]
    if run.get("fault_injection"):
        lines += ["", f"Fault injection was on: {run['fault_injection']}"]
    return "\n".join(lines) + "\n"


def _result(check: dict) -> str:
    if check.get("skipped"):
        return "SKIP"
    return "PASS" if check["passed"] else "FAIL"


def _drift(timing: dict) -> str:
    if timing["drift_pct"] is None:
        return "-"
    if timing["drift_exact"]:
        return f"{timing['drift_pct']:+.3g} % (readings on an exact straight line)"
    if timing["drift_t"] is None:
        return f"{timing['drift_pct']:+.3g} %"
    return f"{timing['drift_pct']:+.3g} % (t = {timing['drift_t']:+.2f})"


def comparison_report(comparison: dict) -> str:
    lines = ["## Comparison", ""]
    if comparison["rows"]:
        lines += [
            "| Rank | Ammeter | n | Mean (A) | Median (A) | CV (95% CI) | Geo. mean vs model | Errors |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for rank, row in enumerate(comparison["rows"], 1):
            low, high = row["cv_ci95"]
            lines.append(
                f"| {rank} | {row['ammeter']} | {row['count']} | {fmt(row['mean'])} | {fmt(row['median'])} | "
                f"{fmt(row['cv'])} ({fmt(low)} to {fmt(high)}) | {pct(row['bias'], signed=True)} | "
                f"{pct(row['error_rate'])} |"
            )
        lines.append("")
    if comparison["not_ranked"]:
        lines += ["Not ranked: " + "; ".join(f"{r['ammeter']} ({r['reason']})" for r in comparison["not_ranked"]), ""]
    if comparison["most_reliable"]:
        lines.append(f"Most reliable in this test: **{comparison['most_reliable']}**, the most precise (lowest CV) of "
                     f"the runs that passed every check, and clearly so: its 95% interval doesn't overlap the others.")
    else:
        lines.append(f"No winner, {comparison['conclusion']}.")
    lines += [
        "",
        "This compares the emulators, whose spread comes from the random input ranges in their code. It doesn't show",
        "which measurement method is more accurate: that needs every meter measuring the same known current.",
    ]
    return "\n".join(lines) + "\n"


def runs_table(entries: list[dict]) -> str:
    if not entries:
        return "No runs found.\n"
    lines = [
        "| Run | Ammeter | Status | n | Mean (A) | Std (A) | CV | Errors |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for e in entries:
        lines.append(
            f"| {e['run_id']} | {e['ammeter']} | {e['status']} | {e['count']} | {fmt(e['mean'])} | "
            f"{fmt(e['std_dev'])} | {fmt(e['cv'])} | {pct(e['error_rate'])} |"
        )
    return "\n".join(lines) + "\n"
