## greenlee: PASS

Run `20261026T162931Z_greenlee_287086`, 127.0.0.1:5001, started 2026-10-26T16:29:31.312+00:00
50 valid readings of 50 planned, 0 failed, 0 missed (their time slot had passed)

| Metric | Value |
|---|---|
| Mean | 1.041 A |
| Median | 0.1183 A |
| Std deviation | 4.062 A |
| Min | 0.01977 A |
| Max | 25.32 A |
| CV (std / mean) | 3.903 |
| Geometric mean | 0.1535 A |
| 95% CI of the mean | 0.203 to 2.365 A |
| Outliers (1.5 IQR rule) | 6 |

| Timing and stability | Value |
|---|---|
| Sampling rate | 10 Hz (requested 10 Hz), 50 of 50 readings taken |
| Interval jitter (std) | 2.144 ms |
| Max delay vs schedule | 5.044 ms |
| Response time mean / p95 / max | 0.7833 / 0.9839 / 1.073 ms |
| Drift over the run | -99.1 % (t = -0.52) |

| Check | Result | Detail |
|---|---|---|
| values_in_range | PASS | 0 of 50 outside [0.01, 100] A |
| error_rate | PASS | 0.0% failed (limit 5%) |
| sampling_rate | PASS | 50 of 50 planned readings taken, 10 Hz for 10 Hz requested (0.0% short, limit 10%) |
| not_stuck | PASS | longest run of identical readings: 1 (stuck from 3) |
| matches_model | PASS | geometric mean 0.1535 A, model 0.1283 A (z = +1.11, limit ±5) |
| no_drift | PASS | -99.1 % over the run (t = -0.52, limit ±5) |
