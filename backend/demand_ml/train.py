"""Train one Prophet model per (market × SKU) — 185 in total.

Run with:
    python -m backend.demand_ml.train
    python -m backend.demand_ml.train --limit 10        # quick smoke
    python -m backend.demand_ml.train --skip-existing   # resume after a partial run

Each model trains on 2023-01-01 → 2025-09-30 and is evaluated on the
2025-10-01 → 2025-12-31 holdout. We log per-model MAPE so the wall is
audible if anything regresses.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Optional

import numpy as np
import pandas as pd

from . import MODEL_VERSION, config, data, persist

# Prophet is *very* loud (CmdStanPy chains, PyStan deprecation warnings).
# Silence the routine ones — real errors still propagate.
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
logging.getLogger("prophet").setLevel(logging.WARNING)


log = logging.getLogger("fhh.demand.train")


# ---------------------------------------------------------------------------
# Single-model training (callable from worker pool)
# ---------------------------------------------------------------------------

def train_one(market_id: str, product_id: str) -> dict:
    """Train + evaluate one Prophet model. Returns metric dict."""
    from prophet import Prophet  # imported here for ProcessPool friendliness

    t0 = time.perf_counter()
    df = data.load_market_product_history(market_id, product_id)
    if df.empty:
        return {"market_id": market_id, "product_id": product_id, "status": "no_data"}

    train, holdout = data.split_train_holdout(df)
    if len(train) < 365 or len(holdout) < 7:
        return {
            "market_id": market_id, "product_id": product_id,
            "status": "insufficient_history",
            "n_train": int(len(train)), "n_holdout": int(len(holdout)),
        }

    m = Prophet(**config.PROPHET_PARAMS)
    for reg in config.REGRESSORS:
        m.add_regressor(reg, mode=config.REGRESSOR_MODE)

    fit_cols = ["ds", "y"] + config.REGRESSORS
    m.fit(train[fit_cols])

    # ---- Holdout MAPE ------------------------------------------------------
    future = holdout[["ds"] + config.REGRESSORS].copy()
    forecast = m.predict(future)
    yhat = forecast["yhat"].to_numpy()
    y_true = holdout["y"].to_numpy()
    # Avoid div-by-zero on rare zero-demand days
    safe_y = np.where(y_true == 0, 1.0, y_true)
    mape_pct = float(np.mean(np.abs(yhat - y_true) / np.abs(safe_y)) * 100.0)
    smape_pct = float(np.mean(
        2.0 * np.abs(yhat - y_true) / (np.abs(y_true) + np.abs(yhat) + 1e-9)
    ) * 100.0)
    in_band = ((y_true >= forecast["yhat_lower"].to_numpy()) &
               (y_true <= forecast["yhat_upper"].to_numpy()))
    coverage_pct = float(in_band.mean() * 100.0)

    persist.save({
        "model": m,
        "model_version": MODEL_VERSION,
        "market_id": market_id,
        "product_id": product_id,
        "trained_until": str(config.TRAIN_END),
        "n_train": int(len(train)),
        "regressors": config.REGRESSORS,
    }, config.model_path(market_id, product_id))

    return {
        "market_id": market_id,
        "product_id": product_id,
        "status": "ok",
        "n_train": int(len(train)),
        "n_holdout": int(len(holdout)),
        "mape_pct": round(mape_pct, 2),
        "smape_pct": round(smape_pct, 2),
        "coverage_pct": round(coverage_pct, 1),
        "fit_seconds": round(time.perf_counter() - t0, 2),
    }


def _train_one_safe(market_id: str, product_id: str) -> dict:
    try:
        return train_one(market_id, product_id)
    except Exception as exc:  # noqa: BLE001
        return {
            "market_id": market_id, "product_id": product_id,
            "status": "error", "error": f"{type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limit", type=int, default=None,
                   help="Train only the first N (market, product) combos (smoke test).")
    p.add_argument("--skip-existing", action="store_true",
                   help="Skip combos that already have a saved model.")
    p.add_argument("--workers", type=int, default=1,
                   help="Parallel worker count. Prophet is single-threaded; "
                        "set this above 1 only on a multi-core machine. "
                        "Default 1 keeps the worker pool out of Windows BLAS quirks.")
    args = p.parse_args()

    products = data.fetch_products()
    markets = data.fetch_markets()
    pairs: list[tuple[str, str]] = [
        (m, sku) for m in markets for sku, _cat in products
    ]
    if args.limit:
        pairs = pairs[: args.limit]
    if args.skip_existing:
        pairs = [(m, p_) for m, p_ in pairs if not persist.exists(config.model_path(m, p_))]

    log.info("training %d Prophet models  (markets=%d, products=%d)",
             len(pairs), len(markets), len(products))

    t_start = time.perf_counter()
    results: list[dict] = []

    if args.workers > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(_train_one_safe, m, sku): (m, sku) for m, sku in pairs}
            for i, fut in enumerate(as_completed(futures), 1):
                r = fut.result()
                results.append(r)
                _log_result(i, len(pairs), r)
    else:
        for i, (m, sku) in enumerate(pairs, 1):
            r = _train_one_safe(m, sku)
            results.append(r)
            _log_result(i, len(pairs), r)

    # Summary
    ok = [r for r in results if r["status"] == "ok"]
    bad = [r for r in results if r["status"] != "ok"]
    elapsed = time.perf_counter() - t_start
    log.info("=" * 60)
    log.info("trained %d / %d models in %.1fs", len(ok), len(pairs), elapsed)
    if ok:
        mape_avg = float(np.mean([r["mape_pct"] for r in ok]))
        smape_avg = float(np.mean([r["smape_pct"] for r in ok]))
        cov_avg = float(np.mean([r["coverage_pct"] for r in ok]))
        log.info("mean MAPE=%.2f%%  sMAPE=%.2f%%  coverage=%.1f%%",
                 mape_avg, smape_avg, cov_avg)
    if bad:
        log.warning("failures (%d):", len(bad))
        for r in bad[:10]:
            log.warning("  %s/%s -> %s", r["market_id"], r["product_id"],
                        r.get("error") or r["status"])
    return 0 if not bad else 1


def _log_result(i: int, total: int, r: dict) -> None:
    label = f"[{i:>3d}/{total}] {r['market_id']}/{r['product_id']}"
    if r["status"] == "ok":
        log.info("%s | mape=%.2f%% smape=%.2f%% cov=%.1f%% (%s)",
                 label, r["mape_pct"], r["smape_pct"], r["coverage_pct"],
                 f"{r['fit_seconds']}s")
    elif r["status"] == "error":
        log.warning("%s | ERROR %s", label, r.get("error"))
    else:
        log.warning("%s | %s", label, r["status"])


if __name__ == "__main__":
    sys.exit(main())
