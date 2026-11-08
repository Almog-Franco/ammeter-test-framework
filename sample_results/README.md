# Sample results

Three real sessions on macOS, Python 3.12. All used the shipped `config/config.yaml` and `--seed 1`, so the readings
can be reproduced:

```sh
python -m src --results-dir sample_results run --seed 1                            # 50 readings at 10 Hz
python -m src --results-dir sample_results run --seed 1 --count 400 --frequency 40 # long run
python -m src --results-dir sample_results run --seed 1 --faults                   # with error simulation
python -m src --results-dir sample_results history entes                           # history_entes.png
```

## 1. Normal run, 50 readings: all PASS, no single winner

| Ammeter | Mean | Median | CV (95% CI) | Geometric mean vs model |
|---|---|---|---|---|
| CIRCUTOR | 0.03317 A | 0.03514 A | 0.475 (0.367 – 0.576) | +8.2% |
| ENTES | 60.12 A | 46.12 A | 0.700 (0.566 – 0.811) | −15.7% |
| Greenlee | 1.041 A | 0.1183 A | 3.90 (1.66 – 5.11) | +19.6% |

- **Every reading was taken on schedule.** That's 50 of 50 per ammeter, and all six checks passed.
- **The comparison names no winner.** CIRCUTOR's and ENTES's CV intervals overlap, so the result is "insufficient
  evidence". Greenlee is clearly less precise.
- **The model deviations are within the noise of 50 readings.** ENTES's −15.7% is z = −1.7, against a limit of ±5.

Comparison: `comparisons/20261026T162946Z_f6b1cc/`.

## 2. Long run, 400 readings at 40 Hz: CIRCUTOR wins clearly

| Ammeter | CV (95% CI) | Geometric mean vs model |
|---|---|---|
| CIRCUTOR | 0.513 (0.481 – 0.545) | −2.2% |
| ENTES | 0.587 (0.551 – 0.622) | +3.4% |
| Greenlee | 4.59 (2.51 – 5.30) | +3.2% |

- **CIRCUTOR wins clearly.** With 400 readings its interval no longer overlaps ENTES's, which matches the CVs its
  input ranges predict (0.50 and 0.61). See the comparison in `comparisons/20261026T163022Z_ed549c/`.
- **This ranks the emulators, not the methods.** It doesn't mean Rogowski coils measure more accurately than Hall
  sensors.

## 3. Fault-injected run: all FAIL, every fault detected

The emulator log (`logs/emulators.log`) shows 15 injected faults: 4 timeouts, 4 no-response, 3 garbage, 3 spikes and
1 stuck. All 15 were detected:

| Ammeter | Failed readings | Missed slots | Failed checks |
|---|---|---|---|
| Greenlee | 7 (6 bad responses, 1 timeout) | 5 | range (1 spike), error rate |
| ENTES | 1 (timeout) | 18 | range (2 spikes), sampling rate, **not_stuck** (5 identical readings), matches_model |
| CIRCUTOR | 3 (1 bad response, 2 timeouts) | 32 | error rate, sampling rate (`no_drift` skipped: only 15 readings) |

- **A timeout stalls the emulator for 3 s.** The slots it covers are skipped and counted as missed, instead of
  stretching the run or firing a burst afterwards. See `runs/20261026T163035Z_circutor_3eecbe/plots/timeseries.png`.
- **There is no winner,** because no run passed. See `comparisons/20261026T163041Z_cdaf78/`.
