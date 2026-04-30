# FHH AI Optimizer — ML training & inference

Two-stage prediction pipeline that scores every (machine, component) pair
on a continuous 0-100 risk axis aligned with API_CONTRACT.md v1.1.

```
                ┌───────────────────────┐         ┌────────────────────────┐
sensor_readings │ IsolationForest × 24  │ anomaly │ XGBoost regressor (1)  │ score (0-100)
   ───────────► │ (one per machine,     │ ──────► │ + isotonic calibration │ ─────────────►
maintenance_log │  component)           │  score  │ + feature attribution  │ tier, window
                └───────────────────────┘         └────────────────────────┘
```

## Files

| File | Purpose |
|---|---|
| `config.py`        | Paths, sensor metadata, hyperparameters, tier thresholds |
| `data.py`          | Synchronous DB loaders (SQLAlchemy + TimescaleDB `time_bucket`) |
| `features.py`      | Rolling stats, slopes, 30-day deviation, anomaly density, component meta |
| `persist.py`       | joblib save/load wrappers |
| `train_anomaly.py` | Fits 24 IsolationForest models on the 80% training period |
| `train_risk.py`    | Fits the global XGBoost regressor + isotonic calibrator |
| `predict.py`       | `predict_component_risk(machine, component, as_of=None)` |
| `evaluate.py`      | Holdout metrics → `reports/model_validation.{json,md}` |

Trained models land in `models/` (gitignored). A fresh checkout has no
artifacts; the API automatically falls back to the DB heuristic in
`backend/api/services/risk.py` until you run training.

## How features are built

For each (machine, component, ts):
- Hourly aggregates from `sensor_readings` over `[ts - history, ts]`
- Rolling **mean** and **std** over 1h / 6h / 24h / 7d windows per sensor
- OLS **slope** over the last 24h and 7d per sensor
- 30-day robust **z-score** of the latest reading per sensor
- **Anomaly density**: count of readings flagged as out-of-range in the last 24h
- Component metadata: hours-since-maintenance, days-since-install, lifetime-pct
- Machine-wide aggregate anomaly density (cross-component)

Same function powers training AND inference, so layouts cannot drift.

## Training labels

`label = max(0, 100 * (1 - days_to_next_failure / 30))`

`days_to_next_failure` is computed from `maintenance_logs` rows where
`maintenance_type = 'corrective'` (these are the 25 ground-truth failure
events seeded into the DB). A reading 1 day before a failure → label ≈ 97;
a reading 30+ days from any failure → label = 0.

## Time-based 80/20 split

The data spans roughly 2025-04-25 → 2026-04-24. The first 80% of that
span is used for training; the last 20% is the holdout. Both
`train_anomaly.py` and `train_risk.py` compute the cutoff dynamically
from `MIN/MAX(timestamp)` on the hypertable so the split survives
re-seeding.

## Run

```bash
# 1. Train the per-(machine, component) IsolationForests
python -m backend.ml.train_anomaly

# 2. Train the global XGBoost regressor + calibrator
python -m backend.ml.train_risk

# 3. Generate the validation report
python -m backend.ml.evaluate

# 4. (Optional) Trigger retraining via the API
curl -s -X POST http://localhost:8000/admin/retrain \
  -H 'X-Admin-Token: fhh-admin-dev-token'
```

After training the API automatically picks up the new artifacts (the
`risk` service caches an "ML available" flag; `/admin/retrain` resets it).

## Inference contract

```python
from backend.ml.predict import predict_component_risk

predict_component_risk("al-nakheel", "yankee")
# → {
#       "score": 87,
#       "tier": "critical",
#       "predicted_failure_window_hours": 48,
#       "top_contributing_features": [
#           {"feature": "yankee_vibration_bearing_3__roll7d_mean", "weight": 0.41},
#           ...
#       ],
#       "anomaly_score": 0.92,
#       "model_version": "0.1.0",
#       "as_of": "2026-04-24T23:00:00Z",
#   }
```

`tier` follows API_CONTRACT.md v1.1, tuned for **high recall on the critical
tier** (industrial safety best practice):
healthy <30 · watch 30-49 · warning 50-69 · critical 70+.

The lower critical floor (70 instead of a precision-friendly 85) catches
more real failures at the cost of more false alarms. See
`reports/model_validation.md` → "Design Decision: High Recall over Precision".

`predicted_failure_window_hours` is `None` for any score < 60.
