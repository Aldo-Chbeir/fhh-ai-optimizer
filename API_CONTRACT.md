# FHH AI Optimizer — API Contract v1.1
**Single source of truth for frontend ↔ backend integration**
*Paste this into Claude Design AND Claude Code at the start of every session.*

---

## How to use this document

**If you are Claude Design:** Build UI components that consume the JSON shapes defined here. Wire every dashboard element to the endpoint it depends on. Use the constants (machine IDs, component IDs, tier names) verbatim — never invent your own.

**If you are Claude Code:** Build FastAPI endpoints that return *exactly* these JSON shapes — same keys, same value types, same enum strings. Never rename a field, never change a casing convention. If a field is `score` returning an integer 0–100, it stays that way forever.

**Naming rules (non-negotiable):**
- All JSON keys: `snake_case`
- All timestamps: ISO 8601 UTC, e.g. `"2026-04-25T14:30:00Z"`
- All IDs: lowercase, hyphenated strings, e.g. `"al-nakheel"`
- All enums: lowercase strings exactly as listed below

---

## Constants & enums

### Machine IDs (4 total)
| ID | Name | Location |
|---|---|---|
| `al-nakheel` | Al Nakheel | Abu Dhabi, UAE |
| `al-bardi` | Al Bardi | Egypt |
| `al-sindian` | Al Sindian | Egypt |
| `al-snobar` | Al Snobar | Jordan |

### Component IDs (6 per machine, in line order)
| ID | Name | Critical? |
|---|---|---|
| `headbox` | OptiFlo II TIS Headbox | No |
| `visconip` | Advantage ViscoNip Press | Medium |
| `yankee` | Cast Alloy Yankee Cylinder | **Yes ($20K/hr)** |
| `aircap` | AirCap Hood with Air System | Medium |
| `softreel` | SoftReel Reel | No |
| `rewinder` | Focus Rewinder | No |

### Sensor types (12 streams per machine)
| ID | Component | Unit | Normal range |
|---|---|---|---|
| `yankee_surface_temp` | yankee | °C | 100–120 |
| `yankee_steam_pressure` | yankee | bar | 8–10 |
| `yankee_vibration_bearing_1` | yankee | mm/s | 2–4 |
| `yankee_vibration_bearing_2` | yankee | mm/s | 2–4 |
| `yankee_vibration_bearing_3` | yankee | mm/s | 2–4 |
| `yankee_blade_pressure` | yankee | kPa | 80–120 |
| `visconip_nip_pressure` | visconip | bar | 4–6 |
| `visconip_felt_moisture` | visconip | % | 35–45 |
| `aircap_inlet_temp` | aircap | °C | 480–520 |
| `aircap_energy` | aircap | kWh/ton | 1.8–2.4 |
| `headbox_stock_temp` | headbox | °C | 45–55 |
| `softreel_tension` | softreel | N/m | 180–220 |
| `rewinder_speed` | rewinder | m/min | 1800–2222 |
| `qcs_softness_index` | qcs | 0–100 scale | 70–90 |

### Risk tiers
| Tier | Score range | Color | Action |
|---|---|---|---|
| `healthy` | 0–30 | green | No action |
| `watch` | 30–60 | yellow | Schedule inspection |
| `warning` | 60–85 | orange | Schedule maintenance within 7 days |
| `critical` | 85–100 | red | Immediate intervention |

### Alarm severities
`info` · `warning` · `critical`

### Markets (5 total)
`jordan` · `egypt` · `uae` · `ksa` · `morocco`

### SKU categories
`tissue` · `baby_care` · `adult_care` · `fine_guard` · `wellness` · `cosmetics`

---

## Shared data shapes

### Machine object
```json
{
  "machine_id": "al-nakheel",
  "name": "Al Nakheel",
  "location": "Abu Dhabi, UAE",
  "model": "Valmet Advantage DCT 200TS",
  "installation_date": "2018-06-15",
  "status": "running",
  "current_speed_mpm": 2150,
  "current_oee_percent": 94.2,
  "risk_score": 67,
  "risk_tier": "warning",
  "active_alerts_count": 2
}
```
`status` enum: `running` · `idle` · `maintenance` · `offline`

### Component object
```json
{
  "component_id": "yankee",
  "machine_id": "al-nakheel",
  "name": "Cast Alloy Yankee Cylinder",
  "is_critical": true,
  "risk_score": 87,
  "risk_tier": "critical",
  "expected_lifetime_hours": 50000,
  "hours_since_last_maintenance": 4200,
  "last_maintenance_date": "2026-01-15"
}
```

### Sensor reading object
```json
{
  "sensor_type": "yankee_vibration_bearing_3",
  "machine_id": "al-nakheel",
  "component_id": "yankee",
  "value": 5.8,
  "unit": "mm/s",
  "timestamp": "2026-04-25T14:30:00Z",
  "is_anomaly": true
}
```

### Alert object
```json
{
  "alert_id": "alt-2026-04-25-0017",
  "machine_id": "al-nakheel",
  "component_id": "yankee",
  "severity": "critical",
  "risk_score": 87,
  "title": "Bearing 3 vibration trending toward failure",
  "description": "Bearing 3 vibration RMS rising 0.4 mm/s/day for 11 days. Predicted failure window: 48 hours.",
  "predicted_failure_window_hours": 48,
  "recommended_action": "Schedule bearing replacement in next planned downtime window. Stockpile spare bearing set BR-7842.",
  "estimated_cost_if_unaddressed_usd": 480000,
  "created_at": "2026-04-25T08:15:00Z",
  "acknowledged": false
}
```

### Forecast point object
```json
{
  "date": "2026-05-01",
  "forecast_value": 142000,
  "lower_bound": 128000,
  "upper_bound": 156000
}
```

---

## MODULE 1 — MAINTENANCE ENDPOINTS

### `GET /machines`
List all machines with current health summary.

**Query params:** none
**Response 200:**
```json
{
  "machines": [
    { /* Machine object */ },
    { /* Machine object */ },
    { /* Machine object */ },
    { /* Machine object */ }
  ],
  "total": 4
}
```

### `GET /machines/{machine_id}`
Single machine details.

**Path params:** `machine_id` (one of the 4 IDs)
**Response 200:** Machine object

---

### `GET /machines/{machine_id}/risk-score`
Machine-level aggregate risk score.

**Response 200:**
```json
{
  "machine_id": "al-nakheel",
  "score": 67,
  "tier": "warning",
  "highest_risk_component_id": "yankee",
  "last_updated": "2026-04-25T14:30:00Z"
}
```

---

### `GET /machines/{machine_id}/components`
List all 6 components for a machine with their individual health.

**Response 200:**
```json
{
  "machine_id": "al-nakheel",
  "components": [
    { /* Component object */ },
    { /* Component object */ }
    /* ...6 total, in line order: headbox → visconip → yankee → aircap → softreel → rewinder */
  ]
}
```

---

### `GET /machines/{machine_id}/components/{component_id}/risk-score`
**This is where component-level alerts live (e.g. "Bearing 3 on Al Nakheel").**

**Response 200:**
```json
{
  "machine_id": "al-nakheel",
  "component_id": "yankee",
  "score": 87,
  "tier": "critical",
  "predicted_failure_window_hours": 48,
  "top_contributing_sensors": [
    { "sensor_type": "yankee_vibration_bearing_3", "contribution_percent": 62 },
    { "sensor_type": "yankee_surface_temp", "contribution_percent": 18 },
    { "sensor_type": "yankee_steam_pressure", "contribution_percent": 12 }
  ],
  "last_updated": "2026-04-25T14:30:00Z"
}
```

---

### `GET /machines/{machine_id}/sensors`
Current (latest) reading for every sensor on the machine.

**Response 200:**
```json
{
  "machine_id": "al-nakheel",
  "readings": [
    { /* Sensor reading object */ }
    /* ...one per sensor type, 14 total */
  ],
  "last_updated": "2026-04-25T14:30:00Z"
}
```

---

### `GET /machines/{machine_id}/sensors/{sensor_type}/history`
Time-series history for a single sensor (for charts).

**Query params:**
- `window` — one of `1h` · `24h` · `7d` · `30d` (default `24h`)
- `aggregation` — one of `raw` · `hourly` · `daily` (default `hourly`)

**Response 200:**
```json
{
  "machine_id": "al-nakheel",
  "sensor_type": "yankee_vibration_bearing_3",
  "unit": "mm/s",
  "window": "7d",
  "aggregation": "hourly",
  "normal_range": { "min": 2.0, "max": 4.0 },
  "points": [
    { "timestamp": "2026-04-18T00:00:00Z", "value": 3.2, "min": 3.0, "max": 3.4 },
    { "timestamp": "2026-04-18T01:00:00Z", "value": 3.3, "min": 3.1, "max": 3.5 }
    /* ... */
  ]
}
```

---

### `GET /machines/{machine_id}/predictions`
Failure predictions across all components on the machine.

**Response 200:**
```json
{
  "machine_id": "al-nakheel",
  "predictions": [
    {
      "component_id": "yankee",
      "failure_probability": 0.87,
      "predicted_failure_window_hours": 48,
      "confidence": 0.82,
      "recommended_action": "Schedule bearing replacement in next planned downtime window."
    },
    {
      "component_id": "visconip",
      "failure_probability": 0.12,
      "predicted_failure_window_hours": null,
      "confidence": 0.78,
      "recommended_action": "Continue monitoring. No action required."
    }
    /* ...one per component */
  ],
  "generated_at": "2026-04-25T14:30:00Z"
}
```

---

### `GET /machines/{machine_id}/alarms`
Recent alarm events from Valmet DNA DCS.

**Query params:**
- `limit` (default 50)
- `severity` (optional filter: `info` · `warning` · `critical`)

**Response 200:**
```json
{
  "machine_id": "al-nakheel",
  "alarms": [
    {
      "alarm_id": "alm-2026-04-25-0083",
      "timestamp": "2026-04-25T13:45:00Z",
      "severity": "warning",
      "description": "Yankee bearing 3 vibration above 5.0 mm/s threshold",
      "resolved_at": null,
      "downtime_minutes": 0
    }
  ],
  "total": 1
}
```

---

### `GET /machines/{machine_id}/maintenance-log`
Maintenance history for the machine.

**Response 200:**
```json
{
  "machine_id": "al-nakheel",
  "logs": [
    {
      "log_id": "mlog-2026-01-15-001",
      "component_id": "yankee",
      "maintenance_type": "preventive",
      "date_performed": "2026-01-15",
      "cost_usd": 12500,
      "downtime_hours": 6,
      "technician": "M. Khalil",
      "notes": "Replaced creping blade. Vibration baseline reset."
    }
  ]
}
```
`maintenance_type` enum: `preventive` · `corrective` · `predictive` · `emergency`

---

### `GET /alerts`
All active alerts across all machines (alerts page).

**Query params:**
- `severity` (optional)
- `machine_id` (optional)
- `acknowledged` (optional bool)
- `sort` — one of `severity` · `created_at` · `risk_score` (default `severity`)

**Response 200:**
```json
{
  "alerts": [
    { /* Alert object */ }
  ],
  "total": 5,
  "counts_by_tier": {
    "critical": 1,
    "warning": 2,
    "watch": 2
  }
}
```

---

### `GET /alerts/{alert_id}`
Single alert detail.

**Response 200:** Alert object

---

## MODULE 2 — PREDICTIVE (DEMAND) ENDPOINTS

### `GET /products`
List all 37 SKUs.

**Response 200:**
```json
{
  "products": [
    {
      "sku": "fine-facial-100",
      "name": "Fine Facial Tissue 100ct",
      "category": "tissue",
      "unit": "box"
    }
    /* ...37 total */
  ],
  "total": 37
}
```

---

### `GET /markets`
List all 5 markets.

**Response 200:**
```json
{
  "markets": [
    { "market_id": "uae", "name": "United Arab Emirates", "currency": "AED" },
    { "market_id": "ksa", "name": "Saudi Arabia", "currency": "SAR" },
    { "market_id": "jordan", "name": "Jordan", "currency": "JOD" },
    { "market_id": "egypt", "name": "Egypt", "currency": "EGP" },
    { "market_id": "morocco", "name": "Morocco", "currency": "MAD" }
  ]
}
```

---

### `GET /forecast`
Demand forecast for a SKU × market combo.

**Query params (all required):**
- `sku` — product ID
- `market` — market ID
- `horizon_months` — integer 1–12 (default 6)

**Response 200:**
```json
{
  "sku": "fine-facial-100",
  "market": "uae",
  "horizon_months": 6,
  "model": "prophet",
  "forecast": [
    { "date": "2026-05-01", "forecast_value": 142000, "lower_bound": 128000, "upper_bound": 156000 }
    /* ...one point per month */
  ],
  "seasonality_events": [
    { "date": "2026-03-10", "label": "Ramadan begins", "expected_lift_percent": 35 },
    { "date": "2026-04-09", "label": "Eid al-Fitr", "expected_lift_percent": 22 }
  ],
  "regressors_used": ["historical_sales", "ramadan_calendar", "b2b_pipeline"],
  "generated_at": "2026-04-25T14:30:00Z"
}
```

---

### `POST /forecast/scenario`
Scenario planner — "what if Ramadan demand +30%?"

**Request body:**
```json
{
  "sku": "fine-facial-100",
  "market": "uae",
  "horizon_months": 6,
  "scenario": {
    "type": "seasonality_shift",
    "event": "ramadan",
    "magnitude_percent": 30
  }
}
```
`scenario.type` enum: `seasonality_shift` · `price_change` · `competitor_entry` · `supply_disruption`

**Response 200:**
```json
{
  "baseline_forecast": [ /* ...forecast points */ ],
  "scenario_forecast": [ /* ...forecast points */ ],
  "delta_summary": {
    "total_baseline_units": 850000,
    "total_scenario_units": 1020000,
    "delta_units": 170000,
    "delta_percent": 20
  }
}
```

---

### `GET /demand/anomalies`
Recent demand anomalies flagged by the model.

**Response 200:**
```json
{
  "anomalies": [
    {
      "anomaly_id": "anm-2026-04-22-003",
      "sku": "fine-baby-s3",
      "market": "ksa",
      "detected_at": "2026-04-22",
      "type": "spike",
      "magnitude_percent": 47,
      "explanation": "Sales 47% above expected — possible distributor restocking or demand surge."
    }
  ]
}
```
`type` enum: `spike` · `dip` · `trend_break`

---

### `GET /demand/seasonality`
Seasonality breakdown for a SKU.

**Query params:** `sku` (required), `market` (optional)

**Response 200:**
```json
{
  "sku": "fine-facial-100",
  "market": "uae",
  "yearly_pattern": [
    { "month": 1, "index": 0.92 },
    { "month": 2, "index": 0.95 }
    /* ...12 months, 1.0 = average */
  ],
  "events": [
    { "name": "ramadan", "average_lift_percent": 35 },
    { "name": "eid_al_fitr", "average_lift_percent": 22 },
    { "name": "back_to_school", "average_lift_percent": 12 }
  ]
}
```

---

## CROSS-CUTTING ENDPOINTS

### `GET /kpis/overview`
Top dashboard KPIs (homepage hero strip).

**Response 200:**
```json
{
  "fleet_avg_oee_percent": 93.7,
  "active_critical_alerts": 1,
  "active_warning_alerts": 2,
  "predicted_downtime_prevented_hours_mtd": 14,
  "estimated_cost_saved_usd_mtd": 280000,
  "machines_running": 3,
  "machines_total": 4,
  "last_updated": "2026-04-25T14:30:00Z"
}
```

---

### `GET /kpis/cost-savings`
ROI tracker — cumulative savings from predicted-and-prevented failures.

**Query params:** `window` — one of `mtd` · `qtd` · `ytd` · `all` (default `ytd`)

**Response 200:**
```json
{
  "window": "ytd",
  "total_predictions": 23,
  "predictions_acted_on": 18,
  "estimated_downtime_hours_prevented": 47,
  "estimated_cost_saved_usd": 940000,
  "breakdown_by_machine": [
    { "machine_id": "al-nakheel", "cost_saved_usd": 480000 },
    { "machine_id": "al-bardi", "cost_saved_usd": 220000 },
    { "machine_id": "al-sindian", "cost_saved_usd": 160000 },
    { "machine_id": "al-snobar", "cost_saved_usd": 80000 }
  ]
}
```

---

## MODULE 3 — CHAT / AI ASSISTANT

The chat sidebar is **always visible** on every screen. It's the user's natural-language interface to the entire tool. The user types questions in plain English; the assistant reads live data from the other endpoints and explains it.

**Implementation note for backend:** the chat endpoint internally calls the Anthropic API (Claude) and gives Claude the other endpoints in this contract as **tools**. The assistant fetches real data on demand — it does not hallucinate metrics.

### `POST /chat`
Send a user message, get an assistant reply.

**Request body:**
```json
{
  "message": "Why is Yankee on Al Nakheel red?",
  "conversation_id": "conv-abc123",
  "context": {
    "current_page": "machine_detail",
    "current_machine_id": "al-nakheel",
    "current_component_id": "yankee",
    "current_sku": null,
    "current_market": null
  }
}
```

`current_page` enum: `overview` · `machine_detail` · `alerts` · `demand_forecast`

`conversation_id` — if omitted or null, the server creates a new conversation and returns the new ID. If provided, the server resumes that conversation with prior message history.

`context` — all fields optional. Lets the assistant know what the user is currently looking at, so a question like *"why is this red?"* resolves correctly.

**Response 200 (non-streaming):**
```json
{
  "conversation_id": "conv-abc123",
  "reply": "Yankee on Al Nakheel is at 87% risk because Bearing 3 vibration has been climbing 0.4 mm/s/day for 11 days. Current reading is 5.8 mm/s; normal range is 2-4 mm/s. The model predicts failure within the next 48 hours. Recommended action: schedule bearing replacement during the next downtime window. Estimated cost if ignored: $480,000.",
  "data_sources_used": [
    "machines/al-nakheel/components/yankee/risk-score",
    "machines/al-nakheel/sensors/yankee_vibration_bearing_3/history"
  ],
  "suggested_followups": [
    "Compare Bearing 3 to the same bearing on Al Snobar",
    "What if I delay the replacement by 3 days?",
    "Show me the maintenance history for this component"
  ],
  "timestamp": "2026-04-25T14:30:00Z"
}
```

**Response (streaming, optional):**
If the client sets header `Accept: text/event-stream`, the server streams the reply as Server-Sent Events:
```
event: token
data: {"text": "Yankee "}

event: token
data: {"text": "on Al Nakheel "}

event: data_source
data: {"endpoint": "machines/al-nakheel/components/yankee/risk-score"}

event: done
data: {"conversation_id": "conv-abc123", "suggested_followups": [...]}
```

---

### `GET /chat/conversations/{conversation_id}`
Retrieve a conversation history (e.g. when the user reopens the sidebar).

**Response 200:**
```json
{
  "conversation_id": "conv-abc123",
  "created_at": "2026-04-25T14:25:00Z",
  "messages": [
    {
      "role": "user",
      "content": "Why is Yankee on Al Nakheel red?",
      "timestamp": "2026-04-25T14:25:00Z"
    },
    {
      "role": "assistant",
      "content": "Yankee on Al Nakheel is at 87% risk...",
      "timestamp": "2026-04-25T14:25:03Z",
      "data_sources_used": [
        "machines/al-nakheel/components/yankee/risk-score"
      ]
    }
  ]
}
```

---

### `DELETE /chat/conversations/{conversation_id}`
Clear a conversation (user clicks "New chat").

**Response 204:** (no body)

---

### `GET /chat/suggested-prompts`
Returns context-aware suggested prompts shown as clickable chips at the bottom of the chat sidebar when the conversation is empty.

**Query params:** `current_page` (optional), `current_machine_id` (optional), `current_sku` (optional)

**Response 200:**
```json
{
  "prompts": [
    "What's wrong with Al Nakheel right now?",
    "Compare risk across all 4 machines",
    "When should I schedule the next maintenance window?",
    "How will Ramadan affect production capacity?"
  ]
}
```

The backend may rotate or personalize these. The frontend simply displays whatever the endpoint returns.

---

## Error responses

All error responses follow this shape:
```json
{
  "error": {
    "code": "machine_not_found",
    "message": "No machine exists with ID 'al-foo'.",
    "status": 404
  }
}
```

**Standard error codes:**
| HTTP | Code | When |
|---|---|---|
| 400 | `invalid_request` | Bad query params or body |
| 404 | `machine_not_found` | Unknown machine ID |
| 404 | `component_not_found` | Unknown component ID |
| 404 | `sku_not_found` | Unknown SKU |
| 404 | `conversation_not_found` | Unknown chat conversation ID |
| 422 | `validation_error` | Body validation failed |
| 429 | `rate_limited` | Too many chat requests in short window |
| 500 | `internal_error` | Unexpected server error |
| 503 | `model_unavailable` | AI model not loaded yet |
| 503 | `chat_unavailable` | Anthropic API unreachable or quota exceeded |

---

## Frontend integration cheat sheet

**Global (every page — chat sidebar is always visible):**
1. `GET /chat/suggested-prompts?current_page=...` — when conversation is empty, show as clickable chips
2. `POST /chat` — on user message submit (pass current page context)
3. `GET /chat/conversations/{id}` — when user reopens sidebar to resume conversation
4. `DELETE /chat/conversations/{id}` — when user clicks "New chat"

**Layout note:** the chat sidebar occupies the right ~25–30% of every screen at all times. The main content (overview, machine detail, alerts, demand) lives in the remaining ~70–75% on the left.

**Homepage (overview dashboard):**
1. `GET /kpis/overview` — top stat strip
2. `GET /machines` — 4 machine cards (each card already has `risk_score` and `risk_tier`)
3. `GET /alerts?severity=critical&limit=3` — alert ticker

**Machine detail page:**
1. `GET /machines/{id}` — header info
2. `GET /machines/{id}/components` — 6-component health row
3. `GET /machines/{id}/predictions` — failure prediction cards
4. `GET /machines/{id}/sensors` — live current readings
5. `GET /machines/{id}/sensors/{sensor_type}/history?window=24h` — chart per sensor
6. `GET /machines/{id}/alarms?limit=10` — recent alarms table
7. `GET /machines/{id}/maintenance-log` — maintenance history

**Alerts page:**
1. `GET /alerts?sort=severity` — main list
2. Click row → `GET /alerts/{alert_id}` for detail drawer

**Demand forecast page:**
1. `GET /products` — SKU dropdown
2. `GET /markets` — market dropdown
3. `GET /forecast?sku=...&market=...&horizon_months=6` — main chart
4. `GET /demand/seasonality?sku=...` — seasonality side panel
5. `POST /forecast/scenario` — when user runs a scenario

**ROI / cost savings page:**
1. `GET /kpis/cost-savings?window=ytd` — main figure + breakdown

---

## Versioning & change log

**v1.1** — 2026-04-25 — Added Module 3 (Chat / AI Assistant): `POST /chat`, `GET /chat/conversations/{id}`, `DELETE /chat/conversations/{id}`, `GET /chat/suggested-prompts`. Chat sidebar is always visible on every screen. Added `conversation_not_found`, `rate_limited`, `chat_unavailable` error codes.

**v1.0** — 2026-04-25 — Initial contract.

**Rule:** any breaking change to a field name, type, or enum value bumps the version number and gets logged here. No silent renames. Ever.

---

*End of contract. Lock this file in the repo as `API_CONTRACT.md`. Both Claude Design and Claude Code reference this file at the start of every session.*
