## entes: PASS

Run `20261026T162936Z_entes_c8d7a8`, 127.0.0.1:5002, started 2026-10-26T16:29:36.718+00:00
50 valid readings of 50 planned, 0 failed, 0 missed (their time slot had passed)

| Metric | Value |
|---|---|
| Mean | 60.12 A |
| Median | 46.12 A |
| Std deviation | 42.11 A |
| Min | 6.002 A |
| Max | 176.1 A |
| CV (std / mean) | 0.7004 |
| Geometric mean | 46.82 A |
| 95% CI of the mean | 48.76 to 72.97 A |
| Outliers (1.5 IQR rule) | 5 |

| Timing and stability | Value |
|---|---|
| Sampling rate | 10 Hz (requested 10 Hz), 50 of 50 readings taken |
| Interval jitter (std) | 2.011 ms |
| Max delay vs schedule | 5.049 ms |
| Response time mean / p95 / max | 0.7972 / 1.023 / 2.34 ms |
| Drift over the run | +31 % (t = +0.92) |

| Check | Result | Detail |
|---|---|---|
| values_in_range | PASS | 0 of 50 outside [5, 200] A |
| error_rate | PASS | 0.0% failed (limit 5%) |
| sampling_rate | PASS | 50 of 50 planned readings taken, 10 Hz for 10 Hz requested (0.0% short, limit 10%) |
| not_stuck | PASS | longest run of identical readings: 1 (stuck from 3) |
| matches_model | PASS | geometric mean 46.82 A, model 55.51 A (z = -1.72, limit ±5) |
| no_drift | PASS | +31 % over the run (t = +0.92, limit ±5) |
