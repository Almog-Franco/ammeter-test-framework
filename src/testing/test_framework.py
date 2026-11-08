import atexit
import logging
import platform
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Dict

from src import analysis, plots, report
from src.client import AmmeterClient
from src.emulators import EmulatorProcess, port_is_open
from src.errors import AmmeterError, EmulatorError
from src.results import ResultStore, new_id
from src.sampling import Sampler
from src.settings import load_settings
from src.utils.logger import TestLogger

log = logging.getLogger(__name__)


class AmmeterTestFramework:
    def __init__(self, config_path: str = "config/config.yaml", **overrides):
        self.settings = load_settings(config_path, **overrides)
        self.config = self.settings.raw
        self.store = ResultStore(self.settings.results_dir)
        self._emulators = None
        self._emulators_checked = False
        atexit.register(self.close)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self._emulators:
            self._emulators.stop()
            self._emulators = None
        self._emulators_checked = False

    def run_test(self, ammeter_type: str) -> Dict:
        """Samples one ammeter, analyses and archives the run, and returns it as a dict."""
        spec = self.settings.ammeter(ammeter_type)
        self._ensure_emulators()
        settings, plan = self.settings, self.settings.sampling
        run_id = new_id(spec.name)
        logger = TestLogger(run_id.split("_", 1)[1], log_dir=str(settings.results_dir / "logs"))
        logger.info(f"{spec.name} at {spec.host}:{spec.port}: {plan.count} readings at {plan.frequency_hz:g} Hz")

        client = AmmeterClient.from_spec(spec, settings.timeout_s, settings.retries)
        started_at = _now()
        result = Sampler().run(plan, client.measure, settings.max_consecutive_errors)
        finished_at = _now()

        samples = result.samples
        values = [s.value for s in samples if s.value is not None]
        failed = [s for s in samples if s.error]
        for s in failed:
            logger.warning(f"reading {s.index} failed: {s.error}")
        error_rate = len(failed) / len(samples) if samples else 0.0
        timing = analysis.consistency(samples, plan)
        checks = analysis.evaluate(values, error_rate, timing, spec, settings.acceptance)
        out_of_range = analysis.count_out_of_range(values, spec.expected_min, spec.expected_max)

        run = {
            "run_id": run_id,
            "status": analysis.verdict(checks, len(values), result.stop_reason),
            "ammeter": asdict(spec),
            "sampling": plan.to_dict(),
            "started_at": started_at,
            "finished_at": finished_at,
            "stop_reason": result.stop_reason,
            "missed": result.missed,
            "statistics": analysis.summarize(values),
            "error_count": len(failed),
            "error_rate": error_rate,
            "errors": dict(Counter(s.error.split(":")[0] for s in failed)),
            "out_of_range_rate": out_of_range / len(values) if values else 0.0,
            "consistency": timing,
            "checks": checks,
            "fault_injection": self._fault_options(),
            "settings": settings.to_dict(),
            "config": {"path": str(settings.config_path), "sha256": settings.config_sha256,
                       "profile": settings.profile, "content": settings.raw},
            "environment": {"python": platform.python_version(), "platform": platform.platform()},
            "log_file": logger.log_file,
        }
        self.store.save(run, samples)
        if settings.plots_enabled:
            plots.plot_run(run, samples, self.store.run_dir(run_id) / "plots", settings.plot_types)
        self.store.write_file(run_id, "report.md", report.run_report(run, settings.metrics))
        logger.info(f"finished with status {run['status']}")
        logger.close()
        return run

    def run_all(self, ammeter_types: list[str] | None = None) -> Dict:
        """Runs every given (default: every configured) ammeter and compares them."""
        names = ammeter_types or list(self.settings.ammeters)
        for name in names:
            self.settings.ammeter(name)  # an unknown name fails now, not after testing the others
        runs = []
        for name in names:
            runs.append(self.run_test(name))
            if runs[-1]["status"] == "INTERRUPTED":
                break
        comparison = analysis.compare(runs, self.settings.min_readings_to_rank)
        folder = self.store.save_comparison(comparison, report.comparison_report(comparison))
        if self.settings.plots_enabled and "comparison" in self.settings.plot_types and len(runs) > 1:
            pairs = [(run, self.store.load_samples(run["run_id"])) for run in runs]
            plots.plot_comparison(pairs, folder / "comparison.png")
        comparison["folder"] = str(folder)
        return {"runs": runs, "comparison": comparison}

    def compare_runs(self, run_ids: list[str]) -> Dict:
        return analysis.compare([self.store.load(run_id) for run_id in run_ids], self.settings.min_readings_to_rank)

    def _ensure_emulators(self):
        """Starts the emulators that aren't running yet. A port that answers with garbage belongs to someone else."""
        if self._emulators_checked or not self.settings.start_emulators:
            return
        missing = []
        for spec in self.settings.ammeters.values():
            if spec.emulator is None:
                continue
            if not port_is_open(spec.host, spec.port):  # a quick check: on Windows a refusal takes about 2 s
                missing.append(spec)
                continue
            try:
                AmmeterClient.from_spec(spec, timeout_s=1.0, retries=0).measure()
            except AmmeterError:
                hint = " (on macOS this is AirPlay Receiver)" if spec.port == 5000 and sys.platform == "darwin" else ""
                raise EmulatorError(
                    f"port {spec.port} for {spec.name} is used by another program{hint}, pick another port in the config"
                ) from None
            if self.settings.faults_enabled or self.settings.emulator_seed is not None:
                log.warning("%s is already running, so its faults and seed can't be set", spec.name)
        if missing:
            log_path = self.settings.results_dir / "logs" / "emulators.log"
            self._emulators = EmulatorProcess(missing, log_path, self._fault_options(),
                                              self.settings.emulator_seed).start()
        self._emulators_checked = True

    def _fault_options(self) -> dict | None:
        if not self.settings.faults_enabled:
            return None
        return {"rates": self.settings.fault_rates, "seed": self.settings.fault_seed,
                "delay_s": self.settings.timeout_s + 1}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
