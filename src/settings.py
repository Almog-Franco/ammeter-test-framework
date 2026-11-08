import hashlib
import math
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import yaml

from src.errors import ConfigError
from src.sampling import SamplingPlan
from src.utils.config import load_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = "config/config.yaml"
METRICS = ("mean", "median", "std_dev", "min", "max", "cv", "geo_mean", "ci95", "outliers")
PLOT_TYPES = ("timeseries", "histogram", "comparison")
FAULT_TYPES = ("timeout", "no_response", "garbage", "spike", "stuck")


@dataclass(frozen=True)
class AmmeterSpec:
    name: str
    port: int
    command: str
    host: str = "127.0.0.1"
    emulator: str | None = None  # which emulator to start for it; None for a real device
    expected_min: float | None = None
    expected_max: float | None = None
    expected_mean: float | None = None
    expected_geo_mean: float | None = None
    expected_log_std: float | None = None


@dataclass(frozen=True)
class Acceptance:
    max_error_rate: float = 0.05
    max_frequency_error: float = 0.1
    stuck_after: int = 3
    max_model_z: float = 5.0
    max_drift_t: float = 5.0


@dataclass
class Settings:
    ammeters: dict[str, AmmeterSpec]
    sampling: SamplingPlan
    acceptance: Acceptance = field(default_factory=Acceptance)
    timeout_s: float = 2.0
    retries: int = 1
    max_consecutive_errors: int = 5
    start_emulators: bool = True
    emulator_seed: int | None = None
    metrics: list[str] = field(default_factory=lambda: list(METRICS))
    min_readings_to_rank: int = 30
    plots_enabled: bool = True
    plot_types: list[str] = field(default_factory=lambda: list(PLOT_TYPES))
    results_dir: Path = PROJECT_ROOT / "results"
    faults_enabled: bool = False
    fault_rates: dict[str, float] = field(default_factory=dict)
    fault_seed: int | str | None = None
    profile: str | None = None
    config_path: Path | None = None
    config_sha256: str | None = None
    raw: dict = field(default_factory=dict)

    def ammeter(self, name: str) -> AmmeterSpec:
        try:
            return self.ammeters[str(name).lower()]
        except KeyError:
            raise ConfigError(f"unknown ammeter {name!r}, configured: {', '.join(self.ammeters)}") from None

    def to_dict(self) -> dict:
        """The settings a run actually used, after command-line overrides. Stored with every run."""
        data = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "raw"}
        data["ammeters"] = {name: asdict(spec) for name, spec in self.ammeters.items()}
        data["sampling"] = self.sampling.to_dict()
        data["acceptance"] = asdict(self.acceptance)
        data["results_dir"] = str(self.results_dir)
        data["config_path"] = str(self.config_path)
        return data


def resolve_config_path(path) -> Path:
    """A config path given by the user is taken from the current folder, the default one from the project."""
    path = Path(path)
    return path.resolve() if path.is_absolute() or path.exists() else PROJECT_ROOT / path


def load_settings(config_path=DEFAULT_CONFIG, profile=None, sampling=None, faults=None,
                  results_dir=None, plots=None, emulator_seed=None) -> Settings:
    """Loads and validates the config. The keyword arguments override it (used by the command line)."""
    path = resolve_config_path(config_path)
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = load_config(str(path))
    except yaml.YAMLError as e:
        raise ConfigError(f"{path} is not valid YAML: {e}") from None
    raw = {} if raw is None else raw
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain key: value sections, not a {type(raw).__name__}")

    errors = []
    testing = _section(raw, "testing", errors)
    acceptance = _section(testing, "acceptance", errors, "testing")
    analysis = _section(raw, "analysis", errors)
    visualization = _section(analysis, "visualization", errors, "analysis")
    results = _section(raw, "result_management", errors)
    fault_cfg = _section(raw, "fault_injection", errors)

    ammeters = _parse_ammeters(raw.get("ammeters"), errors)

    if sampling is None and profile:
        profiles = _section(testing, "profiles", errors, "testing")
        if profile in profiles:
            sampling = _section(profiles, profile, errors, "testing.profiles")
        else:
            errors.append(f"unknown profile {profile!r}, available: {', '.join(map(str, profiles)) or 'none'}")
            sampling = {}
    if sampling is None:
        sampling = _section(testing, "sampling", errors, "testing")
    plan = None
    try:
        plan = SamplingPlan.from_config(
            sampling.get("measurements_count"),
            sampling.get("total_duration_seconds"),
            sampling.get("sampling_frequency_hz"),
        )
    except ConfigError as e:
        errors.append(str(e))

    rates = {}
    for fault, rate in _section(fault_cfg, "rates", errors, "fault_injection").items():
        if fault not in FAULT_TYPES:
            errors.append(f"fault_injection.rates: unknown fault {fault!r}, use {', '.join(FAULT_TYPES)}")
        elif not _is_number(rate) or not 0 <= rate <= 1:
            errors.append(f"fault_injection.rates.{fault} must be between 0 and 1, got {rate!r}")
        else:
            rates[fault] = float(rate)
    if sum(rates.values()) > 1:
        errors.append("fault_injection.rates add up to more than 1")
    fault_seed = fault_cfg.get("seed")
    if fault_seed is not None and (isinstance(fault_seed, bool) or not isinstance(fault_seed, (int, str))):
        errors.append(f"fault_injection.seed must be a whole number or text, got {fault_seed!r}")

    folder = results.get("results_dir")
    if folder is not None and (not isinstance(folder, str) or not folder.strip()):
        errors.append(f"result_management.results_dir must be a folder name, got {folder!r}")
        folder = None

    seed = testing.get("emulator_seed") if emulator_seed is None else emulator_seed
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        errors.append(f"testing.emulator_seed must be a whole number or null, got {seed!r}")

    settings = Settings(
        ammeters=ammeters,
        sampling=plan,
        acceptance=Acceptance(
            max_error_rate=_number(acceptance, "max_error_rate", 0.05, errors, "testing.acceptance", high=1),
            max_frequency_error=_number(acceptance, "max_frequency_error", 0.1, errors, "testing.acceptance", high=1),
            stuck_after=_number(acceptance, "stuck_after", 3, errors, "testing.acceptance", integer=True, low=2),
            max_model_z=_number(acceptance, "max_model_z", 5.0, errors, "testing.acceptance", low=0.1),
            max_drift_t=_number(acceptance, "max_drift_t", 5.0, errors, "testing.acceptance", low=0.1),
        ),
        timeout_s=_number(testing, "timeout_seconds", 2.0, errors, "testing", low=0.01),
        retries=_number(testing, "retries", 1, errors, "testing", integer=True),
        max_consecutive_errors=_number(testing, "max_consecutive_errors", 5, errors, "testing", integer=True),
        start_emulators=_bool(testing, "start_emulators", True, errors, "testing"),
        emulator_seed=seed,
        metrics=_choices(analysis, "statistical_metrics", METRICS, errors, "analysis"),
        min_readings_to_rank=_number(analysis, "min_readings_to_rank", 30, errors, "analysis", integer=True, low=2),
        plots_enabled=_bool(visualization, "enabled", True, errors, "analysis.visualization") if plots is None else plots,
        plot_types=_choices(visualization, "plot_types", PLOT_TYPES, errors, "analysis.visualization"),
        # from the command line: relative to the current folder; from the config: relative to the project
        results_dir=Path(results_dir).resolve() if results_dir else PROJECT_ROOT / (folder or "results"),
        faults_enabled=_bool(fault_cfg, "enabled", False, errors, "fault_injection") if faults is None else faults,
        fault_rates=rates,
        fault_seed=fault_seed,
        profile=profile,
        config_path=path,
        config_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        raw=raw,
    )
    if errors:
        raise ConfigError(f"invalid configuration in {path}:\n  - " + "\n  - ".join(errors))
    return settings


def _parse_ammeters(raw, errors) -> dict[str, AmmeterSpec]:
    from src.emulators import EMULATORS  # imported here because src.emulators imports this module

    if not raw:
        errors.append("ammeters: no ammeters configured")
        return {}
    if not isinstance(raw, dict):
        errors.append(f"ammeters must be a section with one entry per ammeter, got {type(raw).__name__}")
        return {}
    specs, used_ports = {}, {}
    for key, cfg in raw.items():
        name, where = str(key).lower(), f"ammeters.{key}"
        if not re.fullmatch(r"[a-z0-9_-]+", name):  # the name becomes part of run ids and folder names
            errors.append(f"{where}: an ammeter name may only use letters, digits, _ and -")
            continue
        if name in specs:
            errors.append(f"{where} is defined twice")
            continue
        if not isinstance(cfg, dict):
            errors.append(f"{where} must be a section with port, command, ...")
            continue
        port, command, host = cfg.get("port"), cfg.get("command"), cfg.get("host")
        host = "127.0.0.1" if host is None else host
        port_ok = isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535
        if not port_ok:
            errors.append(f"{where}.port must be a number from 1 to 65535, got {port!r}")
        if not isinstance(host, str) or not host.strip():
            errors.append(f"{where}.host must be a host name or IP address, got {host!r}")
        elif port_ok and (host, port) in used_ports:
            errors.append(f"{where}.port {port} is already used by {used_ports[host, port]}")
        elif port_ok:
            used_ports[host, port] = name
        if not isinstance(command, str) or not command.strip():
            errors.append(f"{where}.command is missing")

        emulator = cfg.get("emulator", name if name in EMULATORS else None)
        if emulator is not None and (not isinstance(emulator, str) or emulator not in EMULATORS):
            errors.append(f"{where}.emulator must be one of {', '.join(EMULATORS)} or null, got {emulator!r}")

        expected = _section(cfg, "expected", errors, where)
        values = {}
        for k in ("min", "max", "mean", "geo_mean", "log_std"):
            value = expected.get(k)
            if value is not None and not _is_number(value):
                errors.append(f"{where}.expected.{k} must be a number, got {value!r}")
                value = None
            values[k] = value
        low, high = values["min"], values["max"]
        if low is not None and high is not None:
            if low >= high:
                errors.append(f"{where}.expected.min must be smaller than max")
            for k in ("mean", "geo_mean"):
                if values[k] is not None and not low <= values[k] <= high:
                    errors.append(f"{where}.expected.{k} must be between min and max")
        if (values["geo_mean"] is None) != (values["log_std"] is None):
            errors.append(f"{where}.expected: set both geo_mean and log_std, or neither")
        for k in ("geo_mean", "log_std"):
            if values[k] is not None and values[k] <= 0:
                errors.append(f"{where}.expected.{k} must be above 0")

        specs[name] = AmmeterSpec(name, port, command, host, emulator, low, high, values["mean"],
                                  values["geo_mean"], values["log_std"])
    return specs


def _section(parent: dict, key: str, errors: list, where: str = "") -> dict:
    """A sub-section of the config. Missing or empty is fine; anything but key: value pairs is an error."""
    value = parent.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        name = f"{where}.{key}" if where else key
        errors.append(f"{name} must be a section of key: value pairs, got {type(value).__name__} {value!r}")
        return {}
    return value


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _number(cfg, key, default, errors, where, integer=False, low=0.0, high=None):
    value = cfg.get(key)
    if value is None:
        return default
    valid = _is_number(value) and value >= low and (high is None or value <= high)
    if integer and valid:
        valid = value == int(value)
    if not valid:
        limits = f">= {low:g}" + (f" and <= {high:g}" if high is not None else "")
        errors.append(f"{where}.{key} must be a {'whole ' if integer else ''}number {limits}, got {value!r}")
        return default
    return int(value) if integer else float(value)


def _bool(cfg, key, default, errors, where) -> bool:
    value = cfg.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        errors.append(f"{where}.{key} must be true or false, got {value!r}")
        return default
    return value


def _choices(cfg, key, allowed, errors, where) -> list[str]:
    value = cfg.get(key)
    if value is None:
        return list(allowed)
    if not isinstance(value, list):
        errors.append(f"{where}.{key} must be a list, got {value!r}")
        return list(allowed)
    unknown = [v for v in value if v not in allowed]
    if unknown:
        errors.append(f"{where}.{key}: unknown {unknown}, choose from {', '.join(allowed)}")
        return list(allowed)
    return value
