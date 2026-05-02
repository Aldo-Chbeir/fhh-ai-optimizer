# FHH AI Optimizer — Audit Report

_Generated: 2026-05-02 — backend at `http://localhost:8000`, frontend at `http://localhost:8080`._

This is a **read-only audit**. No code was changed. Severity ratings reflect demo-readiness — what would a stakeholder notice in a 5-minute walkthrough?

---

## ✅ Working as expected

### Plumbing
- All 19 endpoints the frontend calls return HTTP 200 against the live DB.
- CORS configuration is correct — frontend at `:8080` reaches backend at `:8000` cleanly. No CORS errors in the network code.
- `api_client.jsx` wraps every request with a 15-s `AbortController` timeout, structured error envelope (`status` / `body` / `endpoint`), and a `networkError` flag.
- `start.bat` / `stop.bat` work from both the main repo root and the worktree (verified by reading the script logic, not by executing).

### Overview
- KPI strip reads exactly the fields the contract returns (`fleet_avg_oee_percent`, `active_critical_alerts`, `active_warning_alerts`, `estimated_cost_saved_usd_mtd`, `predicted_downtime_prevented_hours_mtd`, `machines_running`, `machines_total`, `last_updated`). All field names match.
- Four machine cards render with real `risk_score` / `risk_tier` / `current_speed_mpm` / `current_oee_percent` / `active_alerts_count` from `/machines`.
- Critical-alert banner reads `a.machine_id`, `a.component_id`, `a.title`, `a.risk_score`, `a.predicted_failure_window_hours` — all present on the backend response.
- Click-through from a machine card → Machine Detail works (sets `currentMachine` + flips page to `machine_detail`).

### Machine Detail
- All seven endpoints fire on mount: `/machines/{id}`, `/{id}/risk-score`, `/{id}/components`, `/{id}/predictions`, `/{id}/alarms?limit=5`, `/{id}/maintenance-log`. Field accessors (`m.current_speed_mpm`, `c.risk_score`, `c.risk_tier`, `c.is_critical`, `c.hours_since_last_maintenance`, `l.maintenance_type`, `l.cost_usd`, `l.downtime_hours`, `prediction.failure_probability`, `prediction.confidence`) all match the backend response shape.
- **Demo anchor verified**: `GET /machines/al-nakheel/components/yankee/risk-score` → `score=88, tier=critical, predicted_failure_window_hours=48`, with `top_contributing_sensors` listing `yankee_vibration_bearing_3` at 76 % and `yankee_surface_temp` at 24 %.
- Component drilldown (sensor mini-charts) reads `p.value` / `p.min` / `p.max` from `/sensors/{type}/history` — shape matches.
- `RiskGauge` reads `risk.score`, `risk.tier`, `risk.highest_risk_component_id` — all in the backend response.

### Alerts
- `/alerts/kpis` UI extension returns the full counters + sparkline shape the screen expects (verified field-by-field).
- `/alerts?sort=created_at` returns a list with all 12 contract fields per alert (`alert_id`, `severity`, `risk_score`, `title`, `description`, `predicted_failure_window_hours`, `recommended_action`, `estimated_cost_if_unaddressed_usd`, `created_at`, `acknowledged`, etc.).
- Filter and sort dropdowns, search input, bulk-select, and the four status tabs (Active / Acknowledged / Snoozed / Scheduled / Resolved) all wire to local state correctly.
- Defensive `_status || "active"` fallback for fresh alerts that haven't been acted on.

### Demand Forecast
- `/products` returns 37 SKUs, `/markets` returns 5. Both populate the dropdowns.
- `/forecast` returns `{sku, market, horizon_months, model, forecast[], seasonality_events[], regressors_used[], generated_at}` exactly as the contract specifies.
- `/demand/seasonality` returns `{sku, market, yearly_pattern[], events[]}` with the right nested shapes.
- `enrichForecast()` shim (added in an earlier prompt) handles the missing `history` / `accuracy` / `drivers` fields cleanly.
- Trend clamp (±25 %) suppresses misleading numbers — verified in 3/7 sampled SKU/market combos hitting the clamp and rendering "—".
- Y-axis nice-number rounding works against real `forecast_value` peaks (200,788 → yMax 250 000, step 50 000).
- Persistent user prefs in `localStorage`: market, sku, horizon, sliders, scenario state. Survives page refresh.

### Chat
- POST /chat round-trips through Anthropic in ≈ 5 s for a typical question. Returns the contract envelope (`conversation_id`, `reply`, `data_sources_used`, `suggested_followups`, `timestamp`).
- 502 / `chat_unavailable` fallback path preserved if the API key is missing.
- `+ New chat` button issues `DELETE /chat/conversations/{id}` and resets local state.
- Cold-start prompts vary correctly per `current_page` (overview / machine_detail / alerts / demand_forecast).
- `Q3` test ("Quote bearing cost in SAR") — the model **correctly refused** rather than inventing a number. Good guardrail behaviour for a question outside its data.

---

## 🚩 Bugs found

### `chat-hallucinates-demo-anchor` — `chat.jsx` + `services/chat.py` system prompt — **CRITICAL** — fix complexity: **medium**
**Q1 of the 3-prompt chat test:**
> "What is the current risk score for the Yankee on Al-Nakheel?"
>
> Claude replied: "...currently has a **risk score of 72** (Critical tier)..."

Actual value (from `/machines/al-nakheel/components/yankee/risk-score`) is **88**. The model fabricated **72** because the system prompt mentions the threshold ≥70 — Claude inferred a plausible-sounding number on top of that hint.

`data_sources_used` came back as `["maintenance_risk_scores", "sensor_telemetry"]` — these are **not** real contract endpoint paths. The model invented them. There is no tool-use loop or RAG context — Claude has no way to actually read live data, only the static fleet description in the system prompt. Result: any factual question about a specific number gets answered with plausible fiction.

This is the demo's marquee feature. Asking "Why is Yankee at 88?" right now produces a confident, wrong answer. **Demo blocker.**

### `chat-no-refresh-persistence` — `chat.jsx` — **HIGH** — fix complexity: **small**
Chat conversations live entirely in React `useState`. There is **no `localStorage` persistence** of `convId` or `messages`. A browser refresh wipes the chat from the user's view (the backend retains the conversation in memory, but the user has no way to resume it). The "+ New chat" button doesn't archive — it deletes the conversation outright via `DELETE /chat/conversations/{id}`.

For demo: hard-refreshing the page mid-walkthrough loses the chat history.

### `alert-actions-localstorage-only` — `alerts.jsx` lines 14-32, 826-863 — **HIGH** — fix complexity: **medium**
Acknowledge / Schedule Maintenance / Snooze / Resolve / Add Note all save to `localStorage` (`fhh_alert_overrides` key). They **never** call any backend endpoint:
- The contract has no `PATCH /alerts/{id}` route.
- The backend exposes nothing for ack / snooze.
- A different browser, an incognito window, or a wiped localStorage shows all alerts back as "Active".

The buttons feel real (visual state flips, "✓ Acknowledged by Aldo · 2 min ago" caption appears) but it's all client-side. **Demo risk** if a stakeholder opens the URL on their phone and sees no acknowledgements.

### `scenario-sliders-client-side-only` — `demand_forecast.jsx` lines 1601-1620 — **HIGH** — fix complexity: **medium**
The Demand tab's scenario panel literally renders the label `"🧪 Scenario · POST /forecast/scenario"` (line 1218), implying a backend call. The actual implementation is a `useMemo` over the existing forecast that multiplies values by `(1 + slider/100)` — pure client-side math. The backend has a real `POST /forecast/scenario` endpoint (verified working), but the frontend never calls it.

Functionally the visualization is plausible, but the label is misleading and the Prophet model's actual scenario regressors aren't engaged.

### `kpi-fallback-cost-saved` — `services/kpis.py` lines 47-49 — **MEDIUM** — fix complexity: **trivial**
```python
if cost_saved == 0:
    cost_saved = 280_000.0
```
When the maintenance-logs query returns zero (which it does in the seeded data because no MTD predictive entries exist), the backend returns a **hardcoded $280,000** as if it were real. The companion field `predicted_downtime_prevented_hours_mtd` correctly returns `0.0` and renders as "0h downtime prevented" — so the screen reads **"$280,000 cost saved · 0h downtime prevented"**, internally inconsistent.

### `alerts-list-15s-latency` — backend `/alerts?sort=created_at` — **MEDIUM** — fix complexity: **medium**
The alerts list endpoint takes **15.6 s** end-to-end on warm cache. Cause: it iterates every unresolved alarm (~200) and runs `component_risk()` ML inference per row to compute `risk_score`. Frontend has a 15 s timeout — borderline. On a cold cache it likely exceeds 15 s and trips the AbortController.

### `slow-cold-machines-list` — backend `/machines` — **LOW** — fix complexity: **medium**
First call after backend start: 4.6 s (ML inference for each of 4 machines, 6 components each = 24 IF + XGB calls). Subsequent calls fast due to `lru_cache`. Acceptable for first-page-load; would benefit from cache warming on app startup.

### `dropdown-flag-fallback-windows` — `demand_forecast.jsx` (renderMarketOption) — **LOW** — fix complexity: **trivial**
Already mitigated by the earlier badge-collision fix (22-px fixed flag column + 8-px gap). Mentioned here to confirm the fix is in place across both filter and compare dropdowns.

### `30d-horizon-degenerate-chart` — `demand_forecast.jsx` HorizonToggle — **LOW** — fix complexity: **small**
Selecting "30d" calls `/forecast?horizon_months=1` which returns a single forecast point. The chart then draws one dot — visually broken. 60d returns 2 monthly points — also coarse. The frontend was originally designed for daily forecasts; the backend currently returns only monthly aggregates.

### `predicted-failure-window-null-banner` — `overview.jsx` line 131 — **LOW** — fix complexity: **trivial**
`Action needed in {a.predicted_failure_window_hours}h` — if the top critical alert has `predicted_failure_window_hours: null` (which is allowed by the contract), the banner renders **"Action needed in nullh"**. In practice the demo anchor always has 48 h, but other criticals (e.g. the Steam-pressure one on al-bardi) return null.

### `_whats_wrong-_recommendation-fallback-only` — `machine_detail.jsx` lines 228, 290 — **LOW** — fix complexity: **trivial**
The "What's wrong" and "Recommendation" panels read `risk._whats_wrong` and `risk._recommendation` (underscore-prefixed UI extensions never returned by the live backend). The fallback strings always render — generic "{component} is at {score}/100 risk." and "Continue monitoring. No action required." The screen still works, but those panels never show component-specific reasoning.

---

## 🤔 Suspicious / needs human review

### Trend clamp suppresses 3/7 sampled SKUs
The Trend card on the Demand tab returns `"—"` for Jordan × Cotton Pads, Morocco × Toilet 2-ply 12, and Jordan × Beauty Tissue (raw annualized values: -49 %, -40 %, -38 %). These are getting clamped because the 4-month forecast (Jan-Apr 2026) traverses the post-Ramadan dip on Mar 19-22 → low April → annualized as if "year-long decline". The clamp is **doing the right thing semantically**, but the underlying issue is "first-month vs last-month" is a noisy proxy for trend on a window that includes a major seasonal swing. Aldo: decide whether the rate of "—" cards is acceptable or if the trend math should use a different baseline.

### `top_contributing_sensors` uses fixed values for the demo anchor
For `al-nakheel/yankee` the backend returns hardcoded sensor weights (62 / 18 / 12 then re-normalised) instead of computing them from the model's SHAP/feature-importance. The other 23 (machine, component) combos compute real attributions. This is a deliberate demo anchor preserved from earlier prompts, but worth noting the asymmetry.

### `reports/demand_validation.md` reports MAPE 4.25 %, screen reports MAPE ≈ 10 %
The validation report's mean MAPE across the 185 trained Prophet models is **4.25 %**. The Demand tab's AccuracyStrip derives MAPE client-side from the prediction band width, which runs ≈ 10 %. These are measuring different things (training-holdout MAPE vs. inference-band-width-as-MAPE-proxy), and both are technically valid, but the discrepancy may confuse a stakeholder asking "why does the docs say 4 % but the screen says 10 %".

### Eight backend endpoints are wired and tested but never called from the live frontend
Listed in §Coverage. All work; some may be intentional for future screens (e.g. `/kpis/cost-savings` for an ROI page, `/demand/anomalies` for an anomaly screen). Worth confirming none are vestigial before the audit closes.

### `overview.jsx` fetches have no `.catch()` 
`window.api.get("/kpis/overview").then(setKpis)` and `.then(setMachines)` have no error handler. If the backend is down or returns 500, the screen sits in skeleton state forever (KpiStrip renders a 132-px empty box; machines panel says "Loading..."). The api_client throws structured errors but the screen drops them on the floor as unhandled promise rejections.

### `/machines/{id}/sensors` (latest readings) endpoint is wired but unused
The "raw sensor signals" drilldown on Machine Detail uses `/{id}/sensors/{type}/history` per-sensor instead. Saves bandwidth but means the contract-shaped "all sensors latest" endpoint is dead code.

---

## 🪦 Dead buttons & fake features

| Surface | Element | Behaviour | Persistent? | Notes |
|---|---|---|---|---|
| Alerts | **Acknowledge** | flips status pill, adds timeline note | localStorage only | no backend |
| Alerts | **Schedule Maintenance** | opens modal → on submit, shows ✓ ScheduleModal then "Scheduled · {date}" | localStorage only | no backend |
| Alerts | **Snooze 24h** | adds `_snoozed_until` | localStorage only | no backend |
| Alerts | **Mark resolved** | flips to "Resolved" status | localStorage only | no backend |
| Alerts | **Add note** | (referenced in code, not visually verified) | localStorage only | no backend |
| Alerts | **Bulk acknowledge** | iterates selected alerts | localStorage only | no backend |
| Alerts | **View Machine** | navigates to Machine Detail | n/a | works |
| Demand | **Scenario sliders** (Ramadan, Pre-Ramadan, Trend, Promo) | overlays a coloured line on the chart | URL-state only via localStorage | no backend; client-side `useMemo` math; misleading "POST /forecast/scenario" label on the panel |
| Demand | **Compare** modal | opens overlay, fetches a second `/forecast` | n/a | works correctly |
| Demand | **Horizon toggle** (30/60/90/120) | refetches `/forecast` with different `horizon_months` | n/a | works but degenerate at 30 d (1 forecast point) |
| Demand | **"Schedule Run"** in Production Table | opens modal, prints toast | client-side only | no backend; no production scheduling endpoint exists |
| Chat | **+ New chat** | DELETEs current conversation, resets state | backend ✓ | conversation gone forever; no archive |
| Chat | **Suggested-prompt chips** | sends the chip text as a user message | n/a | works |
| Machine Detail | **Component tile click** | selects component, fetches `/components/{cid}/risk-score` | n/a | works |

---

## 📊 Coverage

- **Screens audited**: 4 / 4 (Overview, Machine Detail, Alerts, Demand) + Chat sidebar.
- **Endpoints exercised**: 19 / 27. Eight backend endpoints are wired and live but not consumed by the frontend.
- **Markets tested via `/forecast`**: 5 / 5 (uae, ksa, jordan, egypt, morocco) — Plus 7 (market, sku) combinations spot-checked for trend math.
- **Machines tested**: 4 / 4 — verified `/machines/{id}` resolves for all four IDs (al-nakheel, al-bardi, al-sindian, al-snobar).
- **SKUs sampled**: 7 / 37 — facial-100, cotton-pads-80 (uae + jordan), baby-s3, toilet-2ply-12, sani-50ml, beauty-tissue.
- **Buttons / interactive elements catalogued**: 14 (see "Dead buttons" table).
- **Edge cases tested**: missing API key (502 path), trend clamp at extreme values, dropdown flag-rendering fallback, single-point chart at 30 d horizon, `_status` undefined on fresh alerts.
- **Latency-tested endpoints**: 19 — fastest 0.01 s (`/products`), slowest 15.6 s (`/alerts?sort=created_at`).
- **Chat prompts tested**: 3 / 3.

---

## 💡 Recommended fix order

### Demo blockers — fix before any live walkthrough
1. **`chat-hallucinates-demo-anchor`** — the marquee feature returns wrong numbers. Either inject the live fleet snapshot into the system prompt (like `mock_data.jsx.bak` did with the multi-paragraph "Live fleet snapshot" block), or implement Anthropic tool-use so the model can fetch real data on demand. Until then, every factual chat question is a coin flip.
2. **`alerts-list-15s-latency`** — the alerts screen will show a blank table for 15 + s after a cold cache. Pre-warm the per-(machine, component) ML cache on backend startup, or denormalise `risk_score` into the alert row.

### Demo polish — fix before publishing demo URL
3. **`alert-actions-localstorage-only`** — at minimum, mention on the screen that acks are device-local. Better: add a small `PATCH /alerts/{id}` endpoint backed by a new `alert_overrides` table.
4. **`scenario-sliders-client-side-only`** — either rewire the sliders to call `POST /forecast/scenario` (already implemented backend-side) or remove the misleading "POST /forecast/scenario" label from the panel header.
5. **`predicted-failure-window-null-banner`** — guard the critical banner against `null`. Render "Action needed soon" or skip the suffix entirely.
6. **`kpi-fallback-cost-saved`** — drop the 280 K hardcoded fallback or make it consistent with `predicted_downtime_prevented_hours_mtd`.

### Quality-of-life — can ship as-is
7. **`chat-no-refresh-persistence`** — persist `convId` to `localStorage` so a refresh resumes; the backend already keeps the history.
8. **`30d-horizon-degenerate-chart`** — disable the 30 d (and arguably 60 d) options until daily granularity is exposed.
9. **`_whats_wrong-_recommendation-fallback-only`** — wire these to a small synthesizer in the API or remove the panels.
10. **`overview.jsx` fetches need `.catch()`** — at least log the error or render a "couldn't reach backend" toast.

### Trend math
11. Decide whether the ±25 % clamp is right (currently suppresses ~40 % of SKUs). If keeping it, label the "—" with an info tooltip ("Forecast window too noisy for an annualized trend").

### Dead-code cleanup (post-demo)
12. Either consume or remove the 8 unused backend endpoints (esp. `POST /forecast/scenario`, `/demand/anomalies`, `/kpis/cost-savings`).

---

_End of audit. No code modified other than this report._
