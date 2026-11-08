## circutor: PASS

Run `20261026T162941Z_circutor_03d057`, 127.0.0.1:5003, started 2026-10-26T16:29:41.741+00:00
50 valid readings of 50 planned, 0 failed, 0 missed (their time slot had passed)

| Metric | Value |
|---|---|
| Mean | 0.03317 A |
| Median | 0.03514 A |
| Std deviation | 0.01576 A |
| Min | 0.004789 A |
| Max | 0.05914 A |
| CV (std / mean) | 0.4751 |
| Geometric mean | 0.02794 A |
| 95% CI of the mean | 0.02882 to 0.03752 A |
| Outliers (1.5 IQR rule) | 0 |

| Timing and stability | Value |
|---|---|
| Sampling rate | 10 Hz (requested 10 Hz), 50 of 50 readings taken |
| Interval jitter (std) | 2.427 ms |
| Max delay vs schedule | 5.036 ms |
| Response time mean / p95 / max | 0.8185 / 1.19 / 1.374 ms |
| Drift over the run | -12.1 % (t = -0.53) |

| Check | Result | Detail |
|---|---|---|
| values_in_range | PASS | 0 of 50 outside [0.001, 0.1] A |
| error_rate | PASS | 0.0% failed (limit 5%) |
| sampling_rate | PASS | 50 of 50 planned readings taken, 10 Hz for 10 Hz requested (0.0% short, limit 10%) |
| not_stuck | PASS | longest run of identical readings: 1 (stuck from 3) |
| matches_model | PASS | geometric mean 0.02794 A, model 0.02583 A (z = +0.91, limit ±5) |
| no_drift | PASS | -12.1 % over the run (t = -0.53, limit ±5) |
