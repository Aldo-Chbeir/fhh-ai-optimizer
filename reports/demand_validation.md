# Demand-forecast model validation — demand-0.1.0

_Generated: 2026-04-28T12:54:10Z_

- **Train window**:   2023-01-01 → 2025-09-30
- **Holdout window**: 2025-10-01 → 2025-12-31
- **Models evaluated**: 185
- **Evaluation time**: 15.54s

## Overall accuracy

| Metric | Value |
|---|---|
| Mean MAPE | **4.25%** |
| Median MAPE | 4.22% |
| Mean sMAPE | 4.24% |
| Mean 80%-CI coverage | 83.8% |
| Models ≤ 12.0% MAPE | 185 / 185 |

## Per-market accuracy

| market | n | mean MAPE | mean sMAPE | mean coverage |
|---|---|---|---|---|
| egypt | 37 | 4.09% | 4.08% | 86.19% |
| jordan | 37 | 4.34% | 4.33% | 82.61% |
| ksa | 37 | 4.23% | 4.22% | 87.13% |
| morocco | 37 | 4.37% | 4.35% | 78.96% |
| uae | 37 | 4.24% | 4.23% | 84.08% |

## Per-category accuracy

| category | n | mean MAPE | mean sMAPE |
|---|---|---|---|
| adult_care | 30 | 4.25% | 4.23% |
| baby_care | 35 | 4.22% | 4.21% |
| cosmetics | 20 | 4.28% | 4.28% |
| fine_guard | 30 | 4.24% | 4.22% |
| tissue | 50 | 4.25% | 4.25% |
| wellness | 20 | 4.31% | 4.3% |

## Best 5 models (lowest MAPE)

| market | product | n_holdout | MAPE | sMAPE | coverage |
|---|---|---|---|---|---|
| jordan | `fine-baby-s3` | 92 | 3.32% | 3.33% | 92.4% |
| egypt | `fine-guard-n95-20` | 92 | 3.48% | 3.49% | 85.9% |
| uae | `fine-guard-n95-20` | 92 | 3.56% | 3.56% | 79.3% |
| jordan | `fine-sani-50ml` | 92 | 3.57% | 3.56% | 94.6% |
| egypt | `fine-adult-diaper-l` | 92 | 3.58% | 3.58% | 81.5% |

## Worst 5 models (highest MAPE)

| market | product | n_holdout | MAPE | sMAPE | coverage |
|---|---|---|---|---|---|
| jordan | `fine-guard-sani-wipes` | 92 | 5.34% | 5.2% | 69.6% |
| uae | `fine-baby-wipes-64` | 92 | 5.07% | 5.09% | 70.7% |
| morocco | `fine-sani-50ml` | 92 | 5.06% | 5.05% | 75.0% |
| jordan | `fine-makeup-wipes-25` | 92 | 5.0% | 4.96% | 68.5% |
| jordan | `fine-adult-diaper-m` | 92 | 4.99% | 5.04% | 70.7% |
