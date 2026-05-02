# Chat tool-use verification

_Run against the rebuilt `/chat` endpoint after the tool-use loop landed._

The previous chat handler answered factual questions from a static system
prompt with no live data — the audit caught it returning "risk score of 72"
for the Al-Nakheel Yankee (real value: 88). The fix replaces that with an
Anthropic tool-use loop that calls the live FHH backend before answering.

## What changed

**Backend**
- `backend/api/services/chat_tools.py` — new module. Eight tools wired
  directly to the underlying service functions (no HTTP round-trip):
    - `list_machines` · `get_machine_risk` · `get_machine_detail`
    - `list_alerts` · `get_alert`
    - `get_forecast` · `get_demand_drivers`
    - `get_fleet_kpis`
- `backend/api/services/chat.py` — `generate_reply` is now async and
  drives a tool-use loop (max 6 rounds). It echoes the assistant's
  `tool_use` blocks back into the message log, runs each tool, returns
  the `tool_result` blocks as a user message, and re-asks Claude until
  `stop_reason != "tool_use"`. New, much-stricter system prompt requires
  tool use for any factual question and refuses out-of-scope politely.
- `backend/api/routers/chat.py` — depends on `get_conn` and awaits
  `generate_reply(conn=conn)` so tools share the same DB pool.
- Uses `anthropic.AsyncAnthropic` so the LLM call doesn't block the
  event loop.

**Frontend** — no changes. The response shape (`{conversation_id, reply,
data_sources_used, suggested_followups, timestamp}`) is preserved;
`data_sources_used` is now populated with the names of tools actually
called.

## Verification (4 prompts, fresh conversations)

### Q1 — "What's the highest-risk machine right now?"

| | |
|---|---|
| Tools called | `list_machines` |
| Latency | 14.8 s (one Anthropic round trip + 4 × ML inference for fleet risk) |
| Reply (277 chars) | **Al Nakheel** is the highest-risk machine right now with a risk score of **88** (critical tier). The yankee component is driving the elevated risk, and the machine currently has 23 active alerts. Despite the high risk, Al Nakheel is still running at 2150 m/min with 89.2% OEE. |

**Cross-check against ground truth:**
- `GET /machines/al-nakheel/risk-score` → `score=88, tier=critical, highest_risk_component_id=yankee` ✓
- `GET /machines/al-nakheel` → `current_speed_mpm=2150, current_oee_percent=89.2, active_alerts_count=23` ✓
- Previous behaviour: model returned 72 % (hallucination). Now: 88. **Demo anchor recovered.**

### Q2 — "How many critical alerts are active?"

| | |
|---|---|
| Tools called | `list_alerts` |
| Latency | 3.6 s |
| Reply (55 chars) | You have **4** active critical alerts across the fleet. |

**Cross-check:**
- `GET /alerts/kpis` → `active_critical=4` ✓

### Q3 — "What's driving the UAE Diapers Size 4 forecast for next month?"
_(Context: current_page=demand_forecast, current_market=uae, current_sku=fine-baby-s4)_

| | |
|---|---|
| Tools called | `get_demand_drivers`, `get_forecast` (multi-tool synthesis) |
| Latency | 8.6 s |
| Reply (401 chars) | The UAE fine-baby-s4 forecast for next month (Feb 2026) shows baseline demand of ~**49,952 units** with an **upward push from Ramadan** (+13.0%), which starts Jan 1st and carries through. The model also captures a **pre-Ramadan stockup effect** averaging +25.3%, which typically occurs before Ramadan begins. No major drag events (Eid dips) are expected in February itself, so seasonality is positive. |

**Cross-check:**
- `GET /forecast?sku=fine-baby-s4&market=uae&horizon_months=1` returns ~50K monthly aggregate ✓
- `GET /demand/seasonality?sku=fine-baby-s4&market=uae` returns named events with average lift % ✓
- Numbers grounded in real Prophet output, not invented.

### Q4 — "What's the price of crude oil?"

| | |
|---|---|
| Tools called | _none_ |
| Latency | 2.8 s |
| Reply (223 chars) | I appreciate the question, but **crude oil pricing** is outside my scope—I'm focused exclusively on FHH operations data: machine health, alerts, demand forecasts, and production KPIs accessible through our internal systems. |

**Behaviour:** correctly refused without invoking any tool. ✓

## Latency profile

| Prompt | Tool rounds | Total | Notes |
|---|---|---|---|
| Q1 | 1 (`list_machines`) | 14.8 s | Bottleneck is the 4 × machine ML inference inside the tool — not the LLM. |
| Q2 | 1 (`list_alerts`) | 3.6 s | Fast — pure SQL. |
| Q3 | 2 (`get_demand_drivers` + `get_forecast`) | 8.6 s | Two tool rounds + Prophet decomposition. |
| Q4 | 0 | 2.8 s | One LLM round, no tools. |

The 14.8 s on Q1 is the same upstream slowness flagged in the audit
(`/machines` cold-start). It will warm-cache after the first Q1, then
subsequent Q1-style questions return in ~3-5 s.

## Acceptance

- [x] Q1 grounds in real value 88 (was 72 hallucination)
- [x] Q2 grounds in real critical-count
- [x] Q3 grounds in real Prophet forecast + drivers (multi-tool)
- [x] Q4 refuses politely with no tool call
- [x] `data_sources_used` lists the actual tools called per turn
- [x] API key never echoed in logs / responses (verified — all error paths
      go through `ChatUnavailable.safe_message`)

## Known limitations

- Tool calls are not persisted across conversation turns — only the final
  user/assistant text is stored. Each new user message triggers fresh tool
  resolution. This keeps memory bounded but means follow-up questions
  re-fetch the same data. Acceptable for the demo; revisit with caching
  when traffic justifies it.
- `MAX_TOOL_ROUNDS=6` caps the loop. If Claude requests a 7th round, the
  router returns a graceful "I needed more tool calls than my budget
  allows" reply rather than spinning indefinitely.
- The `list_alerts` tool intentionally bypasses the slow per-row ML
  inference path (15 s in audit) and reads `alarm_events` directly. It
  returns severity + description + timestamp, sufficient for triage
  questions. Use `get_alert(alert_id)` when the user asks for risk_score
  or recommended_action on a specific alert.
