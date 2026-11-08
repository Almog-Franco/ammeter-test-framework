## entes: FAIL

Run `20261026T163029Z_entes_754b94`, 127.0.0.1:5002, started 2026-10-26T16:30:29.965+00:00
31 valid readings of 50 planned, 1 failed, 18 missed (their time slot had passed)

| Metric | Value |
|---|---|
| Mean | 4.907e+06 A |
| Median | 58.12 A |
| Std deviation | 1.91e+07 A |
| Min | 6.002 A |
| Max | 8.391e+07 A |
| CV (std / mean) | 3.893 |
| Geometric mean | 122.6 A |
| 95% CI of the mean | 56.47 to 1.252e+07 A |
| Outliers (1.5 IQR rule) | 2 |

| Timing and stability | Value |
|---|---|
| Sampling rate | 6.4 Hz (requested 10 Hz), 32 of 50 readings taken |
| Interval jitter (std) | 2.575 ms |
| Max delay vs schedule | 5.042 ms |
| Response time mean / p95 / max | 63.34 / 1.22 / 2002 ms |
| Drift over the run | -6.18 % (t = -0.03) |

| Check | Result | Detail |
|---|---|---|
| values_in_range | FAIL | 2 of 31 outside [5, 200] A |
| error_rate | PASS | 3.1% failed (limit 5%) |
| sampling_rate | FAIL | 32 of 50 planned readings taken, 6.4 Hz for 10 Hz requested (36.0% short, limit 10%) |
| not_stuck | FAIL | longest run of identical readings: 5 (stuck from 3) |
| matches_model | FAIL | geometric mean 122.6 A, model 55.51 A (z = +6.29, limit ±5) |
| no_drift | PASS | -6.18 % over the run (t = -0.03, limit ±5) |

Errors: AmmeterTimeoutError x1

Fault injection was on: {'rates': {'timeout': 0.02, 'no_response': 0.04, 'garbage': 0.04, 'spike': 0.04, 'stuck': 0.02}, 'seed': 7, 'delay_s': 3.0}
