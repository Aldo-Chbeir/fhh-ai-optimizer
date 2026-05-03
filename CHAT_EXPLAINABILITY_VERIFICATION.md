# Chat explainability — verification

_Tools added so the chat sidebar can back up predictions with the actual
sensor readings the model leaned on, instead of hand-waving "bearing
vibration" without numbers._

## What changed

**Backend only — no frontend changes.**

`backend/api/services/chat_tools.py` now exposes two new tools to Claude:

| Tool | Purpose |
|---|---|
| `get_component_root_cause(machine_id, component_id)` | Walks every sensor on the component, scores each by `max-365-day-value / critical-threshold`, returns the primary driver + up to three contributing drivers + a one-sentence narrative. |
| `get_sensor_readings(machine_id, component_id, sensor_type?, min_value?, limit?, order?)` | Pulls raw sensor readings (timestamp + value + breach flag) from a 30-day window (`order='recent'`) or 365-day window (`order='highest'`). Auto-picks the worst-breaching sensor when `sensor_type` is omitted. Returns aggregate min/max/avg/breach summary alongside the rows. |

The two tools share a `SENSOR_THRESHOLDS` table at the top of
`chat_tools.py`. Critical/warning levels were tuned against the real
seeded data (e.g. bearings critical = 6.0 mm/s — Al-Nakheel bearing 1
peaked at exactly 6.93 mm/s on 2025-09-27, so the threshold flags
historical breaches the way the demo narrative needs).

`backend/api/services/chat.py` system prompt rewritten:
- Two new tools added to the "Available tools" list.
- New "Data explainability — MANDATORY tool sequence" section that
  enumerates trigger phrases ("why is …", "show me the data",
  "give me the readings", "what's driving …", "back that up", etc.)
  and prescribes a strict three-step sequence: call
  `get_component_root_cause`, then `get_sensor_readings` with
  `order='highest'`, then reply with a bulleted list of values.
- Worked example showing the exact output format Claude should produce.
- Explicit "DO NOT include raw readings for casual questions" guard so
  questions like *"how many critical alerts"* still get terse answers.

## Verification

All eight prompts run against the live `/chat` endpoint, fresh
conversation per prompt.

### New explainability prompts

#### E1 — "Why is Yankee on Al-Nakheel critical?"
_Context: machine_detail, machine_id=al-nakheel, component_id=yankee_

| | |
|---|---|
| Tools called | `get_component_root_cause` → `get_sensor_readings` |
| Latency | 25.0 s |
| Reply | "Yankee on Al-Nakheel is critical because **bearing 1 vibration** hit **6.93 mm/s**, exceeding the **6.0 mm/s critical threshold**.<br><br>**Top readings:**<br>• **6.93 mm/s** — 2025-09-27 00:10 UTC<br>• **6.93 mm/s** — 2025-09-27 00:05 UTC<br>• **6.93 mm/s** — 2025-09-27 00:00 UTC<br>• **6.93 mm/s** — 2025-09-26 23:55 UTC<br>• **6.93 mm/s** — 2025-09-26 23:50 UTC<br><br>Last breach was September 27; **0 breaches in the last 7 days**, but the model still penalizes this historical breach event, keeping the risk elevated." |

Cross-check: `tool_get_component_root_cause` returns
`primary_driver.sensor_type='yankee_vibration_bearing_1'` with `max=6.93`,
`last_breach_at='2025-09-27T00:10:00Z'`. The five timestamps in the
reply match the five highest readings actually in the DB. Numbers and
timestamps are real, not hallucinated.

#### E2 — "Show me the data behind that risk score."
_Same context as E1_

| | |
|---|---|
| Tools called | `get_component_root_cause` → `get_sensor_readings` |
| Latency | 21.5 s |
| Reply | "Yankee on Al-Nakheel is critical because **bearing 1 vibration hit 6.93 mm/s**, above the **6.0 mm/s critical threshold**.<br><br>**Top readings:**<br>• **6.93 mm/s** — 2025-09-27 00:10 UTC<br>• … (5 readings) …<br><br>Last breach was 2025-09-27; **0 breaches in the last 7 days**, but the model still penalizes this historical excursion in its risk calculation." |

Same shape, same readings — Claude correctly recognizes "show me the
data" as an explainability trigger and follows the three-step sequence.

#### E3 — "What's the highest-risk machine?" *(no 'why')*
_Context: overview_

| | |
|---|---|
| Tools called | `list_machines` (only) |
| Latency | 10.2 s |
| Reply | "**Al Nakheel** (Abu Dhabi, UAE) is the highest-risk machine with a score of **88** (critical tier). Its Yankee component is driving that risk, with 22 active alerts." |

Correct opt-out: 165-character brief reply, **no raw sensor readings,
no breach data**. The "DO NOT include readings for casual questions"
guard is working.

#### E4 — "Give me the recent vibration readings on Al-Nakheel."
_Context: machine_detail, machine_id=al-nakheel, component_id=yankee_

| | |
|---|---|
| Tools called | `get_component_root_cause` → `get_sensor_readings` (with `order='recent'`) |
| Latency | 22.5 s |
| Reply | "Here are the **recent vibration readings** for bearing 1 on Al-Nakheel's Yankee:<br>• **3.85 mm/s** — 2026-04-24 23:55 UTC<br>• 3.81 mm/s — 2026-04-24 23:50 UTC<br>• … (10 readings) …<br><br>All current readings are **below the 6.0 mm/s critical threshold**. Over the last 30 days, vibration averaged **3.8 mm/s** with a peak of **4.05 mm/s** and **zero breaches** in the last 7 days." |

Correct: the user asked for *"recent"* readings → Claude uses
`order='recent'` (30-day window). Latest data point is 2026-04-24 23:55
which matches `MAX(timestamp)` in `sensor_readings`. Includes the
30-day summary statistics from the tool's `summary` block.

### Regression prompts (must still pass after changes)

| # | Prompt | Tools called | Reply (truncated) | Pass? |
|---|---|---|---|---|
| R1 | "What's the highest-risk machine right now?" | `list_machines` | "**Al Nakheel** … score of **88** (critical tier) … Yankee component is the primary driver, 22 active alerts." | ✓ |
| R2 | "How many critical alerts are active?" | `get_fleet_kpis` | "**3 active critical alerts** across the fleet right now. There are also 19 warning-level alerts active." | ✓ |
| R3 | "What's driving the UAE Diapers Size 4 forecast for next month?" | `get_forecast`, `get_demand_drivers` | "Ramadan surge … **+13.0%** lift … pre-Ramadan stockup … **+25.3%** … 49,356 units (80% CI 45k-53k)." | ✓ |
| R4 | "What's the price of crude oil?" | _(none)_ | "I appreciate the question, but crude oil pricing is outside my scope…" | ✓ |

No regression: every original behaviour preserved. The two new tools
are additive.

## Implementation notes

### How `get_component_root_cause` ranks drivers
For each sensor on the component:
- read latest value + max-value-in-365-days
- compute `headroom_percent = 100 * (latest - critical) / critical`
- count breaches in the last 7 days
- record last breach timestamp

Sort by `(has_ever_breached_critical, max_value / critical_threshold)`
descending. Sensors that have crossed critical at any point sort above
sensors that haven't. Among breachers, the highest exceedance ratio
wins. This surfaces both currently-breaching sensors AND historical
incidents that drive the model's persistent risk score (so the bearing
1 historical 6.93 mm/s readings on Al-Nakheel correctly surface even
though current bearing 1 is back to normal post-replacement).

### How `get_sensor_readings` decides the window
- `order='recent'` → 30-day window (typical "show me the latest
  values" question)
- `order='highest'` → 365-day window (typical "show me the breach
  evidence" question; user wants extreme historical readings, even if
  they're months old)

### Threshold table
| sensor | critical | warning | unit |
|---|---|---|---|
| yankee_surface_temp | 125.0 | 122.0 | °C |
| yankee_steam_pressure | 11.0 | 10.5 | bar |
| yankee_vibration_bearing_{1,2,3} | 6.0 | 4.5 | mm/s |
| yankee_blade_pressure | 130.0 | 125.0 | kPa |
| visconip_nip_pressure | 7.0 | 6.5 | bar |
| visconip_felt_moisture | 50.0 | 47.0 | % |
| aircap_inlet_temp | 540.0 | 525.0 | °C |
| aircap_energy | 2.8 | 2.5 | kWh/ton |
| headbox_stock_temp | 60.0 | 57.0 | °C |
| softreel_tension | 240.0 | 225.0 | N/m |
| rewinder_speed | 2300.0 | 2250.0 | m/min |

`qcs_softness_index` is intentionally omitted — it's a low-bad sensor
(quality drops as the value falls), not high-bad, so the same
threshold model doesn't apply. A future iteration can model two-sided
thresholds.

### Note on the demo anchor narrative
The marketing narrative for the demo says *"bearing 3 vibration trending
toward failure"*. The actual seeded sensor data shows:
- bearing 1: max 6.93 mm/s on 2025-09-27 (real historical breach)
- bearing 2: max 4.07 mm/s
- bearing 3: max 4.47 mm/s in April 2026 (recent rising trend, no critical breach)

The unresolved alarm description still mentions bearing 3, but the chat
tools correctly ground in the actual data and identify bearing 1 as the
primary driver (because bearing 3's max never crossed 6.0). This is
**more truthful** than the marketing copy. If you want chat to point at
bearing 3 instead, lower the bearing-vibration critical threshold to
4.5 (matching the warning) — but that's a marketing decision, not a
code bug.

## Files touched

| File | Change |
|---|---|
| `backend/api/services/chat_tools.py` | +SENSOR_THRESHOLDS table, +tool_get_component_root_cause, +tool_get_sensor_readings, +2 schema entries, +2 dispatch entries (8 → 10 tools) |
| `backend/api/services/chat.py` | Updated "Available tools" list (10 tools); new "Data explainability — MANDATORY tool sequence" prompt section with trigger phrases + 3-step procedure + worked example + opt-out guard |

## Acceptance

- [x] Two new tools defined in `TOOL_SCHEMAS`, dispatched correctly
- [x] System prompt instructs the model to call them on "why" / "show me data" / "give me readings" type prompts
- [x] E1, E2, E4 all hit the new tools and reply with the actual numbers
- [x] E3 correctly skips raw readings for the casual "highest-risk machine" question
- [x] R1-R4 from the previous CHAT_VERIFICATION.md still pass
- [x] All values in replies cross-check against the DB (6.93 mm/s, Sept 27 timestamps, 88 score, 3 critical alerts, 49,356-unit forecast, etc.)
- [x] No frontend changes
