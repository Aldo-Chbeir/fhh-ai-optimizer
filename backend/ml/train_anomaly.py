"""Train one IsolationForest per (machine, component) → 24 models.

Run with:
    python -m backend.ml.train_anomaly

Each model is trained on hourly-aggregated sensor features for the FIRST
80 % of the data window (time-based split). Anomaly scores produced at
inference are used as an extra feature for the global XGBoost regressor
in train_risk.py.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from . import config, data, features, persist

log = logging.getLogger("fhh.ml.anomaly")


def _training_timestamps(start: datetime, split: datetime, step_hours: int) -> list[pd.Timestamp]:
    """Hourly stride of UTC timestamps in [start + 30d_warmup, split)."""
    warm = start + timedelta(days=30)
    if warm >= split:
        warm = start
    n_hours = int((split - warm).total_seconds() // 3600)
    if n_hours <= 0:
        return []
    ts = pd.Timestamp(warm)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    base = ts.floor("h")
    return [base + pd.Timedelta(hours=h) for h in range(0, n_hours, step_hours)]


def train_one(
    machine_id: str,
    component_id: str,
    start: datetime,
    split: datetime,
    components_meta: pd.DataFrame,
) -> tuple[IsolationForest, list[str], int, dict]:
    """Fit IF on training-period samples and return (model, feature_names, n_samples, norm)."""
    ts_list = _training_timestamps(start, split, config.TRAINING_SAMPLE_EVERY_HOURS)
    if not ts_list:
        raise RuntimeError(f"no training timestamps for {machine_id}/{component_id}")

    df = features.build_feature_frame(
        machine_id=machine_id,
        component_id=component_id,
        timestamps=ts_list,
        components_meta=components_meta,
        history_start=start - timedelta(days=30),
        history_end=split,
    )
    feat_cols = features.feature_columns(df)
    X = df[feat_cols].fillna(0.0).to_numpy()

    model = IsolationForest(**config.ISOLATION_FOREST)
    model.fit(X)

    # Capture the 1%/99% quantiles of the raw anomaly score on the training
    # set. Inference uses the SAME normalisation so anomaly scores are
    # comparable across models AND between training & inference.
    raw_train = -model.score_samples(X)
    lo_q, hi_q = float(np.quantile(raw_train, 0.01)), float(np.quantile(raw_train, 0.99))
    norm = {"raw_lo": lo_q, "raw_hi": hi_q}
    return model, feat_cols, len(X), norm


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                        datefmt="%H:%M:%S")
    t0 = time.perf_counter()

    lo, hi = data.fetch_data_range()
    span_seconds = (hi - lo).total_seconds()
    split = lo + timedelta(seconds=span_seconds * (1.0 - config.DEFAULT_HOLDOUT_FRACTION))
    log.info("data window: %s → %s", lo, hi)
    log.info("train cutoff (80%%): %s", split)

    components_meta = data.fetch_components_meta()
    log.info("components in DB: %d", len(components_meta))

    artifacts: dict[str, dict] = {}
    sample_total = 0
    for mi, machine_id in enumerate(config.MACHINES):
        for ci, component_id in enumerate(config.COMPONENT_ORDER):
            label = f"[{mi*6+ci+1:>2d}/24] {machine_id}/{component_id}"
            t1 = time.perf_counter()
            model, feat_cols, n, norm = train_one(
                machine_id, component_id, lo, split, components_meta,
            )
            sample_total += n
            persist.save({
                "model": model,
                "feature_names": feat_cols,
                "trained_until": split.isoformat(),
                "n_samples": n,
                "norm": norm,  # raw_lo / raw_hi quantiles for inference normalisation
            }, config.anomaly_model_path(machine_id, component_id))
            log.info("%s | n=%d | features=%d | %.2fs",
                     label, n, len(feat_cols), time.perf_counter() - t1)
            artifacts[f"{machine_id}/{component_id}"] = {
                "n_samples": n,
                "feature_count": len(feat_cols),
            }

    elapsed = time.perf_counter() - t0
    log.info("TOTAL anomaly training: %d models | %d samples | %.1fs",
             len(artifacts), sample_total, elapsed)


if __name__ == "__main__":
    main()
