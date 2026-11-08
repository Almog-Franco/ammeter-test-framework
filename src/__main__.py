import argparse
import sys

from src import plots, report
from src.errors import ArchiveError, ConfigError, EmulatorError
from src.testing.test_framework import AmmeterTestFramework


def cmd_run(framework, args) -> int:
    result = framework.run_all(args.ammeters or None)
    for run in result["runs"]:
        print(report.run_report(run, framework.settings.metrics))
    if len(result["runs"]) > 1:
        print(report.comparison_report(result["comparison"]))
    print(f"Results saved in {framework.store.root}")
    return 0 if all(run["status"] == "PASS" for run in result["runs"]) else 1


def cmd_list(framework, args) -> int:
    print(report.runs_table(framework.store.list_runs(args.ammeter, args.status)))
    return 0


def cmd_show(framework, args) -> int:
    print(report.run_report(framework.store.load(args.run_id), framework.settings.metrics))
    return 0


def cmd_compare(framework, args) -> int:
    print(report.comparison_report(framework.compare_runs(args.run_ids)))
    return 0


def cmd_history(framework, args) -> int:
    entries = framework.store.list_runs(args.ammeter)
    print(report.runs_table(entries))
    if entries and framework.settings.plots_enabled:
        path = plots.plot_history(entries, framework.store.root / f"history_{args.ammeter}.png")
        if path:
            print(f"Trend plot: {path}")
    return 0


COMMANDS = {"run": cmd_run, "list": cmd_list, "show": cmd_show, "compare": cmd_compare, "history": cmd_history}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src", description="Ammeter test framework")
    parser.add_argument("--config", default="config/config.yaml", help="config file (default: %(default)s)")
    parser.add_argument("--results-dir", help="where to store and read results (default: from the config)")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="test one or more ammeters (all of them by default)")
    run.add_argument("ammeters", nargs="*", help="e.g. greenlee entes")
    run.add_argument("--profile", help="sampling profile from the config, e.g. smoke")
    run.add_argument("--count", type=int, help="number of measurements")
    run.add_argument("--duration", type=float, help="total duration in seconds")
    run.add_argument("--frequency", type=float, help="sampling frequency in Hz")
    run.add_argument("--faults", action="store_true", help="inject errors into the emulators")
    run.add_argument("--seed", type=int, help="seed for the emulators' readings, to repeat a run exactly")
    run.add_argument("--no-plots", action="store_true")

    listing = sub.add_parser("list", help="list archived runs")
    listing.add_argument("--ammeter")
    listing.add_argument("--status", help="PASS, FAIL, ERROR or INTERRUPTED")
    sub.add_parser("show", help="show the report of an archived run").add_argument("run_id")
    sub.add_parser("compare", help="compare archived runs").add_argument("run_ids", nargs="+")
    sub.add_parser("history", help="all runs of one ammeter, with a trend plot").add_argument("ammeter")

    args = parser.parse_args(argv)
    overrides = {"results_dir": args.results_dir}
    if args.command == "run":
        sampling = {
            "measurements_count": args.count,
            "total_duration_seconds": args.duration,
            "sampling_frequency_hz": args.frequency,
        }
        sampling = {key: value for key, value in sampling.items() if value is not None}
        overrides.update(
            profile=args.profile,
            sampling=sampling or None,
            faults=True if args.faults else None,
            plots=False if args.no_plots else None,
            emulator_seed=args.seed,
        )

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    try:
        with AmmeterTestFramework(args.config, **overrides) as framework:
            return COMMANDS[args.command](framework, args)
    except (ConfigError, EmulatorError, ArchiveError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
