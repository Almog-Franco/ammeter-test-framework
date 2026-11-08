## greenlee: PASS

Run `20261026T162951Z_greenlee_0a0fae`, 127.0.0.1:5001, started 2026-10-26T16:29:51.861+00:00
400 valid readings of 400 planned, 0 failed, 0 missed (their time slot had passed)

| Metric | Value |
|---|---|
| Mean | 0.4908 A |
| Median | 0.1084 A |
| Std deviation | 2.254 A |
| Min | 0.01393 A |
| Max | 31.21 A |
| CV (std / mean) | 4.594 |
| Geometric mean | 0.1324 A |
| 95% CI of the mean | 0.2956 to 0.7321 A |
| Outliers (1.5 IQR rule) | 51 |

| Timing and stability | Value |
|---|---|
| Sampling rate | 40 Hz (requested 40 Hz), 400 of 400 readings taken |
| Interval jitter (std) | 2.017 ms |
| Max delay vs schedule | 5.057 ms |
| Response time mean / p95 / max | 0.6927 / 0.9265 / 1.248 ms |
| Drift over the run | -80.3 % (t = -1.01) |

| Check | Result | Detail |
|---|---|---|
| values_in_range | PASS | 0 of 400 outside [0.01, 100] A |
| error_rate | PASS | 0.0% failed (limit 5%) |
| sampling_rate | PASS | 400 of 400 planned readings taken, 40 Hz for 40 Hz requested (0.0% short, limit 10%) |
| not_stuck | PASS | longest run of identical readings: 1 (stuck from 3) |
| matches_model | PASS | geometric mean 0.1324 A, model 0.1283 A (z = +0.56, limit ±5) |
| no_drift | PASS | -80.3 % over the run (t = -1.01, limit ±5) |
