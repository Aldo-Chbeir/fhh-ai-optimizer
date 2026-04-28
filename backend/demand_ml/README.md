# FHH AI Optimizer — Prophet demand forecasting

185 univariate Prophet models, one per (market × SKU), trained on the
`demand_history` hypertable. Ramadan, Eid al-Fitr, Eid al-Adha,
pre-Ramadan stockup, and active promos are wired in as multiplicative
regressors so the model learns how each event shifts demand for each
specific (market, SKU) pair.

## Architecture

```
                    demand_history          demand_calendar
   ┌──────────────────────────────────┐    ┌───────────────────────────┐
   │ date, market_id, product_id,     │    │ date, is_ramadan,         │
   │ units_sold, revenue, promo_active│    │ is_eid_alfitr/aladha,     │
   └──────────────┬───────────────────┘    │ is_pre_ramadan_stockup,   │
                  │                         │ ramadan_day, holiday_name │
                  │  data.py joins  ◄───────┤                           │
                  ▼                         └───────────────────────────┘
       ┌──────────────────────────────┐
       │ Prophet-ready frame:         │
       │  ds, y, is_ramadan,          │
       │  is_eid_alfitr,              │
       │  is_eid_aladha,              │
       │  is_pre_ramadan_stockup,     │
       │  promo_active                │
       └──────────────┬───────────────┘
                      │  fit one model per (market, sku)
                      ▼
                ┌─────────────────┐         ┌────────────────────────┐
                │ 185 Prophet pkls│ ──────► │ predict.forecast_demand│
                └─────────────────┘         └─────────┬──────────────┘
                                                      │
                       ┌──────────────────────────────┴──────────────────┐
                       │                                                 │
                       ▼                                                 ▼
            backend/api/services/demand_prophet.py            backend/demand_ml/decompose.py
                       │                                                 │
                       ▼                                                 ▼
              GET /forecast                                 GET /demand/seasonality
              POST /forecast/scenario                       (decomposed: trend, weekly,
              GET /demand/anomalies                          yearly, regressor lifts)
```

## Files

| File | Purpose |
|---|---|
| `config.py`     | Paths, hyperparameters, train/holdout cutoffs |
| `data.py`       | Synchronous DB loaders, `build_future_frame` (extends calendar past Dec 2025) |
| `persist.py`    | joblib save/load |
| `train.py`      | Fits 185 models, persists each, logs per-model MAPE/sMAPE/coverage |
| `predict.py`    | `forecast_demand(market, sku, horizon_days, scenario_overrides)` |
| `decompose.py`  | Pulls trend / weekly / yearly / regressor curves out of a fitted model |
| `evaluate.py`   | Holdout report → `reports/demand_validation.{json,md}` |

## Training

Run the full set:

```bash
python -m backend.demand_ml.train
```

Useful flags:

```bash
python -m backend.demand_ml.train --limit 10        # smoke test on the first 10 combos
python -m backend.demand_ml.train --skip-existing   # resume after a partial run
python -m backend.demand_ml.train --workers 4       # parallel (multi-core machines only)
```

Per-model footprint is small — ~1 second per Prophet fit, ~1 MB pkl on disk.
Total wall time on a single core: **~75 seconds** for all 185 models.

## Inference

```python
from backend.demand_ml.predict import forecast_demand

out = forecast_demand("uae", "fine-facial-100", horizon_days=120)

#  out["forecast"]:        per-day {date, predicted_units, lower_bound, upper_bound,
#                                  trend_component, seasonal_component, holiday_component}
#  out["weekly_rollup"]:   per ISO-week totals + bands
#  out["monthly_rollup"]:  per-month totals + bands
#  out["key_drivers"]:     {yoy_growth_pct, ramadan_lift_pct, eid_alfitr_lift_pct,
#                           summer_dip_pct, trend_direction}
#  out["model_version"]:   "demand-0.1.0"
```

### Scenario what-if

Pass a `scenario_overrides` dict to amplify, shift, or kill regressors:

| Key | Effect |
|---|---|
| `is_ramadan_starts_earlier: 7` | Shift Ramadan/pre-stockup flags 7 days earlier |
| `ramadan_intensity_multiplier: 1.5` | Scale Ramadan + pre-stockup regressor (+50 % ⇒ Prophet's learned lift becomes 1.5×) |
| `disable_ramadan: true` | Zero out Ramadan and pre-stockup |
| `eid_alfitr_extra_day: true` | Tag the day before each Eid as Eid too |
| `promo_boost: 0.20` | Set 20 % of horizon days to `promo_active=1` |

## API endpoints (wired automatically when models exist)

| Method · Path | Path |
|---|---|
| `GET`  | `/forecast?sku=...&market=...&horizon_months=6` |
| `POST` | `/forecast/scenario` (body: `{sku, market, horizon_months, scenario}`) |
| `GET`  | `/demand/seasonality?sku=...&market=...` (Prophet decomposition) |
| `GET`  | `/demand/anomalies?market=...&sku=...&days=60` |
| `POST` | `/admin/retrain-demand` (header: `X-Admin-Token: ...`) |

If no models exist on disk, all four fall back to the synthetic generators
in `backend/api/services/forecast.py` so the API stays callable on a fresh
clone.

## Validation report

Generate the JSON + Markdown holdout report:

```bash
python -m backend.demand_ml.evaluate
# → reports/demand_validation.json
# → reports/demand_validation.md
```

The report breaks accuracy down per market, per category, plus best-5 / worst-5.

### What the report measures

| Metric | Description |
|---|---|
| **MAPE** | mean absolute percentage error on the holdout (Oct-Dec 2025). Average across 185 models, with a target of < 12 %. |
| **sMAPE** | symmetric MAPE — robust to small/zero actuals |
| **Coverage** | % of holdout days where the actual fell inside the predicted [lower, upper] band. The target band is 80 % (configured via `interval_width=0.80`). |
| **Bias** | mean(yhat - actual). A persistent positive bias suggests the model over-forecasts. |

## Known issues / fallbacks

- **Prophet on Windows**: `prophet>=1.1.5` ships with prebuilt cmdstan binaries
  for Win-x64, so no C++ compile is needed. If install ever breaks we fall back
  to the synthetic forecast generator in `backend/api/services/forecast.py`.
- **Plotly warning** (`Importing plotly failed. Interactive plots will not work.`)
  is harmless — Prophet only uses plotly for built-in plotting helpers we don't call.
- **`yhat_lower` occasionally turning negative**: with `growth=linear` and
  `interval_width=0.80`, low-volume SKUs sometimes get small negative lower
  bounds. We clip below zero in the API layer (zero is the only physically
  sensible floor for unit counts).

## Re-training

Two equivalent paths:

```bash
# CLI
python -m backend.demand_ml.train

# API (must include the admin token)
curl -s -X POST http://localhost:8000/admin/retrain-demand \
     -H 'X-Admin-Token: fhh-admin-dev-token'
```

The API call drops the in-process model cache after training so subsequent
`/forecast` requests pick up the freshly persisted models without restart.
