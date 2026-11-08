## entes: PASS

Run `20261026T163002Z_entes_e32e9c`, 127.0.0.1:5002, started 2026-10-26T16:30:02.404+00:00
400 valid readings of 400 planned, 0 failed, 0 missed (their time slot had passed)

| Metric | Value |
|---|---|
| Mean | 70.75 A |
| Median | 63.3 A |
| Std deviation | 41.56 A |
| Min | 5.503 A |
| Max | 182.3 A |
| CV (std / mean) | 0.5874 |
| Geometric mean | 57.4 A |
| 95% CI of the mean | 66.78 to 74.68 A |
| Outliers (1.5 IQR rule) | 0 |

| Timing and stability | Value |
|---|---|
| Sampling rate | 40 Hz (requested 40 Hz), 400 of 400 readings taken |
| Interval jitter (std) | 2.401 ms |
| Max delay vs schedule | 17.19 ms |
| Response time mean / p95 / max | 0.7124 / 0.9235 / 3.476 ms |
| Drift over the run | -14.2 % (t = -1.40) |

| Check | Result | Detail |
|---|---|---|
| values_in_range | PASS | 0 of 400 outside [5, 200] A |
| error_rate | PASS | 0.0% failed (limit 5%) |
| sampling_rate | PASS | 400 of 400 planned readings taken, 40 Hz for 40 Hz requested (0.0% short, limit 10%) |
| not_stuck | PASS | longest run of identical readings: 1 (stuck from 3) |
| matches_model | PASS | geometric mean 57.4 A, model 55.51 A (z = +0.95, limit ±5) |
| no_drift | PASS | -14.2 % over the run (t = -1.40, limit ±5) |
