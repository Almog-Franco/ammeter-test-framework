# Changes to the original code

Every change to the original code this framework builds on, with the problem it fixes and how it was checked.
Files that were **not** changed: the three emulators (`Greenlee_Ammeter.py`, `Entes_Ammeter.py`,
`Circutor_Ammeter.py`) and `src/utils/Utils.py`.

The original files use Windows (CRLF) line endings. The edited ones keep them, so a diff shows only real changes.

| # | File | Problem | Fix |
|---|---|---|---|
| 1 | `main.py` | Sent shortened commands, got no data | Commands and ports come from `config.yaml` |
| 2 | `Ammeters/base_ammeter.py` | Restarting right away fails silently | `SO_REUSEADDR` (not on Windows) |
| 3 | `Ammeters/client.py` | Printed the reading but returned nothing, no timeout | Returns the reading, has a timeout |
| 4 | README / config | CIRCUTOR command didn't match the emulator | Docs and config use the emulator's command |
| 5 | README / `main.py` | Three different port maps, 5000 is taken on macOS | One port map in `config.yaml`: 5001-5003 |
| 6 | `config/config.yaml` | Empty values, ammeters commented out | Filled in, validated at startup |
| 7 | `src/testing/test_framework.py` | Could not even be imported | Implemented |
| 8 | `src/utils/logger.py` | Never wrote anything | Writes a log file per run |
| 9 | `src/utils/config.py` | Encoding depended on the OS | Always UTF-8 |
| 10 | `examples/run_tests.py` | Called `run_test()` wrongly, printed nothing | Rewritten as a working example |
| 11 | `README.md` | Wrong file names, ports and command | Rewritten |
| 12 | `requirements.txt` | Four unused heavy libraries | Only PyYAML and matplotlib |
| 13 | packages | No `__init__.py` files | Added |
| 14 | `Ammeters/base_ammeter.py` | One client resetting its connection stopped the emulator for good | Connection errors are handled per connection |

## 1. `main.py` sent shortened commands

The three requests sent `b'MEASURE_GREENLEE'`, `b'MEASURE_ENTES'` and `b'MEASURE_CIRCUTOR'`. The emulator only
answers when the command matches exactly (`data == self.get_current_command`), and otherwise just closes the
connection. So uncommenting the lines printed `No data received.` three times, with no error.

`main.py` now reads every ammeter's port and command from `config/config.yaml`, starts the emulators in threads as
before, waits until each port accepts connections (instead of a fixed `sleep(5)`) and requests one reading from each.
An optional argument selects another config file: `python main.py my_config.yaml`.

The comment *"if you have problem restarting the servers between runs try increasing sleep time"* was misleading:
that sleep runs before the requests, not between runs. The restart problem is fix 2.

Verified: before, `No data received.` x3. After, three readings, also when run twice in a row (checked by hand).
`tests/test_end_to_end.py::test_main_py_gets_a_reading_from_every_ammeter` runs it on free ports.

## 2. Emulators could not be restarted right away

The server closes every connection after answering, so the operating system keeps those connections in `TIME_WAIT`
for a while. Starting the emulators again during that time fails in `bind()` with *Address already in use*. The
error happens inside a daemon thread, so nothing is shown: the emulator is simply not there and every request is
refused. Reproduced by running a request twice in a row: the second run got `ConnectionRefusedError`.

Fix: `SO_REUSEADDR` before `bind()`. It is skipped on Windows, where it isn't needed for this and means something
else (it lets a second program bind a port that is already in use).

## 3. `request_current_from_ammeter()` returned nothing

It printed the reading and returned `None`, so no caller could use the value, and it had no timeout, so an ammeter
that never answers blocked it forever. It now returns the reading as a `float` (`None` when nothing came back) and
takes a `timeout` (default 5 s). The existing calls still work unchanged.

## 4. CIRCUTOR command

`Circutor_Ammeter.py` expects `MEASURE_CIRCUTOR -get_measurement -current`. The README and the commented-out config
said `MEASURE_CIRCUTOR -get_measurement`, which gets an empty reply.

I changed the docs and config, not the emulator. The emulator plays the role of the device, and a test setup has to
use the device's real protocol. The compiled files left in `Ammeters/__pycache__` (from November 2024) show the
emulator has always used `-current`, so the docs were what was out of date.
`tests/test_emulators.py` checks both commands.

## 5. Ports

| Ammeter | README | `main.py` | old `config.yaml` | now (`config.yaml`) |
|---|---|---|---|---|
| Greenlee | 5000 | 5001 | 5000 | 5001 |
| ENTES | 5001 | 5002 | 5001 | 5002 |
| CIRCUTOR | 5002 | 5003 | 5002 | 5003 |

The maps are shifted by one, so mixing them sends each command to the wrong emulator, which again fails silently.
Port 5000 is also used by macOS for AirPlay Receiver (`lsof` shows `ControlCenter` listening on it), so the README's
map can't work on a Mac.

Now `config.yaml` is the only place with ports, using 5001-5003. The framework checks each port before starting an
emulator. If something else answers there, it stops with a clear message, and mentions AirPlay for port 5000 on macOS.

## 6. `config/config.yaml`

The sampling values were `NULL`, the ammeters were commented out, and `statistical_metrics`, `plot_types` and
`result_management` were empty. It now has all sections filled in, plus sampling profiles, acceptance limits,
expected ranges and fault injection. The file is checked when it's loaded (`src/settings.py`), and all problems are
reported together with their key names, for example:

```
invalid configuration in config/config.yaml:
  - ammeters.entes.port 5001 is already used by greenlee
  - sampling: set at least two of measurements_count, total_duration_seconds, sampling_frequency_hz
```

## 7. `src/testing/test_framework.py`

`run_test()` was declared `-> Dict` but `Dict` was never imported, so importing the module raised `NameError`.
The method was empty, and the relative import (`from ..utils.config`) only worked by accident (see 13).

Implemented with the same constructor (`config_path="config/config.yaml"`), the same
`run_test(ammeter_type: str) -> Dict` signature, and `self.config` still holding the loaded config.
`run_all()` and `compare_runs()` were added. Before starting its own emulators, it checks each port with a quick
connection test, because on Windows a refused connection only fails after about 2 s.

## 8. `src/utils/logger.py`

It built a log file name but never added a handler or set a level. INFO messages went nowhere (Python's default
level is WARNING) and no file was ever written. Checked: `handlers: []`, `level: 30`, empty `results/logs/`.

Now it writes everything to the log file (UTF-8) and prints only errors to the console, so it doesn't clutter the
report. Handlers are added once even if the same name is used again, and `close()` releases the file (Windows can't
delete open files). There is a `log_dir` argument, which defaults to the original `results/logs`.
`__test__ = False` stops pytest from trying to collect the class because its name starts with `Test`.
The original Hebrew comments are kept. They now describe what the code does.

## 9. `src/utils/config.py`

`open()` without an encoding uses the OS default: cp1252 or cp1255 on Windows, UTF-8 elsewhere. It now always reads
UTF-8.

## 10. `examples/run_tests.py`

The README said not to use it. It called `run_test()` without the ammeter type, so it would have run the same thing
three times, and it printed nothing. It is rewritten as a short working example, and it now runs from any folder.

## 11. `README.md`

Fixed wrong paths (`Ammeters/main.py` is in the root, `src/testing/AmmeterTester.py` is
`src/testing/test_framework.py`, `examples/run_test.py` is `examples/run_tests.py`), the ports and the CIRCUTOR
command. Added usage of the framework.

## 12. `requirements.txt`

numpy, scipy, pandas and seaborn were listed but aren't needed: the statistics use Python's `statistics` module.
Dependencies are kept minimal: it now lists only PyYAML and matplotlib, and matplotlib is optional (charts
are skipped without it). pytest is in `requirements-dev.txt`.

## 13. Package files

Added empty `__init__.py` files to `Ammeters/`, `src/`, `src/utils/` and `src/testing/`. Without them the packages
only worked as implicit namespace packages, which breaks relative imports in some setups.

## 14. A connection reset stopped the emulator for good

The server loop had no error handling. When a client dropped its connection with a TCP reset (RST), the server's
`recv()` or `sendall()` raised `ConnectionResetError`. The exception ended the server thread, and every later request
was refused.

Clients send a reset in ordinary situations: a crashed client, a closed socket with unread data on Windows, a
network glitch.

Reproduced with one client that connected and reset. The emulator thread died with
`ConnectionResetError: [Errno 54] Connection reset by peer`. My first check of this only tried a normal close, which
the emulator survives, so it missed the problem.

Fix: the accept-and-answer part of the loop catches `ConnectionError` (resets, aborts, broken pipes), prints it and
waits for the next client. Other errors still stop the server, so real faults aren't hidden.
`tests/test_emulators.py::test_emulator_survives_clients_that_reset_the_connection` resets before and after sending
the command, for every emulator, and then reads a value.

## Left as they are

- `base_ammeter.py` reseeds Python's shared random generator with the time for every emulator
  (`random.seed(time.time())`). To still allow repeatable readings (`--seed`), the framework seeds the generator in the
  emulator process after creating the emulators, instead of changing this line. See "Repeating a run exactly" in
  `docs/DESIGN.md` for the limits of that.
- An emulator answers an unknown command by closing the connection silently. That is the device's behaviour, so it is
  kept. The framework reports it as an *empty response* error.
- `Greenlee_Ammeter.py` prints `Ω`. On Windows, printing it crashes the emulator thread with `UnicodeEncodeError` when
  output is redirected (cp1252/cp1255). Instead of changing the emulator, the framework gives the emulator process
  UTF-8 output, and `main.py` replaces characters the console can't show.
- The README gives the Rogowski coil formula as `I = ∫V dt`. Physically it is `I = (1/M) ∫V dt`, where M is the coil's
  mutual inductance. As written the unit is V·s, not A. The emulator is unchanged, but see `docs/DESIGN.md`.
