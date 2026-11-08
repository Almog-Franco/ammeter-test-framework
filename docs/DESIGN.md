# Design decisions

## Overview

```
config.yaml ─► settings ─► AmmeterTestFramework.run_test("entes")
                              │
                              ├─ emulators   start missing emulators in a child process
                              ├─ client      one TCP request per reading, typed errors
                              ├─ sampling    one time slot per reading, run ends on time
                              ├─ analysis    statistics, timing, checks, verdict
                              ├─ results     results/runs/<run_id>/ + index.jsonl
                              └─ report, plots
```

| Module | Responsibility |
|---|---|
| `src/settings.py` | Loads `config.yaml` into dataclasses and validates it, reporting all errors at once |
| `src/client.py` | `AmmeterClient.measure()`, the same interface for every ammeter type |
| `src/sampling.py` | `SamplingPlan` (count / duration / frequency) and `Sampler` |
| `src/analysis.py` | Statistics, timing and drift, acceptance checks, verdict, comparison |
| `src/results.py` | The results archive: save, list, load |
| `src/report.py`, `src/plots.py` | Markdown reports (also used for the console) and charts |
| `src/emulators.py`, `src/faults.py` | Running the emulators, and error simulation |
| `src/testing/test_framework.py` | `AmmeterTestFramework`, which ties everything together |
| `src/__main__.py` | The command line |
| `tools/calibrate_checks.py` | Derives the expected values and check limits by simulation |

## The emulators are treated as devices

The framework talks to the emulators only over TCP, with their real protocol. It never calls `measure_current()`
directly, because that would skip the data-transfer link between ammeter and computer in the setup diagram, and
with it every error the framework is supposed to handle.

When the framework starts emulators itself, it starts them in a **separate process**. That is closer to a real
device, the framework can stop them cleanly, and their constant output goes to `results/logs/emulators.log` instead
of mixing with the report. Before starting an emulator the framework checks its port:

- a valid reading means it is already running (for example from `main.py`), so it is reused
- connection refused means it gets started
- anything else means another program owns the port, and the run stops with a clear error

A client that resets or drops its connection no longer stops an emulator (see `docs/FIXES.md`, fix 14).

## Configuration

`config.yaml` is the only place that has ports, commands, sampling and limits. It is checked before anything
starts, and every problem is listed with its key name, instead of failing on the first problem or on a `None`
somewhere in the middle of a run. The checks cover:

- **Structure:** every section must be `key: value` pairs. A list or a word where a section belongs is reported,
  not left to crash later.
- **Numbers:** they must be finite and in range, so `.inf` and `.nan` are rejected.
- **Switches:** they must be real `true`/`false`. The text `"false"` would otherwise count as on.
- **Field types:** ports, hosts, commands, emulator names and seeds.
- **Expected values:** min < max, the means lie between them, and `geo_mean` and `log_std` come as a pair.

A test sets every key of the shipped config to a list, a word, a number, a boolean, infinity, a section and null.
In every case it expects either a valid config or a `ConfigError`, never a crash.

The command line can override sampling, profile, fault injection, the emulator seed, plots and the results folder.
To add an ammeter, add an entry to `config.yaml`. For a new emulator type, also add its class to `EMULATORS` in
`src/emulators.py`. A real device is added with `emulator: null`, so the framework only connects to it.

Relative paths in the config are taken from the project folder, so a run gives the same result from any working
folder. Paths given on the command line (`--config`, `--results-dir`) are taken from the current folder, as usual
for command-line arguments.

## Sampling

- **Count, duration and frequency depend on each other** (count = duration × frequency), so the config sets any two
  and the third is calculated. If all three are given, they must agree.
- **One time slot per reading:** reading *i* belongs to `[start + i/f, start + (i+1)/f)`, measured with
  `time.perf_counter()`. It starts at the beginning of its slot, or right after the previous reading if that one ran
  late. Sleeping `1/f` after every reading would add each reading's own time on top, and the run would drift.
- **Missed slots and the deadline:**
  - If a reading takes so long that the next slots have already passed, those slots are **skipped and counted as
    missed**. They are not retried, so there are no catch-up bursts.
  - No reading starts after the planned duration. A reading that is still in progress may finish, but only within the
    client's timeout. So a run never takes longer than its duration plus one timeout.
  - Example: "1 s at 10 Hz" against an ammeter that needs 1 s per answer gives one reading and nine missed slots, and
    is done after 1 s.
- **Timing is measured, not assumed.** Every reading records when it started, how late it was within its slot and
  how long it took. The report shows the achieved rate, interval jitter, delay and response times, and the
  `sampling_rate` check fails when more than 10% of the planned readings didn't happen.
- **A failed reading is data, not a crash.** It is stored with its error type and the run continues. After 5
  failures in a row the device is clearly gone and the run stops (0 means never stop early). Ctrl-C stops the run but
  keeps and archives what was collected, as `INTERRUPTED`.

## Talking to the ammeter

`AmmeterClient.measure()` sends the command over a fresh TCP connection and reads until the ammeter closes it.

- **The timeout covers the whole reading:** connect, send, the complete answer and any retries. An ammeter that
  sends one byte at a time, or keeps dropping the connection, can't keep the client waiting beyond it.
- **Answers longer than 1024 bytes are rejected.** A reading is a short number.
- **Only plain decimal numbers count as readings,** such as `12.5`, `-3` or `1e-3`. Python's own `float()` would
  also accept `1_000`, `infinity` or `nan`, which no ammeter sends.
- **Typed errors:**
  - `AmmeterConnectionError`: nothing listening, the connection attempt timed out, or the connection was reset.
    Retried once by default, within the same timeout.
  - `AmmeterTimeoutError`: not retried, because a slow device stays slow.
  - `AmmeterResponseError`: empty, not a number, not finite, or too long.

## Statistics

- **Python's `statistics` module only.** Mean, median, sample standard deviation (n−1), min and max. Also CV,
  geometric mean, 95% confidence intervals of the mean and of the CV, quartiles and outliers.
- **Bootstrap confidence intervals:** 1000 resamples with a fixed seed, so a report is repeatable. Greenlee's readings
  have a long tail, and `mean ± 1.96·SE` gave an interval reaching below zero. A current can't be negative.
- **Outliers are counted, not removed.** For Greenlee they are real readings from the tail, and dropping them would
  bias the mean.

## What the emulators should produce

The emulators don't measure a shared current, and their ranges differ by about 1000×. What the README does give is
the physics and the input ranges of each emulator, and from those the possible range and the expected distribution
follow. These are the `expected` values in `config.yaml`:

| Ammeter | Formula | Inputs | Range | Mean | CV | Geometric mean | Std of log |
|---|---|---|---|---|---|---|---|
| Greenlee | I = V / R | V 1–10 V, R 0.1–100 Ω | 0.01–100 A | 0.3803 A | 4.96 | 0.1283 A | 1.139 |
| ENTES | I = B · K | B 0.01–0.1 T, K 500–2000 | 5–200 A | 68.75 A | 0.61 | 55.51 A | 0.701 |
| CIRCUTOR | I = Δt · ΣVᵢ | 10 × V 0.1–1 V, Δt 1–10 ms | 0.001–0.1 A | 0.03025 A | 0.50 | 0.02583 A | 0.607 |

- **The means follow on paper.** All inputs are uniform and independent, so E[V/R] = E[V]·E[1/R], with
  E[1/R] = ln(100/0.1)/(100 − 0.1).
- **Greenlee's long tail:** 1/R explodes near R = 0.1 Ω, so its mean is about three times its median and its CV is
  about 5.
- **The log-scale values are simulated.** They come from 4 million simulated readings per ammeter in
  `tools/calibrate_checks.py`, which simulates the README's physics independently of the emulator code.
- **The values are tested against the emulators.** `tests/test_emulators.py` checks every one of them against
  20,000 readings from each emulator.
- **The README's Rogowski formula is incomplete.** `I = ∫V dt` leaves out the coil constant: a Rogowski coil gives
  V = M·dI/dt, so I = (1/M)∫V dt. The emulator uses the formula as written, so its "current" is really in V·s. It is
  kept, because the goal is to test the existing emulators, not to correct them.

## Acceptance checks and verdict

Each run gets checks that come from the requirements and the physics, not from the data itself:

| Check | Fails when |
|---|---|
| `values_in_range` | Any reading is outside the physically possible range |
| `error_rate` | More than 5% of readings failed |
| `sampling_rate` | More than 10% of the planned readings didn't happen (missed slots) |
| `not_stuck` | The same reading comes 3 or more times in a row |
| `matches_model` | The mean of log(readings) is more than 5 standard errors from the model (needs 10 readings) |
| `no_drift` | The readings trend over the run: slope t-statistic ≥ 5, or an exact sloped line (needs 30 readings) |

A check without enough readings is reported as `SKIP`, never as a silent pass. The verdict is one of:
- `PASS`: every check passed
- `FAIL`: at least one check failed
- `ERROR`: there wasn't a single valid reading
- `INTERRUPTED`: the run was stopped with Ctrl-C

**Why `not_stuck` works here:** the emulators return random values with about 15 significant digits, so identical
readings in a row mean a frozen sensor. A real meter with coarse resolution would need a higher `stuck_after`.

**Why the model check uses logarithms:** Greenlee's readings span four decades, so a check on the plain mean would
raise false alarms. On a log scale all three ammeters are close to normal. The check catches readings that are stuck
or have a calibration error, even when they stay within the range.

### How the limits were chosen

`tools/calibrate_checks.py` simulated 200,000 clean runs per case. Most of the table below is "share of runs that
falsely failed"; the last two rows are detection rates:

| | Model check (\|z\| > 5) | Drift check (\|t\| ≥ 5) |
|---|---|---|
| False alarms, 10 readings | ≤ 4 in 100,000 | up to 1 in 1,000, so the check needs 30 readings |
| False alarms, 30 readings | ≤ 1 in 100,000 | ≤ 5 in 100,000 |
| False alarms, 50+ readings | ≤ 1 in 100,000 | ≤ 1 in 100,000 |
| Caught: ×0.5 calibration error, 50 readings | ENTES 98%, CIRCUTOR 100%, Greenlee 24% | - |
| Caught: exact straight line | - | always |

The checks have real limits, and the reports and docs say so:

- **A 20% calibration error can't be detected with 50 readings** (≤ 1%). The readings vary by 50–60% each, so the
  error hides in that spread. Catching it needs a few hundred readings.
- **A gradual drift buried in that spread is rarely caught.** For example, +100% over 50 readings is caught in 0–2% of
  runs. The drift check is meant for clear trends, like a sensor ramping or the exact line in the review.

## Comparing the ammeters

**What it can and can't say:**
- **It compares the emulators, not the methods.** Their spread comes from the random input ranges in their code,
  not from how good Ohm's law, the Hall effect or a Rogowski coil is as a measurement method.
- **Method accuracy needs a shared reference.** It would take every meter measuring the same known current (for
  example from a calibrated source) and comparing each reading against it. These emulators can't do that, because
  each one generates its own current.
- **So the claim is narrow:** which emulator gave the most repeatable readings while also behaving the way its own
  specification says.

**How it works** (all ammeter names are checked before any run starts, so a typo doesn't waste the others' runs):

1. **Only runs that passed every check, with at least 30 readings, take part.** The others are listed as "not
   ranked", with the reason. Range, errors, agreement with the model and drift are already pass/fail checks, so a
   failed run, or one with a single reading (whose CV is 0), can't win.
2. **The rest are ranked by precision: the CV, with its bootstrap 95% interval.** CV is relative, so ranges 1000×
   apart compare fairly.
3. **A winner is named only if its CV interval doesn't overlap any other run's.** Otherwise the result is
   *insufficient evidence*, with the names of the runs that are tied. The same happens with fewer than two runs that
   qualify.

The physics predicts CIRCUTOR (CV 0.50) ahead of ENTES (0.61), with Greenlee (≈5) far behind. How many readings it
takes to show that, from 20 simulated comparisons each:

| Readings per ammeter | 50 | 200 | 400 | 800 |
|---|---|---|---|---|
| CIRCUTOR named the winner | 2 of 20 | 11 of 20 | 19 of 20 | 20 of 20 |
| Wrong winner | 0 | 0 | 0 | 0 |

With the default 50 readings the honest result is usually "CIRCUTOR and ENTES are tied, Greenlee is clearly less
precise". `sample_results/` has a 400-reading run where CIRCUTOR wins clearly.

## Results archive

```
results/
  index.jsonl                      one line per run, for listing and filtering
  runs/<run_id>/run.json           settings, config, statistics, timing, checks, verdict
  runs/<run_id>/samples.csv        every reading: slot, time, delay, response time, value or error
  runs/<run_id>/report.md
  runs/<run_id>/plots/*.png
  comparisons/<id>/comparison.{md,json,png}
  logs/<time>_<ammeter>_<id>.log, logs/emulators.log
```

- **Run IDs** look like `20261026T120623Z_greenlee_d05946`: UTC time, ammeter and a random part. They are unique and
  sort by time.
- **What `run.json` stores:**
  - `settings`: the **effective** settings after command-line overrides, including timeouts, retries, every
    acceptance limit, the profile and the seeds
  - `config.content`: the **full content** of the config file, plus its path and SHA-256
  - timestamps, and the Python and OS versions

  A run can be traced and repeated even after the config file has changed.
- **Writes can't be half done:** files are written to a temporary name and then renamed, and the index line is
  added only after the run's files exist.
- **Retrieval:** `ResultStore.list_runs/load/load_samples/latest`, `AmmeterTestFramework.compare_runs`, and the
  `list`, `show`, `compare` and `history` commands.
- **Bad input to the archive gives a clear `ArchiveError`, not a traceback:**
  - A run id must be letters, digits, `_` and `-`, so `show ../../x` can't read files outside the archive.
  - A damaged `run.json` or `samples.csv` is reported as damaged.
  - Index lines that aren't complete entries are skipped.

### Repeating a run exactly

`--seed N` (or `testing.emulator_seed`) seeds the emulators' readings.

- **Why the framework does the seeding:** the emulators use Python's shared random generator and reseed it with the
  clock whenever one is created. So the framework seeds it in the emulator process after creating them and before the
  first reading, without changing the emulator code.
- **Limits:**
  - **Same command, same readings.** All emulators in the process draw from the one generator, in the order the runs
    happen. Running `entes` alone gives different readings than `entes` as part of all three.
  - **Only emulators the framework starts can be seeded.** An already-running one is reused unseeded, with a warning.
  - **The timing isn't repeated, just the readings.** With a slow device, the number of missed slots can differ
    between runs.

## Error simulation

`FaultyAmmeter` wraps any emulator and breaks some of its answers at configured, seeded rates:

| Fault | What the emulator does | Expected detection |
|---|---|---|
| `timeout` | Answers after the client gave up | `AmmeterTimeoutError`, missed slots |
| `no_response` | Sends nothing back | `AmmeterResponseError` (empty response) |
| `garbage` | Sends text that is not a number | `AmmeterResponseError` |
| `spike` | Sends a reading a million times too big | `values_in_range` (and usually `matches_model`) |
| `stuck` | Repeats one reading for the next 5 requests | `not_stuck` |

It only overrides `measure_current()`, so the emulators themselves stay unchanged. In the sample results all 15
injected faults were detected (see `sample_results/README.md`).

## Cross-platform

- `pathlib` paths, and UTF-8 for every file the framework writes or reads.
- `127.0.0.1` instead of `localhost`. On Windows, `localhost` may be tried as IPv6 first, which can add about a
  second per connection.
- The emulator process gets UTF-8 output. Greenlee prints `Ω`, which crashes its thread on Windows when output is
  redirected.
- **A refused connection is slow on Windows.** Connecting to a port nothing listens on fails at once on macOS and
  Linux, but Windows retries for about 2 s first. So a connection attempt that times out counts as "cannot reach",
  not as a slow answer. And before starting its emulators, the framework checks each port with a quick 0.2 s
  connection test, instead of asking for a reading and waiting for the refusal. The tests check this on every
  platform with a fixture (`windows_loopback`) that makes refusals as slow as on Windows.
- `SO_REUSEADDR` only outside Windows. The tests' connection reset uses the Windows layout of `SO_LINGER` there.
- matplotlib's `Agg` backend, so no display is needed.
- The logger closes its file so Windows can delete it.

## Tests of the framework itself

`pytest` runs 65 tests (163 cases, counting each parameter) in about 35 seconds, or about 13 seconds with
`pytest -n auto`. Each test checks one behaviour that can be named in a sentence:

- **Unit tests** need no network and no real waiting.
  - The sampler runs on a fake clock, so timing tests are exact.
  - A property test runs over random latencies: one reading per slot, no reading outside its slot, and a slot is
    only skipped when it really had passed.
- **Contract tests** run the same checks against every configured ammeter, on emulators started on free ports.
- **Reference tests** check the expected values in the config against 20,000 readings from each emulator.
- **Robustness tests** use scripted TCP servers:
  - slow, dribbling and endless ammeters
  - connection resets on both sides, with recovery
  - exact retry counts, and a check that sockets are closed
  - an emulator that keeps working after a client reset, but stops on its own bugs
- **Config tests** set every key to every wrong type, and expect a `ConfigError` rather than a crash.
- **Fault tests** check that each injected fault is detected as the right error.
- **A golden-file test** compares the full run and comparison reports, word for word, with copies saved in
  `tests/golden/`. After an intended change to a report, `UPDATE_GOLDEN=1 pytest tests/test_report.py` saves new
  copies.
- **End-to-end tests** cover:
  - `run_test()` and its archive, including the effective settings
  - `run_all()` and the command line
  - fault-injected and stuck runs, a slow ammeter that can't stretch the run, and seeded runs that repeat exactly
  - settings from the config reaching the run
  - an unreachable ammeter and ports taken by other programs
  - `main.py`, both normally and on a simulated legacy Windows console (cp1252)

Random behaviour is seeded wherever a test depends on it, and tolerances are wide enough for the rest, so the suite
gives the same result every run.

## Dependencies

- PyYAML for the config.
- matplotlib for the charts. It is optional: without it the charts are skipped with a warning.
- pytest for the tests.
- numpy for `tools/calibrate_checks.py` only. It comes with matplotlib.

Everything else is the standard library.

## Limitations

- A reading needs a new TCP connection, as the emulator protocol requires. That puts the practical sampling limit at
  a few hundred Hz on one machine.
- When the framework reuses an emulator that is already running (for example started by `main.py`), it can't inject
  faults into it or seed it, and logs a warning.
- Small calibration errors and gradual drifts can't be told from the emulators' large random spread with tens of
  readings (see the detection table). More readings help: the needed count grows with the square of the spread
  divided by the error.
- The comparison ranks emulator behaviour, not measurement-method accuracy (see above).
