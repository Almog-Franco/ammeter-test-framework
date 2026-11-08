import copy
import hashlib
from pathlib import Path

import pytest
import yaml

from src.errors import ConfigError
from src.settings import PROJECT_ROOT, load_settings


def test_shipped_config_is_valid():
    """The config.yaml that ships with the project loads, with the right ports, commands and expected values.
    Ammeters are found by name in any case, and an unknown name lists the configured ones."""
    settings = load_settings()
    assert {name: spec.port for name, spec in settings.ammeters.items()} == {
        "greenlee": 5001, "entes": 5002, "circutor": 5003,
    }
    assert settings.ammeter("circutor").command == "MEASURE_CIRCUTOR -get_measurement -current"
    assert (settings.sampling.count, settings.sampling.frequency_hz) == (50, 10)
    assert settings.ammeter("entes").expected_geo_mean == 55.51
    assert (settings.acceptance.stuck_after, settings.acceptance.max_model_z) == (3, 5.0)
    assert settings.emulator_seed is None
    assert settings.min_readings_to_rank == 30
    assert settings.ammeter("ENTES").name == "entes"
    with pytest.raises(ConfigError, match="unknown ammeter 'fluke'.*configured: greenlee, entes, circutor"):
        settings.ammeter("fluke")


def test_all_problems_are_reported_together(config, write_config):
    """All problems in a config are reported at once, not one per run, also for the original, fully empty
    config."""
    original = {
        "testing": {"sampling": {"measurements_count": None, "total_duration_seconds": None,
                                 "sampling_frequency_hz": None}},
        "ammeters": None,
        "analysis": {"statistical_metrics": None, "visualization": {"enabled": True, "plot_types": None}},
        "result_management": None,
    }
    with pytest.raises(ConfigError) as error:
        load_settings(write_config(original))
    assert "no ammeters configured" in str(error.value)
    assert "at least two" in str(error.value)

    config["ammeters"]["entes"]["port"] = config["ammeters"]["greenlee"]["port"]
    del config["ammeters"]["circutor"]["command"]
    config["ammeters"]["greenlee"]["expected"]["min"] = 1000
    config["testing"]["sampling"] = {"measurements_count": 10}
    config["testing"]["timeout_seconds"] = -1
    config["fault_injection"]["rates"]["meltdown"] = 0.1
    with pytest.raises(ConfigError) as error:
        load_settings(write_config(config))
    message = str(error.value)
    for problem in ["port 5001 is already used by greenlee", "circutor.command is missing",
                    "expected.min must be smaller", "at least two", "timeout_seconds", "unknown fault 'meltdown'"]:
        assert problem in message


def _set(path, value):
    def edit(config):
        *parents, last = path.split(".")
        for key in parents:
            config = config[key]
        config[last] = value
    return edit


@pytest.mark.parametrize("edit, message", [
    (_set("testing.sampling", [1, 2]), "testing.sampling must be a section"),
    (_set("ammeters.greenlee.expected", [1, 2]), "ammeters.greenlee.expected must be a section"),
    (_set("fault_injection.rates", ["spike"]), "fault_injection.rates must be a section"),
    (_set("testing", "fast"), "testing must be a section"),
    (_set("ammeters", ["greenlee"]), "ammeters must be a section"),
    (_set("testing.timeout_seconds", float("inf")), "timeout_seconds must be a number"),
    (_set("testing.acceptance.max_model_z", float("nan")), "max_model_z must be a number"),
    (_set("testing.sampling", {"total_duration_seconds": float("inf"), "sampling_frequency_hz": 10}),
     "positive number"),
    (_set("testing.start_emulators", "false"), "start_emulators must be true or false"),
    (_set("fault_injection.enabled", "false"), "enabled must be true or false"),
    (_set("analysis.visualization.enabled", 1), "enabled must be true or false"),
    (_set("ammeters.greenlee.host", 123), "host must be a host name"),
    (_set("ammeters.greenlee.emulator", ["greenlee"]), "emulator must be one of"),
    (_set("ammeters.entes.expected", {"geo_mean": 55.5}), "set both geo_mean and log_std"),
    (_set("ammeters.entes.expected.mean", 500), "mean must be between min and max"),
    (_set("ammeters.entes.expected.log_std", 0), "log_std must be above 0"),
    (_set("testing.emulator_seed", "abc"), "emulator_seed must be a whole number"),
    (_set("testing.acceptance.stuck_after", 1), "stuck_after must be a whole number >= 2"),
    (_set("analysis.statistical_metrics", "mean"), "statistical_metrics must be a list"),
    (_set("result_management.results_dir", 5), "results_dir must be a folder name"),
    (_set("testing.acceptance.max_frequency_error", 5), "max_frequency_error"),
    (_set("fault_injection.rates", {"timeout": 0.7, "spike": 0.7}), "add up to more than 1"),
    (_set("ammeters", {}), "no ammeters configured"),
    (_set("testing.timeout_seconds", 0), "timeout_seconds"),
    (_set("ammeters.entes.expected.min", 200.0), "min must be smaller than max"),
    (_set("ammeters.entes.command", "   "), "command is missing"),
    (_set("testing.start_emulators", "yes"), "must be true or false"),
    (_set("testing.start_emulators", "no"), "must be true or false"),
    (_set("ammeters.entes.expected.max", float("inf")), "expected.max must be a number"),
    (_set("ammeters.entes.host", ""), "host must be"),
    (_set("ammeters.my meter", {"port": 5009, "command": "X", "emulator": None}), "may only use letters"),
    (_set("ammeters.Greenlee", {"port": 5009, "command": "X", "emulator": None}), "Greenlee is defined twice"),
    (_set("testing.retries", -1), "retries must be a whole number >= 0"),
    (_set("ammeters.entes.port", 0), "port must be a number from 1 to 65535"),
])
def test_wrong_values_are_reported_clearly(config, write_config, edit, message):
    """Each wrong value gives a ConfigError that says what's wrong and where: section types, NaN or infinite
    numbers, 'false' as text, hosts, ports, names, limits and expected values."""
    edit(config)
    with pytest.raises(ConfigError, match=message):
        load_settings(write_config(config))


def _paths(node, prefix=""):
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        yield path
        if isinstance(value, dict):
            yield from _paths(value, path)


def test_wrong_types_anywhere_give_a_config_error_never_a_crash(config, write_config):
    """Fuzz test: every key in the config is set to every wrong type in turn, and loading always gives a
    ConfigError, never a crash."""
    crashes = []
    for path in _paths(config):
        for bad in ([1, 2], "x", 7, True, float("inf"), {"a": 1}, None):
            broken = copy.deepcopy(config)
            _set(path, bad)(broken)
            try:
                load_settings(write_config(broken), profile="smoke")
            except ConfigError:
                pass
            except Exception as e:
                crashes.append(f"{path} = {bad!r}: {type(e).__name__}: {e}")
    assert not crashes, "\n".join(crashes)


def test_profiles_and_command_line_overrides(config, write_config):
    """Profiles and command-line overrides replace the file's settings, 0 is a valid value, a key left out
    gets its documented default, and an unknown profile is an error."""
    config["testing"].update(retries=0, max_consecutive_errors=0, emulator_seed=3)
    path = write_config(config)
    settings = load_settings(path)
    assert (settings.retries, settings.max_consecutive_errors, settings.emulator_seed) == (0, 0, 3)
    assert load_settings(path, profile="smoke").sampling.count == 10
    custom = load_settings(path, sampling={"total_duration_seconds": 2, "sampling_frequency_hz": 4})
    assert custom.sampling.count == 8
    both = load_settings(path, profile="smoke", sampling={"measurements_count": 7, "sampling_frequency_hz": 7})
    assert both.sampling.count == 7
    assert load_settings(path, faults=True).faults_enabled
    assert not load_settings(path, faults=False).faults_enabled
    assert load_settings(path, emulator_seed=9).emulator_seed == 9
    assert load_settings(path, plots=False).plots_enabled is False
    with pytest.raises(ConfigError, match="unknown profile 'nightly'"):
        load_settings(path, profile="nightly")
    del config["testing"]["max_consecutive_errors"]
    assert load_settings(write_config(config)).max_consecutive_errors == 5  # the documented default


def test_effective_settings_can_be_stored(config, write_config):
    """The settings actually used, after the profile and overrides, are stored with each run: the full
    ammeter details, limits, the config path and its SHA-256."""
    path = write_config(config)
    stored = load_settings(path, profile="smoke", emulator_seed=9).to_dict()
    assert stored["sampling"]["measurements_count"] == 10
    assert stored["emulator_seed"] == 9
    assert stored["acceptance"]["max_model_z"] == 5.0
    assert stored["ammeters"]["entes"]["port"] == 5002
    assert stored["ammeters"]["entes"]["command"] == "MEASURE_ENTES -get_data"
    assert stored["ammeters"]["entes"]["expected_geo_mean"] == 55.51
    assert stored["config_path"] == str(Path(path).resolve())
    assert stored["fault_rates"] == config["fault_injection"]["rates"]
    assert stored["profile"] == "smoke"
    assert stored["config_sha256"] == hashlib.sha256(Path(path).read_bytes()).hexdigest()
    assert "raw" not in stored


def test_config_files_and_paths(config, write_config, tmp_path, monkeypatch):
    """Missing, broken, empty, one-word or list config files give a clear ConfigError. A relative config path is read
    from the current folder first, and the config's results folder is relative to the project."""
    config["result_management"]["results_dir"] = "my_results"
    path = Path(write_config(config))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "my_results").mkdir()  # must not matter: the config is relative to the project
    assert load_settings(path).results_dir == PROJECT_ROOT / "my_results"
    assert load_settings(path, results_dir="cli_results").results_dir == tmp_path.resolve() / "cli_results"
    assert load_settings(path.name).config_path == path.resolve()
    (tmp_path / "config").mkdir()
    config["analysis"]["min_readings_to_rank"] = 31
    (tmp_path / "config" / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    assert load_settings("config/config.yaml").min_readings_to_rank == 31  # the current folder's, not the project's

    with pytest.raises(ConfigError, match="not found"):
        load_settings(tmp_path / "nope.yaml")
    with pytest.raises(ConfigError, match="not found"):
        load_settings(tmp_path)  # a folder
    (tmp_path / "broken.yaml").write_text("ammeters: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="broken.yaml is not valid YAML"):
        load_settings("broken.yaml")
    (tmp_path / "list.yaml").write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="must contain key: value sections"):
        load_settings(tmp_path / "list.yaml")
    (tmp_path / "word.yaml").write_text("hello", encoding="utf-8")
    with pytest.raises(ConfigError, match="must contain key: value sections"):
        load_settings("word.yaml")
    (tmp_path / "empty.yaml").write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match="no ammeters configured"):
        load_settings("empty.yaml")
