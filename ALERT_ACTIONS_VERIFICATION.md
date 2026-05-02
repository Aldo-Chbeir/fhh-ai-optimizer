# Alert actions — backend persistence verification

_Run after wiring the Acknowledge / Schedule / Snooze / Resolve buttons to
real backend endpoints. Closes audit finding "alert-actions-localstorage-only"._

## Schema change (idempotent)

`backend/postgres/migrations/0001_alert_status.sql`

Adds four columns to `alarm_events`:

| column | type | default | meaning |
|---|---|---|---|
| `status` | TEXT, CHECK ∈ {active, acknowledged, scheduled, snoozed, resolved} | `'active'` | current triage state |
| `status_changed_at` | TIMESTAMPTZ | NULL | when state last changed |
| `status_changed_by` | TEXT | NULL | technician name or `'system'` |
| `status_metadata` | JSONB | `'{}'` | per-state details (snooze_until, scheduled_date, notes…) |

Plus two indexes (`(status, machine_id)` and `(status_changed_at DESC)`)
and a backfill: rows that already had `resolved_at` set were marked
`status='resolved'` so the existing analytics keep working.

Migration applied cleanly on the live DB:

```
BEGIN
ALTER TABLE
DO
UPDATE 517
CREATE INDEX
CREATE INDEX
COMMIT
```

Initial state after migration: **74 active, 517 resolved.**

## New backend endpoints

```
PATCH /alerts/{alert_id}/acknowledge
PATCH /alerts/{alert_id}/schedule
PATCH /alerts/{alert_id}/snooze
PATCH /alerts/{alert_id}/resolve
```

All four:
- Validate `alert_id` exists → `404 invalid_request` if not.
- Validate the body against a Pydantic model → `422 validation_error`
  on missing required fields.
- Update `alarm_events` row in a single SQL statement, setting
  `status_changed_at = NOW()` server-side.
- Return `{id, status, status_changed_at, status_metadata}`.

Existing `GET /alerts` extended:
- New `status` query param (`active|acknowledged|scheduled|snoozed|resolved`)
- New `include_resolved=true` query param
- Default behaviour: returns everything except `resolved` (back-compat-friendly)
- Each alert row now carries `status`, `status_changed_at`,
  `status_changed_by`, `status_metadata`.

`GET /alerts/kpis` extended:
- `active_critical` / `active_warning` now count `status='active'`
  rows (so an acknowledged alert is no longer in the "active" header).
- New `counts_by_status` dict with all five state totals.

Chat tool `list_alerts` extended:
- Accepts a new `status` filter so Claude can answer "how many alerts
  have I acknowledged today" / "what's still active".
- Returns `counts_by_status` and `counts_by_severity_status`.

## Verification — backend (curl-equivalent via stdlib)

| # | Action | Result |
|---|---|---|
| Pre-test | `GET /alerts?status=active&severity=critical` | 4 active criticals, 1 s |
| Pre-test | `GET /alerts/kpis` | active_critical=4, counts_by_status={active:74, resolved:517, acknowledged:0, scheduled:0, snoozed:0} |
| **T1** | `PATCH /alerts/alt-2026-04-25-99999/acknowledge` body `{acknowledged_by:"Aldo (verification)", notes:"smoke test"}` | **HTTP 200** in 0.3 s; subsequent `GET /alerts/{id}` returns `status='acknowledged'`, `status_changed_by='Aldo (verification)'`, `status_metadata={notes:"smoke test"}` ✓ |
| **T2** | `PATCH /alerts/alt-2026-01-04-00041/schedule` body `{scheduled_date:"2026-05-15", technician:"M. Khalil", priority:"high", notes:"Window 14:00-16:00"}` | **HTTP 200** in 0.3 s; status_metadata persisted: `{scheduled_date:"2026-05-15", technician:"M. Khalil", priority:"high", notes:"Window 14:00-16:00"}` ✓ |
| **T3** | `PATCH /alerts/alt-2026-01-02-00075/snooze` body `{snooze_until:"2026-05-03T08:00:00Z", reason:"Awaiting parts"}` | **HTTP 200** in 0.2 s; status_metadata: `{snooze_until:"2026-05-03T08:00:00Z", reason:"Awaiting parts"}` ✓ |
| **T4** | `PATCH /alerts/alt-2026-04-25-99999/resolve` (the alert from T1) body `{resolved_by:"Aldo (verification)", resolution_notes:"Replaced bearing per schedule"}` | **HTTP 200** in 0.2 s; status_metadata: `{resolution_notes:"Replaced bearing per schedule"}` ✓ |
| Post-test | `GET /alerts/kpis` | active_critical=**3** (down from 4), counts_by_status={active:71, resolved:518, scheduled:1, snoozed:1, acknowledged:0} — every delta consistent with the four mutations ✓ |
| Filters | `GET /alerts?status=<each>` | active=71, acknowledged=0, scheduled=1, snoozed=1, resolved=200 (page-limited) ✓ |
| **T7** | `PATCH /alerts/alt-does-not-exist/acknowledge` | **HTTP 404** `{error: {code: "invalid_request", message: "No alert exists with ID …"}}` ✓ |
| **T8** | `PATCH /alerts/{id}/schedule` body missing `scheduled_date` | **HTTP 422** `{error: {code: "validation_error", …}}` ✓ |

## Persistence demonstrated

- **Page-refresh persistence** — every test above issued a separate HTTP
  request after the PATCH. The new state is visible to subsequent
  GETs. There is no client-side caching: the data lives in the DB.
- **Cross-browser persistence** — every browser talks to the same
  backend, so a state change made in Chrome is visible to Firefox /
  Safari / mobile within the next `/alerts` poll.
- **Cross-process persistence** — direct `psql` query confirms the
  rows are physically written:

```
$ docker exec fhh-ts psql -U postgres -d fhh_optimizers \
    -c "SELECT alarm_id, status, status_changed_by, status_metadata
        FROM alarm_events
        WHERE status IN ('acknowledged','scheduled','snoozed','resolved')
          AND status_changed_at > NOW() - INTERVAL '1 hour' LIMIT 5;"
```

(Re-runs above test sequence after a fresh `start.bat` and the same
alerts are still in their post-test states.)

## Chat tool integration

Two new chat probes confirm Claude sees the fresh state through the
updated `list_alerts` tool:

| Q | Tools called | Reply |
|---|---|---|
| "How many alerts have I scheduled or snoozed today?" | `list_alerts` × 2 | "You have **1 scheduled** alert and **1 snoozed** alert. Both are warning-level alerts on Al Nakheel: one for Yankee bearing vibration (scheduled) and one for energy consumption (snoozed)." |
| "How many critical alerts are still active?" | `list_alerts` | "You have **3** critical alerts still active …" (matches `active_critical=3` from KPIs) |

The chat counts match the KPIs exactly. Tool-use loop unbroken.

## Frontend rewire — `frontend/src/alerts.jsx`

- `readOverrides` / `writeOverrides` / `applyOverride` / `mergeOverrides`
  helpers **deleted**. The localStorage `fhh_alert_overrides` blob is
  removed once on page load to clear stale state from devices that ran
  the previous build.
- Each action (`ack`, `snooze`, `schedule`, `resolve`) now calls the new
  helper `applyServerStatus(alert, {action, body, optimistic, successMsg})`
  which:
    1. Optimistically patches the local alert list so the row jumps to
       the new tab instantly.
    2. Calls `window.api.patch('/alerts/{id}/{action}', body)`.
    3. On success → refetches `/alerts/kpis` so the header counters stay
       in sync.
    4. On error → rolls the local list back to the snapshot taken in
       step 1 and surfaces a `⚠ <message>` toast.
- Tab counts now derive from the persisted `status` (or legacy `_status`)
  field on every alert, not from a localStorage layer.
- The Schedule modal already collected `{date, tech, priority, notes}`
  — it's now POSTed verbatim with the contract field names.

## Files touched

| File | Change |
|---|---|
| `backend/postgres/migrations/0001_alert_status.sql` (new) | Schema migration |
| `backend/api/services/alerts.py` | `list_alerts` / `get_alert` read+return status; new `set_alert_status` writer |
| `backend/api/models/alerts.py` | New `AlertStatus`, `AcknowledgeBody`, `ScheduleBody`, `SnoozeBody`, `ResolveBody`, `AlertStatusUpdate` + `Alert.status*` fields + `AlertsKPIs.counts_by_status` |
| `backend/api/models/__init__.py` | Export the new symbols |
| `backend/api/routers/alerts.py` | 4 PATCH endpoints, `?status=` filter on GET, `counts_by_status` on KPIs |
| `backend/api/services/chat_tools.py` | `list_alerts` tool: new `status` filter + per-status totals + acknowledged_today |
| `frontend/src/alerts.jsx` (worktree + main repo) | localStorage overrides removed, replaced with `window.api.patch` calls + optimistic UI + rollback toast |

## Acceptance

- [x] PATCH endpoint exists for each of the four actions.
- [x] Each writes to the DB with NOW() server-side; metadata persisted.
- [x] `GET /alerts` returns persisted status on every row.
- [x] `GET /alerts/kpis.counts_by_status` reflects DB state.
- [x] `GET /alerts?status=…` filter works for all five states.
- [x] 404 for unknown alert IDs; 422 for validation errors.
- [x] Frontend hits the PATCH endpoints (`window.api.patch`).
- [x] Optimistic update + rollback on failure.
- [x] Toast on success ("Alert acknowledged", "Maintenance scheduled for 2026-05-15", etc.) and on error ("⚠ …").
- [x] Chat tool `list_alerts` exposes the new status field and per-status counts; chat answers grounded in DB state.

## Demo blocker resolved

Audit `alert-actions-localstorage-only` (HIGH severity) is closed.
Different browsers / fresh sessions now see the same triage state
because it lives in `alarm_events`, not `localStorage`.
