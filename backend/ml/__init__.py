"""FHH AI Optimizer — ML training & inference layer.

Two-stage pipeline:
  1. Per-(machine, component) IsolationForest → anomaly score
  2. Global XGBoost regressor (features + IF score) → 0-100 risk

Public entrypoints:
  - backend.ml.train_anomaly  : python -m backend.ml.train_anomaly
  - backend.ml.train_risk     : python -m backend.ml.train_risk
  - backend.ml.evaluate       : python -m backend.ml.evaluate
  - backend.ml.predict.predict_component_risk(machine_id, component_id, as_of=None)
"""

MODEL_VERSION = "0.1.0"
