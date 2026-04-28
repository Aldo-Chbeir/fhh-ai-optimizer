# Model validation — v0.1.0

_Generated: 2026-04-28T12:00:29Z_

- **Data window**: 2025-04-25T00:00:00+00:00 → 2026-04-24T23:55:00+00:00
- **Train / holdout split**: 2026-02-10T23:56:00+00:00
- **Holdout rows**: 7,008
- **Overall calibrated MAE**: 5.83
- **Evaluation time**: 272.97s

## Classification metrics

| Threshold | TP | FP | TN | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|
| 60.0 | 114 | 10 | 6544 | 340 | 0.919 | 0.251 | 0.394 |
| 85.0 | 23 | 9 | 6814 | 162 | 0.719 | 0.124 | 0.212 |

## Calibration buckets (predicted vs actual)

| Score bucket | n | Mean predicted | Actual ≥60 rate |
|---|---|---|---|
| 0-29 | 6234 | 1.7000000476837158 | 0.004812319538017324 |
| 30-59 | 650 | 46.52000045776367 | 0.47692307692307695 |
| 60-84 | 92 | 76.44000244140625 | 0.8913043478260869 |
| 85-100 | 32 | 88.56999969482422 | 1.0 |

## Top-20 feature importance

| # | feature | importance |
|---|---|---|
| 1 | `machine__anom_density_24h` | 0.30245 |
| 2 | `yankee_steam_pressure__roll1h_mean` | 0.06186 |
| 3 | `yankee_steam_pressure__roll7d_mean` | 0.06173 |
| 4 | `yankee_steam_pressure__roll24h_mean` | 0.05427 |
| 5 | `yankee_steam_pressure__anom_density_24h` | 0.03147 |
| 6 | `visconip_felt_moisture__anom_density_24h` | 0.02246 |
| 7 | `aircap_inlet_temp__anom_density_24h` | 0.02054 |
| 8 | `rewinder_speed__zscore30d` | 0.01995 |
| 9 | `anomaly_score` | 0.0183 |
| 10 | `yankee_blade_pressure__roll7d_mean` | 0.01777 |
| 11 | `yankee_vibration_bearing_1__anom_density_24h` | 0.01745 |
| 12 | `yankee_vibration_bearing_1__roll7d_mean` | 0.01483 |
| 13 | `yankee_vibration_bearing_1__roll1h_mean` | 0.01448 |
| 14 | `yankee_vibration_bearing_1__roll24h_mean` | 0.01299 |
| 15 | `yankee_blade_pressure__roll1h_mean` | 0.01134 |
| 16 | `component__days_since_install` | 0.01093 |
| 17 | `yankee_surface_temp__anom_density_24h` | 0.01059 |
| 18 | `yankee_blade_pressure__roll24h_mean` | 0.01041 |
| 19 | `yankee_vibration_bearing_1__roll7d_std` | 0.00994 |
| 20 | `rewinder_speed__roll6h_mean` | 0.00829 |

## Per-component performance (holdout)

| machine | component | n | MAE | warning F1 | critical F1 | max predicted | max actual |
|---|---|---|---|---|---|---|---|
| al-nakheel | headbox | 292 | 1.63 | 1.0 | 0.7 | 88.18000030517578 | 100.0 |
| al-nakheel | visconip | 292 | 1.29 | 0.0 | 0.0 | 1.3700000047683716 | 0.0 |
| al-nakheel | yankee | 292 | 8.22 | 0.0 | 0.0 | 77.16999816894531 | 0.0 |
| al-nakheel | aircap | 292 | 1.29 | 0.0 | 0.0 | 1.2899999618530273 | 0.0 |
| al-nakheel | softreel | 292 | 1.29 | 0.0 | 0.0 | 1.2899999618530273 | 0.0 |
| al-nakheel | rewinder | 292 | 1.29 | 0.0 | 0.0 | 1.3700000047683716 | 0.0 |
| al-bardi | headbox | 292 | 1.0 | 0.0 | 0.0 | 1.2899999618530273 | 0.0 |
| al-bardi | visconip | 292 | 8.45 | 0.911 | 0.095 | 86.25 | 100.0 |
| al-bardi | yankee | 292 | 8.52 | 0.0 | 0.0 | 45.040000915527344 | 0.0 |
| al-bardi | aircap | 292 | 1.29 | 0.0 | 0.0 | 1.2899999618530273 | 0.0 |
| al-bardi | softreel | 292 | 1.23 | 0.0 | 0.0 | 1.2899999618530273 | 0.0 |
| al-bardi | rewinder | 292 | 11.96 | 0.115 | 0.19 | 88.18000030517578 | 100.0 |
| al-sindian | headbox | 292 | 0.95 | 0.0 | 0.0 | 1.2899999618530273 | 0.0 |
| al-sindian | visconip | 292 | 1.29 | 0.0 | 0.0 | 1.2899999618530273 | 0.0 |
| al-sindian | yankee | 292 | 30.82 | 0.0 | 0.0 | 45.040000915527344 | 100.0 |
| al-sindian | aircap | 292 | 1.23 | 0.0 | 0.0 | 1.2899999618530273 | 0.0 |
| al-sindian | softreel | 292 | 1.02 | 0.0 | 0.0 | 1.2899999618530273 | 0.0 |
| al-sindian | rewinder | 292 | 10.21 | 0.339 | 0.0 | 83.61000061035156 | 100.0 |
| al-snobar | headbox | 292 | 1.21 | 0.0 | 0.0 | 1.2899999618530273 | 0.0 |
| al-snobar | visconip | 292 | 1.26 | 0.0 | 0.0 | 1.2899999618530273 | 0.0 |
| al-snobar | yankee | 292 | 31.95 | 0.349 | 0.255 | 88.18000030517578 | 100.0 |
| al-snobar | aircap | 292 | 1.29 | 0.0 | 0.0 | 1.2899999618530273 | 0.0 |
| al-snobar | softreel | 292 | 1.26 | 0.0 | 0.0 | 1.2899999618530273 | 0.0 |
| al-snobar | rewinder | 292 | 9.92 | 0.676 | 0.438 | 100.0 | 100.0 |
