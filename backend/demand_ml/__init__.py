"""FHH AI Optimizer — Prophet-based demand forecasting.

185 univariate Prophet models (5 markets × 37 SKUs) trained on the
seeded `demand_history` hypertable, with Ramadan / Eid / pre-stockup /
promo flags wired in as multiplicative regressors.

Public entrypoints:
  - `python -m backend.demand_ml.train`       train all 185 models
  - `python -m backend.demand_ml.evaluate`    holdout MAPE / sMAPE / coverage
  - `backend.demand_ml.predict.forecast_demand(market, sku, horizon_days=90)`
  - `backend.demand_ml.decompose.decompose_forecast(market, sku, ...)`
"""

MODEL_VERSION = "demand-0.1.0"
