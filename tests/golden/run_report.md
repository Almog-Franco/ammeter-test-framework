## high: PASS

Run `20261026T120000Z_entes_abc123`, 127.0.0.1:5002, started 2026-10-26T12:00:00+00:00
51 valid readings of 51 planned, 0 failed, 0 missed (their time slot had passed)

| Metric | Value |
|---|---|
| Mean | 74.87 A |
| Median | 68.94 A |
| Std deviation | 45.28 A |
| Min | 10.01 A |
| Max | 190 A |
| CV (std / mean) | 0.6049 |
| Geometric mean | 59.64 A |
| 95% CI of the mean | 62.42 to 87.15 A |
| Outliers (1.5 IQR rule) | 0 |

| Timing and stability | Value |
|---|---|
| Sampling rate | 8 Hz (requested 8 Hz), 51 of 51 readings taken |
| Interval jitter (std) | 0 ms |
| Max delay vs schedule | 0 ms |
| Response time mean / p95 / max | 1 / 1 / 1 ms |
| Drift over the run | +65.5 % (t = +2.38) |

| Check | Result | Detail |
|---|---|---|
| values_in_range | PASS | 0 of 51 outside [5, 200] A |
| error_rate | PASS | 0.0% failed (limit 5%) |
| sampling_rate | PASS | 51 of 51 planned readings taken, 8 Hz for 8 Hz requested (0.0% short, limit 10%) |
| not_stuck | PASS | longest run of identical readings: 1 (stuck from 3) |
| matches_model | PASS | geometric mean 59.64 A, model 50 A (z = +1.80, limit ±5) |
| no_drift | PASS | +65.5 % over the run (t = +2.38, limit ±5) |
