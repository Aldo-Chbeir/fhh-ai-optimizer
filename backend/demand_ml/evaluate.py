"""Holdout evaluation report — pulls per-(market, product) accuracy out of
each saved Prophet model, aggregates by market and category, and writes
both JSON + Markdown to reports/.

Run with:
    python -m backend.demand_ml.evaluate
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from . import MODEL_VERSION, config, data, persist

log = logging.getLogger("fhh.demand.eval")


# ---------------------------------------------------------------------------
# Per-model holdout metrics
# ---------------------------------------------------------------------------

def _evaluate_one(
    market_id: str, product_id: str, category: Optional[str] = None,
) -> Optional[dict]:
    if not persist.exists(config.model_path(market_id, product_id)):
        return None
    artifact = persist.load(config.model_path(market_id, product_id))
    model = artifact["model"]

    df = data.load_market_product_history(market_id, product_id)
    if df.empty:
        return None
    train, holdout = data.split_train_holdout(df)
    if holdout.empty:
        return None

    future = holdout[["ds"] + config.REGRESSORS].copy()
    forecast = model.predict(future)
    yhat = forecast["yhat"].to_numpy()
    y_true = holdout["y"].to_numpy()
    safe_y = np.where(y_true == 0, 1.0, y_true)
    mape = float(np.mean(np.abs(yhat - y_true) / np.abs(safe_y)) * 100.0)
    smape = float(np.mean(2.0 * np.abs(yhat - y_true) /
                          (np.abs(y_true) + np.abs(yhat) + 1e-9)) * 100.0)
    in_band = ((y_true >= forecast["yhat_lower"].to_numpy()) &
               (y_true <= forecast["yhat_upper"].to_numpy()))
    coverage = float(in_band.mean() * 100.0)
    bias = float(np.mean(yhat - y_true))

    return {
        "market_id": market_id,
        "product_id": product_id,
        "category": category,
        "n_holdout": int(len(holdout)),
        "mape_pct": round(mape, 2),
        "smape_pct": round(smape, 2),
        "coverage_pct": round(coverage, 1),
        "bias_units": round(bias, 1),
        "actual_total": int(y_true.sum()),
        "predicted_total": int(yhat.sum()),
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
    t0 = time.perf_counter()

    products = data.fetch_products()
    markets = data.fetch_markets()
    cat_lookup = {sku: cat for sku, cat in products}

    log.info("evaluating %d (market × product) pairs", len(markets) * len(products))

    rows: list[dict] = []
    skipped = 0
    for m in markets:
        for sku, cat in products:
            r = _evaluate_one(m, sku, cat)
            if r is None:
                skipped += 1
                continue
            rows.append(r)

    if not rows:
        log.error("no models evaluated — did you run train.py?")
        return 1
    log.info("evaluated %d models  (%d skipped, no model on disk)",
             len(rows), skipped)

    df = pd.DataFrame(rows)

    overall = {
        "n_models": int(len(df)),
        "mean_mape_pct": round(float(df["mape_pct"].mean()), 2),
        "median_mape_pct": round(float(df["mape_pct"].median()), 2),
        "mean_smape_pct": round(float(df["smape_pct"].mean()), 2),
        "mean_coverage_pct": round(float(df["coverage_pct"].mean()), 1),
        "models_under_target": int((df["mape_pct"] <= config.TARGET_AVG_MAPE_PCT).sum()),
        "target_avg_mape_pct": config.TARGET_AVG_MAPE_PCT,
    }

    by_market = (
        df.groupby("market_id")
          .agg(n=("mape_pct", "count"),
               mape=("mape_pct", "mean"),
               smape=("smape_pct", "mean"),
               coverage=("coverage_pct", "mean"))
          .reset_index()
          .round(2)
          .to_dict(orient="records")
    )
    by_category = (
        df.groupby("category")
          .agg(n=("mape_pct", "count"),
               mape=("mape_pct", "mean"),
               smape=("smape_pct", "mean"))
          .reset_index()
          .round(2)
          .to_dict(orient="records")
    )

    sorted_df = df.sort_values("mape_pct")
    best5 = sorted_df.head(5).to_dict(orient="records")
    worst5 = sorted_df.tail(5).iloc[::-1].to_dict(orient="records")

    report = {
        "model_version": MODEL_VERSION,
        "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "train_window": {
            "start": str(config.HISTORY_START),
            "end": str(config.TRAIN_END),
        },
        "holdout_window": {
            "start": str(config.HOLDOUT_START),
            "end": str(config.HOLDOUT_END),
        },
        "overall": overall,
        "per_market": by_market,
        "per_category": by_category,
        "best_5_models": best5,
        "worst_5_models": worst5,
        "all_models": rows,
        "evaluation_seconds": round(time.perf_counter() - t0, 2),
    }

    config.REPORT_JSON_PATH.write_text(json.dumps(report, indent=2, default=str),
                                       encoding="utf-8")
    config.REPORT_MD_PATH.write_text(_render_markdown(report), encoding="utf-8")

    log.info("wrote %s", config.REPORT_JSON_PATH)
    log.info("wrote %s", config.REPORT_MD_PATH)

    log.info("OVERALL  mean MAPE=%.2f%%  median=%.2f%%  coverage=%.1f%%  "
             "models under target=%d/%d",
             overall["mean_mape_pct"], overall["median_mape_pct"],
             overall["mean_coverage_pct"],
             overall["models_under_target"], overall["n_models"])
    return 0


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def _render_markdown(r: dict) -> str:
    md: list[str] = []
    md.append(f"# Demand-forecast model validation — {r['model_version']}")
    md.append("")
    md.append(f"_Generated: {r['generated_at']}_")
    md.append("")
    md.append(f"- **Train window**:   {r['train_window']['start']} → {r['train_window']['end']}")
    md.append(f"- **Holdout window**: {r['holdout_window']['start']} → {r['holdout_window']['end']}")
    md.append(f"- **Models evaluated**: {r['overall']['n_models']}")
    md.append(f"- **Evaluation time**: {r['evaluation_seconds']}s")
    md.append("")
    md.append("## Overall accuracy")
    md.append("")
    o = r["overall"]
    md.append(f"| Metric | Value |")
    md.append(f"|---|---|")
    md.append(f"| Mean MAPE | **{o['mean_mape_pct']}%** |")
    md.append(f"| Median MAPE | {o['median_mape_pct']}% |")
    md.append(f"| Mean sMAPE | {o['mean_smape_pct']}% |")
    md.append(f"| Mean 80%-CI coverage | {o['mean_coverage_pct']}% |")
    md.append(f"| Models ≤ {o['target_avg_mape_pct']}% MAPE | {o['models_under_target']} / {o['n_models']} |")
    md.append("")

    md.append("## Per-market accuracy")
    md.append("")
    md.append("| market | n | mean MAPE | mean sMAPE | mean coverage |")
    md.append("|---|---|---|---|---|")
    for m in r["per_market"]:
        md.append(f"| {m['market_id']} | {m['n']} | {m['mape']}% | {m['smape']}% | {m['coverage']}% |")
    md.append("")

    md.append("## Per-category accuracy")
    md.append("")
    md.append("| category | n | mean MAPE | mean sMAPE |")
    md.append("|---|---|---|---|")
    for c in r["per_category"]:
        md.append(f"| {c['category']} | {c['n']} | {c['mape']}% | {c['smape']}% |")
    md.append("")

    md.append("## Best 5 models (lowest MAPE)")
    md.append("")
    md.append("| market | product | n_holdout | MAPE | sMAPE | coverage |")
    md.append("|---|---|---|---|---|---|")
    for x in r["best_5_models"]:
        md.append(f"| {x['market_id']} | `{x['product_id']}` | {x['n_holdout']} | "
                  f"{x['mape_pct']}% | {x['smape_pct']}% | {x['coverage_pct']}% |")
    md.append("")

    md.append("## Worst 5 models (highest MAPE)")
    md.append("")
    md.append("| market | product | n_holdout | MAPE | sMAPE | coverage |")
    md.append("|---|---|---|---|---|---|")
    for x in r["worst_5_models"]:
        md.append(f"| {x['market_id']} | `{x['product_id']}` | {x['n_holdout']} | "
                  f"{x['mape_pct']}% | {x['smape_pct']}% | {x['coverage_pct']}% |")
    md.append("")

    return "\n".join(md)


if __name__ == "__main__":
    import sys
    sys.exit(main())
