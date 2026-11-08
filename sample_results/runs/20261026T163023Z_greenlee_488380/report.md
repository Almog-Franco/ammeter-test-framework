## greenlee: FAIL

Run `20261026T163023Z_greenlee_488380`, 127.0.0.1:5001, started 2026-10-26T16:30:23.060+00:00
38 valid readings of 50 planned, 7 failed, 5 missed (their time slot had passed)

| Metric | Value |
|---|---|
| Mean | 852.5 A |
| Median | 0.1238 A |
| Std deviation | 5249 A |
| Min | 0.01977 A |
| Max | 3.236e+04 A |
| CV (std / mean) | 6.157 |
| Geometric mean | 0.2205 A |
| 95% CI of the mean | 0.2332 to 2556 A |
| Outliers (1.5 IQR rule) | 6 |

| Timing and stability | Value |
|---|---|
| Sampling rate | 9 Hz (requested 10 Hz), 45 of 50 readings taken |
| Interval jitter (std) | 2.17 ms |
| Max delay vs schedule | 5.039 ms |
| Response time mean / p95 / max | 45.28 / 1.006 / 2001 ms |
| Drift over the run | -341 % (t = -1.03) |

| Check | Result | Detail |
|---|---|---|
| values_in_range | FAIL | 1 of 38 outside [0.01, 100] A |
| error_rate | FAIL | 15.6% failed (limit 5%) |
| sampling_rate | PASS | 45 of 50 planned readings taken, 9 Hz for 10 Hz requested (10.0% short, limit 10%) |
| not_stuck | PASS | longest run of identical readings: 1 (stuck from 3) |
| matches_model | PASS | geometric mean 0.2205 A, model 0.1283 A (z = +2.93, limit ±5) |
| no_drift | PASS | -341 % over the run (t = -1.03, limit ±5) |

Errors: AmmeterResponseError x6, AmmeterTimeoutError x1

Fault injection was on: {'rates': {'timeout': 0.02, 'no_response': 0.04, 'garbage': 0.04, 'spike': 0.04, 'stuck': 0.02}, 'seed': 7, 'delay_s': 3.0}
