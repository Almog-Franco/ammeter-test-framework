## circutor: PASS

Run `20261026T163012Z_circutor_c4b89d`, 127.0.0.1:5003, started 2026-10-26T16:30:12.562+00:00
400 valid readings of 400 planned, 0 failed, 0 missed (their time slot had passed)

| Metric | Value |
|---|---|
| Mean | 0.02996 A |
| Median | 0.02942 A |
| Std deviation | 0.01537 A |
| Min | 0.005438 A |
| Max | 0.07032 A |
| CV (std / mean) | 0.5129 |
| Geometric mean | 0.02527 A |
| 95% CI of the mean | 0.0284 to 0.03137 A |
| Outliers (1.5 IQR rule) | 0 |

| Timing and stability | Value |
|---|---|
| Sampling rate | 40 Hz (requested 40 Hz), 400 of 400 readings taken |
| Interval jitter (std) | 2.236 ms |
| Max delay vs schedule | 5.041 ms |
| Response time mean / p95 / max | 0.7852 / 1.001 / 2.272 ms |
| Drift over the run | -4.55 % (t = -0.51) |

| Check | Result | Detail |
|---|---|---|
| values_in_range | PASS | 0 of 400 outside [0.001, 0.1] A |
| error_rate | PASS | 0.0% failed (limit 5%) |
| sampling_rate | PASS | 400 of 400 planned readings taken, 40 Hz for 40 Hz requested (0.0% short, limit 10%) |
| not_stuck | PASS | longest run of identical readings: 1 (stuck from 3) |
| matches_model | PASS | geometric mean 0.02527 A, model 0.02583 A (z = -0.72, limit ±5) |
| no_drift | PASS | -4.55 % over the run (t = -0.51, limit ±5) |
