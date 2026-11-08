# Ammeter Test Framework

Emulators for three ammeters (Greenlee, ENTES, CIRCUTOR) and a framework that samples them, analyses the readings,
decides PASS or FAIL, and keeps every run in a results archive. It can also inject errors into the emulators to show
that the error handling works.

- [docs/FIXES.md](docs/FIXES.md): every change to the original code, and why
- [docs/DESIGN.md](docs/DESIGN.md): design decisions, checks and their limits, results layout
- [sample_results/](sample_results/README.md): output of real runs, normal, long and with injected faults

## Setup

Python 3.10 or newer, on Windows, macOS or Linux.

```sh
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

Libraries installed for this project:

| Library | Version | Used for |
|---|---|---|
| PyYAML | 6.0.3 | Reading `config.yaml` (was already installed) |
| matplotlib | 3.11.2 | Charts. Optional: without it the charts are skipped. It brings numpy, pillow and a few small packages |
| pytest | 9.1.1 | The framework's own tests (`requirements-dev.txt`) |
| pytest-xdist | 3.8.0 | Running the tests in parallel (`requirements-dev.txt`) |

numpy, scipy, pandas and seaborn were removed from `requirements.txt`. The statistics use Python's `statistics`
module. Only `tools/calibrate_checks.py` uses numpy, which comes with matplotlib.

## Usage

**Quick check**: start the emulators and get one reading from each:

```sh
python main.py
```

**Test the ammeters**: all of them by default. Emulators that aren't running are started automatically:

```sh
python -m src run                          # all ammeters, sampling from config.yaml, plus a comparison
python -m src run entes circutor           # only these two
python -m src run --profile smoke          # quick run: 10 readings at 20 Hz
python -m src run --count 400 --frequency 40
python -m src run --duration 30 --frequency 5
python -m src run --faults                 # inject errors and see them caught
python -m src run --seed 1                 # repeatable readings
```

The exit code is 0 when every run passed, 1 when one failed and 2 for a config or startup error.

**Look at past results**:

```sh
python -m src list [--ammeter entes] [--status FAIL]
python -m src show <run_id>
python -m src --results-dir sample_results show 20261026T135630Z_greenlee_41ac2a   # one of the sample runs
python -m src compare <run_id> <run_id> ...
python -m src history entes                # every run of one ammeter, with a trend chart
```

**From Python** (see [examples/run_tests.py](examples/run_tests.py)):

```python
from src.testing.test_framework import AmmeterTestFramework

with AmmeterTestFramework("config/config.yaml") as framework:
    result = framework.run_test("greenlee")    # dict: status, statistics, timing, checks, settings, ...
    print(result["status"], result["statistics"]["mean"])
    everything = framework.run_all()           # all ammeters + comparison
```

**The framework's own tests**:

```sh
python -m pytest                        # 65 tests (163 cases), about 35 seconds
python -m pytest -n auto                # in parallel, about 13 seconds
python -m pytest -m "not integration"   # skip the tests that run against the emulators
UPDATE_GOLDEN=1 python -m pytest tests/test_report.py   # after changing a report on purpose: save new copies
```

## What a run produces

```
## circutor: PASS

Run `20261026T135640Z_circutor_66d582`, 127.0.0.1:5003, started 2026-10-26T13:56:40.602+00:00
50 valid readings of 50 planned, 0 failed, 0 missed (their time slot had passed)

| Metric | Value |
|---|---|
| Mean | 0.03317 A |
| Median | 0.03514 A |
| Std deviation | 0.01576 A |
...
| Check | Result | Detail |
|---|---|---|
| values_in_range | PASS | 0 of 50 outside [0.001, 0.1] A |
| error_rate | PASS | 0.0% failed (limit 5%) |
| sampling_rate | PASS | 50 of 50 planned readings taken, 10 Hz for 10 Hz requested (0.0% short, limit 10%) |
| not_stuck | PASS | longest run of identical readings: 1 (stuck from 3) |
| matches_model | PASS | geometric mean 0.02794 A, model 0.02583 A (z = +0.91, limit ±5) |
| no_drift | PASS | -12.2 % over the run (t = -0.53, limit ±5) |
```

The checks are explained, with their false-alarm rates and limits, in [docs/DESIGN.md](docs/DESIGN.md#acceptance-checks-and-verdict).

A comparison names a winner only when the evidence is clear:
- **It ranks precision (CV) among runs that passed every check.** A run also needs at least 30 readings to take part.
- **It says "insufficient evidence" when the precision of the best runs overlaps.** With the default 50 readings,
  CIRCUTOR and ENTES usually tie; with 400 readings CIRCUTOR wins clearly.
- **It compares how the emulators behave, not which measurement method is more accurate.** That would need every
  meter measuring the same known current.

Each run is stored in `results/runs/<run_id>/`:

- `run.json`: the effective settings, the full config, all results
- `samples.csv`: every reading
- `report.md`: the report above
- `plots/`: the charts

`results/index.jsonl` lists all runs. See [docs/DESIGN.md](docs/DESIGN.md#results-archive).

## Configuration

Everything is in [config/config.yaml](config/config.yaml):

| Section | What it sets |
|---|---|
| `testing.sampling` | Any two of `measurements_count`, `total_duration_seconds`, `sampling_frequency_hz`. The third is calculated |
| `testing.profiles` | Named sampling settings, used with `--profile` |
| `testing` | `timeout_seconds` (whole request), `retries`, `max_consecutive_errors` (0 = never stop early), `start_emulators`, `emulator_seed` |
| `testing.acceptance` | `max_error_rate`, `max_frequency_error` (missed readings), `stuck_after`, `max_model_z`, `max_drift_t` |
| `ammeters.<name>` | `port`, `command`, optional `host` and `emulator`, and `expected` min / max / mean / geo_mean / log_std |
| `analysis` | Which metrics the report shows, `min_readings_to_rank`, which charts are made |
| `result_management.results_dir` | Where results go. Relative paths are taken from the project folder (`--results-dir` from the current folder) |
| `fault_injection` | `enabled`, `seed`, and the rate of each fault (`timeout`, `no_response`, `garbage`, `spike`, `stuck`) |

The config is checked when it's loaded:
- every section must be key: value pairs
- numbers must be finite and in range
- switches must be real `true`/`false`

Every problem is listed at once. The expected values come from the README's physics (see
[docs/DESIGN.md](docs/DESIGN.md#what-the-emulators-should-produce)). They can be re-derived with
`python tools/calibrate_checks.py`.

## Ammeter emulators

| Ammeter | Port | Command | Method |
|---|---|---|---|
| Greenlee | 5001 | `MEASURE_GREENLEE -get_measurement` | Ohm's law, I = V / R, with V 1–10 V and R 0.1–100 Ω |
| ENTES | 5002 | `MEASURE_ENTES -get_data` | Hall effect, I = B · K, with B 0.01–0.1 T and K 500–2000 |
| CIRCUTOR | 5003 | `MEASURE_CIRCUTOR -get_measurement -current` | Rogowski coil integration, I = ∫V dt, over 10 samples of 0.1–1.0 V, with a time step of 1–10 ms |

Each emulator answers one request per TCP connection and closes the connection without a reply when the command
doesn't match exactly. Port 5000 is avoided because macOS uses it for AirPlay Receiver.

## Project structure

```
main.py                     starts the emulators and reads each one once
Ammeters/                   the emulators (base_ammeter.py, *_Ammeter.py) and a simple client
config/config.yaml          all settings
src/
  __main__.py               command line (python -m src ...)
  testing/test_framework.py AmmeterTestFramework
  settings.py               loads and validates the config
  client.py                 AmmeterClient: one interface for every ammeter
  sampling.py               sampling plan and scheduler
  analysis.py               statistics, timing, checks, comparison
  results.py                results archive
  report.py, plots.py       reports and charts
  emulators.py, faults.py   running emulators, error simulation
  utils/                    config loading, logger, random helper
tools/calibrate_checks.py   derives the expected values and check limits by simulation
tests/                      the framework's own tests (helpers.py has shared test servers and data)
examples/run_tests.py       using the framework from Python
docs/                       FIXES.md, DESIGN.md
sample_results/             output of real runs
```
