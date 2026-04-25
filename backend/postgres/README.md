# PostgreSQL — relational layer

This folder owns the **relational** half of the FHH AI Optimizer data model.
Field names, IDs, and enum values are taken verbatim from
[`API_CONTRACT.md`](../../API_CONTRACT.md) v1.1 — never improvise here, the
contract is the single source of truth.

Sensor time-series live in a separate **TimescaleDB** layer (next folder
to be built); risk scores derived from sensor data are placeholder
constants in `db.py` until that layer lands.

## Tables

| Table              | Purpose                                                |
| ------------------ | ------------------------------------------------------ |
| `machines`         | 4 paper machines (al-nakheel, al-bardi, al-sindian, al-snobar) |
| `components`       | 6 components per machine, in line order                |
| `production_runs`  | One row per shift (morning / afternoon / night)        |
| `maintenance_logs` | Preventive / corrective / predictive / emergency work  |
| `alarm_events`     | Valmet DNA DCS alarms (info / warning / critical)      |
| `quality_scans`    | QCS readings (hourly per active run)                   |
| `products`         | 37 SKUs across 6 categories                            |
| `markets`          | 5 MENA markets                                         |

## Local setup (Docker)

`docker-compose.yml` snippet — drop into the project root:

```yaml
services:
  postgres:
    image: postgres:16
    container_name: fhh-postgres
    environment:
      POSTGRES_USER: fhh
      POSTGRES_PASSWORD: fhh
      POSTGRES_DB: fhh_optimizer
    ports:
      - "5432:5432"
    volumes:
      - fhh_pg_data:/var/lib/postgresql/data
volumes:
  fhh_pg_data:
```

Bring it up:

```bash
docker compose up -d postgres
```

## Environment

`db.py` reads `DATABASE_URL` from the environment (loads `.env` automatically
via `python-dotenv`). Default if unset:

```
postgresql+psycopg2://fhh:fhh@localhost:5432/fhh_optimizer
```

For local development, create a `.env` at the project root:

```
DATABASE_URL=postgresql+psycopg2://fhh:fhh@localhost:5432/fhh_optimizer
```

## Install Python dependencies

From the project root:

```bash
pip install -r requirements.txt
```

## 1 — apply the schema

```bash
psql "$DATABASE_URL" -f backend/postgres/schema.sql
```

Or with the Docker container directly:

```bash
docker exec -i fhh-postgres psql -U fhh -d fhh_optimizer < backend/postgres/schema.sql
```

## 2 — seed the data

```bash
cd backend/postgres
python seed_data.py            # populate
python seed_data.py --truncate # wipe + re-populate
python seed_data.py --count    # dry-run; print expected counts only
```

The seeder is deterministic (`random.seed(42)`) so the demo narrative —
Al Nakheel Yankee at 87% / critical with an unresolved bearing-3 alarm — is
reproducible across runs.

## 3 — verify

Total rows seeded should be **≈19,800** with the breakdown below:

```sql
SELECT 'machines'         AS table, COUNT(*) FROM machines
UNION ALL SELECT 'components',        COUNT(*) FROM components
UNION ALL SELECT 'production_runs',   COUNT(*) FROM production_runs
UNION ALL SELECT 'maintenance_logs',  COUNT(*) FROM maintenance_logs
UNION ALL SELECT 'alarm_events',      COUNT(*) FROM alarm_events
UNION ALL SELECT 'quality_scans',     COUNT(*) FROM quality_scans
UNION ALL SELECT 'products',          COUNT(*) FROM products
UNION ALL SELECT 'markets',           COUNT(*) FROM markets;
```

Expected order of magnitude:

| Table              | Rows    |
| ------------------ | ------: |
| machines           |       4 |
| components         |      24 |
| production_runs    |  ~2,094 |
| maintenance_logs   |     ~80 |
| alarm_events       |     591 |
| quality_scans      | ~16,752 |
| products           |      37 |
| markets            |       5 |
| **TOTAL**          | **~19,587** |

Spot-check the demo narrative:

```sql
-- Al Nakheel Yankee should be the worst-off component
SELECT machine_id, component_id, hours_since_last_maintenance, last_maintenance_date
FROM components
WHERE machine_id = 'al-nakheel' AND component_id = 'yankee';
-- → 4200 hrs since 2026-01-15

-- And there's an unresolved critical bearing-3 alarm waiting to surface
SELECT alarm_id, severity, description
FROM alarm_events
WHERE machine_id = 'al-nakheel' AND resolved_at IS NULL AND severity = 'critical'
ORDER BY timestamp DESC LIMIT 1;
```

## Use from Python

```python
from backend.postgres.db import get_machine_status, get_machine_components

get_machine_status("al-nakheel")
# → {'machine_id': 'al-nakheel', 'name': 'Al Nakheel', ..., 'risk_score': 67, 'risk_tier': 'warning', ...}

get_machine_components("al-nakheel")
# → [{'component_id': 'headbox', ...}, ..., {'component_id': 'yankee', 'risk_score': 87, 'risk_tier': 'critical', ...}, ...]
```

Both functions return dicts shaped to drop straight into a FastAPI response.
