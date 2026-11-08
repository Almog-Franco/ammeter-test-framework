## circutor: FAIL

Run `20261026T163035Z_circutor_3eecbe`, 127.0.0.1:5003, started 2026-10-26T16:30:35.301+00:00
15 valid readings of 50 planned, 3 failed, 32 missed (their time slot had passed)

| Metric | Value |
|---|---|
| Mean | 0.02327 A |
| Median | 0.02001 A |
| Std deviation | 0.01476 A |
| Min | 0.007367 A |
| Max | 0.05594 A |
| CV (std / mean) | 0.6342 |
| Geometric mean | 0.01957 A |
| 95% CI of the mean | 0.01692 to 0.03088 A |
| Outliers (1.5 IQR rule) | 1 |

| Timing and stability | Value |
|---|---|
| Sampling rate | 3.6 Hz (requested 10 Hz), 18 of 50 readings taken |
| Interval jitter (std) | 2.767 ms |
| Max delay vs schedule | 10.07 ms |
| Response time mean / p95 / max | 278.8 / 2002 / 2002 ms |
| Drift over the run | -36.2 % (t = -0.70) |

| Check | Result | Detail |
|---|---|---|
| values_in_range | PASS | 0 of 15 outside [0.001, 0.1] A |
| error_rate | FAIL | 16.7% failed (limit 5%) |
| sampling_rate | FAIL | 18 of 50 planned readings taken, 3.6 Hz for 10 Hz requested (64.0% short, limit 10%) |
| not_stuck | PASS | longest run of identical readings: 1 (stuck from 3) |
| matches_model | PASS | geometric mean 0.01957 A, model 0.02583 A (z = -1.77, limit ±5) |
| no_drift | SKIP | skipped: needs at least 30 readings |

Errors: AmmeterResponseError x1, AmmeterTimeoutError x2

Fault injection was on: {'rates': {'timeout': 0.02, 'no_response': 0.04, 'garbage': 0.04, 'spike': 0.04, 'stuck': 0.02}, 'seed': 7, 'delay_s': 3.0}
