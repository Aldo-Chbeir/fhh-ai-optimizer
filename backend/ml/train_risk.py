"""Train the global XGBoost risk regressor.

Run with:
    python -m backend.ml.train_risk

Pipeline:
  1. Build a flat feature matrix across ALL (machine, component) timestamps.
  2. Append per-(machine, component) IsolationForest anomaly score as a feature
     (loaded from disk — train_anomaly.py must run first).
  3. Compute label = 100 * max(0, 1 - days_to_next_failure / 30) for each row.
  4. Time-based 80/20 split on `timestamp`.
  5. Fit XGBoost with early stopping on the holdout.
  6. Calibrate raw score → "calibrated score 0-100" via isotonic regression
     on the holdout (so scores align with real failure rates).
  7. Persist model + calibrator + metadata.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error

from . import config, data, features, persist

log = logging.getLogger("fhh.ml.risk")


def _build_full_dataset(
    lo: datetime,
    hi: datetime,
    split: datetime,
    components_meta: pd.DataFrame,
    failures: pd.DataFrame,
) -> pd.DataFrame:
    """Return one giant DataFrame: features + label + group flag (train|holdout)."""
    base_raw = pd.Timestamp(lo + timedelta(days=30))
    base = (base_raw.tz_localize("UTC") if base_raw.tzinfo is None
            else base_raw.tz_convert("UTC")).floor("h")
    n_hours = int((hi - base.to_pydatetime()).total_seconds() // 3600)
    ts_full = [base + pd.Timedelta(hours=h)
               for h in range(0, n_hours, config.TRAINING_SAMPLE_EVERY_HOURS)]
    log.info("planned timestamps per (machine, component): %d", len(ts_full))

    frames: list[pd.DataFrame] = []
    for mi, machine_id in enumerate(config.MACHINES):
        for ci, component_id in enumerate(config.COMPONENT_ORDER):
            label = f"[{mi*6+ci+1:>2d}/24] {machine_id}/{component_id}"
            t1 = time.perf_counter()
            df = features.build_feature_frame(
                machine_id=machine_id,
                component_id=component_id,
                timestamps=ts_full,
                components_meta=components_meta,
                history_start=lo - timedelta(days=30),
                history_end=hi,
            )
            df["label"] = df["timestamp"].apply(lambda t: features.label_for_target(
                features.days_to_next_failure(machine_id, component_id, t, failures)
            ))
            # Anomaly score from the per-(machine, component) IF model.
            from sklearn.ensemble import IsolationForest  # noqa
            artifact = persist.load(config.anomaly_model_path(machine_id, component_id))
            if_model: IsolationForest = artifact["model"]
            feat_cols = artifact["feature_names"]
            X = df[feat_cols].fillna(0.0).to_numpy()
            # `score_samples` is higher = more normal; flip & scale so
            # higher = more anomalous, in [0, 1].
            raw = -if_model.score_samples(X)
            # Min-max normalise robustly so it's roughly [0, 1].
            lo_q, hi_q = np.quantile(raw, [0.01, 0.99])
            df["anomaly_score"] = np.clip((raw - lo_q) / max(1e-9, hi_q - lo_q), 0.0, 1.0)
            frames.append(df)
            log.info("%s | rows=%d | label_pos=%.1f%% | %.2fs",
                     label, len(df),
                     100.0 * (df["label"] > 0).mean(),
                     time.perf_counter() - t1)

    full = pd.concat(frames, ignore_index=True)
    split_ts = pd.Timestamp(split)
    if split_ts.tzinfo is None:
        split_ts = split_ts.tz_localize("UTC")
    else:
        split_ts = split_ts.tz_convert("UTC")
    full["group"] = np.where(full["timestamp"] < split_ts, "train", "holdout")
    return full


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                        datefmt="%H:%M:%S")
    t0 = time.perf_counter()

    lo, hi = data.fetch_data_range()
    span_seconds = (hi - lo).total_seconds()
    split = lo + timedelta(seconds=span_seconds * (1.0 - config.DEFAULT_HOLDOUT_FRACTION))
    log.info("data: %s → %s | split: %s", lo, hi, split)

    components_meta = data.fetch_components_meta()
    failures = data.fetch_corrective_events()
    log.info("corrective events: %d", len(failures))

    full = _build_full_dataset(lo, hi, split, components_meta, failures)
    log.info("full dataset: %d rows | %d features | label mean=%.2f",
             len(full),
             len(features.feature_columns(full)),
             full["label"].mean())

    feat_cols = features.feature_columns(full)
    train = full[full["group"] == "train"]
    hold = full[full["group"] == "holdout"]
    log.info("train rows: %d | holdout rows: %d", len(train), len(hold))

    X_tr = train[feat_cols].fillna(0.0).to_numpy()
    y_tr = train["label"].to_numpy()
    X_te = hold[feat_cols].fillna(0.0).to_numpy()
    y_te = hold["label"].to_numpy()

    log.info("fitting XGBoost (n_estimators=%d, depth=%d, lr=%.3f)...",
             config.XGBOOST["n_estimators"],
             config.XGBOOST["max_depth"],
             config.XGBOOST["learning_rate"])

    # Up-weight high-label rows so the rare "imminent failure" class drives gradient.
    sw = np.clip(y_tr / 20.0, a_min=1.0, a_max=None)

    model = xgb.XGBRegressor(
        **config.XGBOOST,
        early_stopping_rounds=config.XGBOOST_FIT["early_stopping_rounds"],
    )
    model.fit(
        X_tr, y_tr,
        sample_weight=sw,
        eval_set=[(X_te, y_te)],
        verbose=False,
    )

    raw_tr = model.predict(X_tr)
    raw_te = model.predict(X_te)

    # Holdout regression metrics
    mae = float(mean_absolute_error(y_te, raw_te))
    rmse = float(np.sqrt(mean_squared_error(y_te, raw_te)))
    log.info("holdout MAE=%.2f  RMSE=%.2f", mae, rmse)

    # Isotonic calibration so predicted score aligns with empirical label distribution.
    cal = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=100.0)
    cal.fit(raw_te, y_te)
    cal_te = cal.transform(raw_te)
    cal_mae = float(mean_absolute_error(y_te, cal_te))
    log.info("calibrated holdout MAE=%.2f", cal_mae)

    # ---- Persist ----------------------------------------------------------
    persist.save({
        "model": model,
        "feature_names": feat_cols,
        "best_iteration": int(getattr(model, "best_iteration", 0) or 0),
        "trained_until": split.isoformat(),
    }, config.RISK_MODEL_PATH)
    persist.save({"calibrator": cal}, config.RISK_CALIBRATOR_PATH)

    persist.save({
        "feature_names": feat_cols,
        "data_min": lo.isoformat(),
        "data_max": hi.isoformat(),
        "train_split": split.isoformat(),
        "n_train": int(len(train)),
        "n_holdout": int(len(hold)),
        "holdout_mae_raw": mae,
        "holdout_rmse_raw": rmse,
        "holdout_mae_calibrated": cal_mae,
    }, config.RISK_METADATA_PATH)

    elapsed = time.perf_counter() - t0
    log.info("TOTAL risk training: %.1fs", elapsed)


if __name__ == "__main__":
    main()
