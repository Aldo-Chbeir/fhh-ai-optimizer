# FHH AI Optimizer — FastAPI backend

This package exposes the relational + TimescaleDB layer to the frontend
exactly as specified in [`API_CONTRACT.md`](../../API_CONTRACT.md) v1.1.
Field names, value types, enum strings — everything in here matches the
contract. If a field looks wrong, the contract is right and this code
needs to change, not the other way round.

## Architecture

```
backend/api/
├── main.py                # FastAPI entry + lifespan + CORS
├── errors.py              # APIError hierarchy + global handlers
├── logging_middleware.py  # Access log middleware + configure_logging
├── db/
│   └── pool.py            # asyncpg pool + get_conn dependency + db_health
├── models/                # Pydantic v2 schemas, one file per resource
├── services/              # Business logic separated from routes
│   ├── constants.py       # Sensor metadata, line order, tier_for, market names
│   ├── risk.py            # Continuous 0-100 risk scoring + demo anchors
│   ├── predictions.py     # Per-component failure predictions
│   ├── alerts.py          # Synthesises Alert objects from alarm_events
│   ├── forecast.py        # Demand forecast + scenario engine
│   ├── kpis.py            # KPI rollups for the homepage
│   └── chat.py            # In-memory conversation store + reply stub
└── routers/               # One router file per resource
    ├── health.py          # GET /health
    ├── machines.py        # GET /machines, GET /machines/{id}
    ├── components.py      # GET /machines/{id}/components
    ├── risk.py            # GET /machines/{id}/risk-score, .../components/{cid}/risk-score, .../predictions
    ├── sensors.py         # GET /machines/{id}/sensors[, /{sensor}/history]
    ├── alerts.py          # GET /alerts, /alerts/{id}, /machines/{id}/alarms, /machines/{id}/maintenance-log
    ├── demand.py          # GET /products, /markets, /forecast, /demand/anomalies, /demand/seasonality + POST /forecast/scenario
    ├── chat.py            # POST /chat, GET/DELETE /chat/conversations/{id}, GET /chat/suggested-prompts
    └── kpis.py            # GET /kpis/overview, /kpis/cost-savings
```

The DB layer uses **asyncpg** (the relational `backend/postgres/db.py`
SQLAlchemy code is for the seeder; the API is fully async).

## Prerequisites

- Python 3.10+
- TimescaleDB Docker container running on `localhost:5433` with database
  `fhh_optimizers` (already seeded — see `backend/postgres/README.md`)
- `.env` at the project root with `DATABASE_URL` set:

  ```
  DATABASE_URL=postgresql://postgres:postgres123@localhost:5433/fhh_optimizers
  ```

  (Note: the API normalises SQLAlchemy-style URLs like
  `postgresql+psycopg2://...` to bare `postgresql://...`, so the same
  `.env` value works for the seeder *and* the API.)

## Install

From the project root:

```bash
pip install -r requirements.txt
```

The new dependencies added for the API layer:

```
fastapi>=0.110
uvicorn[standard]>=0.27
asyncpg>=0.29
pydantic>=2.5
```

## Run

From the project root:

```bash
uvicorn backend.api.main:app --reload --port 8000
```

Then open:

- Swagger UI:     <http://localhost:8000/docs>
- OpenAPI JSON:   <http://localhost:8000/openapi.json>
- Health check:   <http://localhost:8000/health>

## Smoke-test cURL

```bash
# 1. Health
curl -s http://localhost:8000/health | jq

# 2. List all machines
curl -s http://localhost:8000/machines | jq

# 3. One machine (Al Nakheel)
curl -s http://localhost:8000/machines/al-nakheel | jq

# 4. Machine risk score
curl -s http://localhost:8000/machines/al-nakheel/risk-score | jq

# 5. All 6 components for Al Nakheel (Yankee should be the critical one)
curl -s http://localhost:8000/machines/al-nakheel/components | jq

# 6. THE DEMO ANCHOR — Al Nakheel Yankee at 87% / critical
curl -s http://localhost:8000/machines/al-nakheel/components/yankee/risk-score | jq

# 7. Latest sensor readings
curl -s http://localhost:8000/machines/al-nakheel/sensors | jq

# 8. Sensor history (24h hourly)
curl -s 'http://localhost:8000/machines/al-nakheel/sensors/yankee_vibration_bearing_3/history?window=24h&aggregation=hourly' | jq

# 9. Failure predictions for the machine
curl -s http://localhost:8000/machines/al-nakheel/predictions | jq

# 10. Recent alarms (Valmet DCS)
curl -s 'http://localhost:8000/machines/al-nakheel/alarms?limit=10' | jq

# 11. Maintenance log
curl -s http://localhost:8000/machines/al-nakheel/maintenance-log | jq

# 12. All open alerts (sorted by severity)
curl -s 'http://localhost:8000/alerts?sort=severity' | jq

# 13. KPIs (homepage)
curl -s http://localhost:8000/kpis/overview | jq

# 14. Cost savings
curl -s 'http://localhost:8000/kpis/cost-savings?window=ytd' | jq

# 15. Demand catalog
curl -s http://localhost:8000/products | jq
curl -s http://localhost:8000/markets | jq

# 16. Forecast
curl -s 'http://localhost:8000/forecast?sku=fine-facial-100&market=uae&horizon_months=6' | jq

# 17. Scenario
curl -s -X POST http://localhost:8000/forecast/scenario \
  -H 'Content-Type: application/json' \
  -d '{
        "sku": "fine-facial-100",
        "market": "uae",
        "horizon_months": 6,
        "scenario": {"type":"seasonality_shift","event":"ramadan","magnitude_percent":30}
      }' | jq

# 18. Demand anomalies + seasonality
curl -s http://localhost:8000/demand/anomalies | jq
curl -s 'http://localhost:8000/demand/seasonality?sku=fine-facial-100&market=uae' | jq

# 19. Chat
curl -s http://localhost:8000/chat/suggested-prompts | jq
curl -s -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Why is Yankee on Al Nakheel red?",
       "context":{"current_page":"machine_detail","current_machine_id":"al-nakheel","current_component_id":"yankee"}}' | jq
```

## Risk scoring

Risk scores live in `services/risk.py`. The continuous 0-100 score combines:

| Signal                                        | Weight       |
| --------------------------------------------- | ------------ |
| Sensor anomaly density on the component (7d)  | up to 50 pts |
| Unresolved critical alarms on the machine     | up to 25 pts |
| Wear: hours-since-maintenance / lifetime      | up to 15 pts |
| Worst-sensor 24h-vs-7d trend                  | up to 10 pts |

Tiers (per the contract — tuned for **high recall on critical**, see
`reports/model_validation.md` → "Design Decision: High Recall over Precision"):

| Score range | Tier      |
| ----------- | --------- |
| 0–29        | healthy   |
| 30–49       | watch     |
| 50–69       | warning   |
| 70–100      | critical  |

The lower critical floor (70) is intentional. In safety-critical predictive
maintenance the cost of missing a real failure (downtime, equipment damage,
safety incidents) far exceeds the cost of a false alarm (an inspection),
so we accept more false positives to maximise recall.

**Demo anchors** — Al Nakheel / Yankee renders at **88 / critical / 48 h
failure window** with the trained ML pipeline. The heuristic-fallback
overrides live in `DEMO_COMPONENT_RISK` and `DEMO_MACHINE_RISK` in
`services/risk.py` for the case where the model artifacts haven't been
trained yet.

## Error shape

All errors follow the contract envelope:

```json
{ "error": { "code": "machine_not_found", "message": "...", "status": 404 } }
```

| HTTP | Code                   | When                                     |
| ---- | ---------------------- | ---------------------------------------- |
| 400  | `invalid_request`      | Bad query params or path values          |
| 404  | `machine_not_found`    | Unknown machine ID                       |
| 404  | `component_not_found`  | Unknown component ID for the machine     |
| 404  | `sku_not_found`        | Unknown SKU                              |
| 404  | `conversation_not_found` | Unknown chat conversation ID           |
| 422  | `validation_error`     | Pydantic validation failure              |
| 500  | `internal_error`       | Unhandled exception (logged with trace)  |

## Logging

`AccessLogMiddleware` emits one INFO line per request:

```
2026-04-28T08:21:14 | INFO    | fhh.api | method=GET path=/machines status=200 duration_ms=14.3
```

Unhandled exceptions print a 500 line plus a stack trace at ERROR level.

## Troubleshooting

**"DB connectivity check failed at startup"** — confirm the Docker
container is up and the DSN matches:

```bash
docker ps --filter name=fhh-ts
docker exec fhh-ts psql -U postgres -d fhh_optimizers -c '\dt'
```

**Empty / wrong sensor results** — confirm 5.88M sensor rows are present:

```bash
docker exec fhh-ts psql -U postgres -d fhh_optimizers -c \
  'SELECT COUNT(*) FROM sensor_readings;'
```

**TimescaleDB extension not active** — the `/health` endpoint returns
`status=degraded`. Re-create the extension:

```bash
docker exec fhh-ts psql -U postgres -d fhh_optimizers -c \
  'CREATE EXTENSION IF NOT EXISTS timescaledb;'
```

**Al Nakheel Yankee not at 87** — risk overrides are in
`backend/api/services/risk.py` (`DEMO_COMPONENT_RISK`). The contract
pins this combo, so the override is the single source of truth.

**`/forecast` returns `sku_not_found`** — the catalog has 37 SKUs (see
`backend/postgres/seed_data.py`). Use `GET /products` to list.

## Wiring the chat to Anthropic (next prompt)

`services/chat.py` returns a deterministic placeholder reply today. The
endpoint shapes (`POST /chat`, `GET/DELETE /chat/conversations/{id}`,
`GET /chat/suggested-prompts`) are correct so the frontend can integrate
now. Replacing `generate_reply` with an Anthropic Claude tool-use loop —
where each REST endpoint here is exposed as a tool — is the next prompt's
job.
