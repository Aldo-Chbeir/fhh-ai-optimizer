// Mock data matching API_CONTRACT v1.1 exactly. Field names, value types, enum
// strings are verbatim from the contract — do not rename, do not invent.

// GET /kpis/overview
const MOCK_KPIS_OVERVIEW = {
  fleet_avg_oee_percent: 93.7,
  active_critical_alerts: 1,
  active_warning_alerts: 2,
  predicted_downtime_prevented_hours_mtd: 14,
  estimated_cost_saved_usd_mtd: 280000,
  machines_running: 3,
  machines_total: 4,
  last_updated: "2026-04-25T14:30:00Z",
};

// GET /machines  →  { machines: [...], total }
const MOCK_MACHINES = {
  machines: [
    {
      machine_id: "al-nakheel", name: "Al Nakheel", location: "Abu Dhabi, UAE",
      model: "Valmet Advantage DCT 200TS", installation_date: "2018-06-15",
      status: "running", current_speed_mpm: 2150, current_oee_percent: 94.2,
      risk_score: 67, risk_tier: "warning", active_alerts_count: 2,
    },
    {
      machine_id: "al-bardi", name: "Al Bardi", location: "Egypt",
      model: "Valmet Advantage DCT 200TS", installation_date: "2019-09-02",
      status: "running", current_speed_mpm: 2080, current_oee_percent: 95.1,
      risk_score: 28, risk_tier: "healthy", active_alerts_count: 0,
    },
    {
      machine_id: "al-sindian", name: "Al Sindian", location: "Egypt",
      model: "Valmet Advantage DCT 200TS", installation_date: "2020-03-21",
      status: "running", current_speed_mpm: 2110, current_oee_percent: 92.4,
      risk_score: 45, risk_tier: "watch", active_alerts_count: 1,
    },
    {
      machine_id: "al-snobar", name: "Al Snobar", location: "Jordan",
      model: "Valmet Advantage DCT 200TS", installation_date: "2017-11-08",
      status: "idle", current_speed_mpm: 0, current_oee_percent: 93.1,
      risk_score: 22, risk_tier: "healthy", active_alerts_count: 0,
    },
  ],
  total: 4,
};

// ────────────── Full /alerts feed ──────────────
// Contract Alert object: alert_id, machine_id, component_id, severity, risk_score,
// title, description, predicted_failure_window_hours, recommended_action,
// estimated_cost_if_unaddressed_usd, created_at, acknowledged.
// UI-only extension fields (prefixed with _): _status, _trend, _resolved_at,
// _resolved_by, _resolution_notes, _scheduled_for, _scheduled_by, _ack_by, _ack_at.
const MOCK_ALL_ALERTS = [
  // ─── ACTIVE (4) ───
  {
    alert_id: "alt-2026-04-25-0017", machine_id: "al-nakheel", component_id: "yankee",
    severity: "critical", risk_score: 87,
    title: "Bearing 3 vibration trending toward failure",
    description: "Bearing 3 vibration trending +0.4 mm/s/day, 3.2σ above 30-day baseline (5.8 vs 2-4 mm/s normal).",
    predicted_failure_window_hours: 48,
    recommended_action: "Schedule bearing replacement in next planned downtime. Stockpile spare set BR-7842.",
    estimated_cost_if_unaddressed_usd: 480000,
    created_at: "2026-04-28T12:30:00Z", acknowledged: false,
    _status: "active", _trend: "rising",
  },
  {
    alert_id: "alt-2026-04-28-0008", machine_id: "al-sindian", component_id: "visconip",
    severity: "warning", risk_score: 72,
    title: "Felt moisture trending up",
    description: "ViscoNip felt moisture 56% vs 50% baseline; up 9 days. Felt approaching end-of-life sooner than calendar.",
    predicted_failure_window_hours: 168,
    recommended_action: "Schedule felt change ML-118 within 7 days. Confirm inventory.",
    estimated_cost_if_unaddressed_usd: 38000,
    created_at: "2026-04-28T08:30:00Z", acknowledged: false,
    _status: "active", _trend: "rising",
  },
  {
    alert_id: "alt-2026-04-27-0019", machine_id: "al-bardi", component_id: "softreel",
    severity: "warning", risk_score: 64,
    title: "Reel tension oscillation detected",
    description: "Reel tension oscillating ±18 N/m around 200 N/m setpoint. Pattern began 26h ago.",
    predicted_failure_window_hours: 240,
    recommended_action: "Inspect reel drive coupling at next reel change. Recalibrate tension loop.",
    estimated_cost_if_unaddressed_usd: 22000,
    created_at: "2026-04-27T14:30:00Z", acknowledged: false,
    _status: "active", _trend: "stable",
  },
  {
    alert_id: "alt-2026-04-26-0007", machine_id: "al-snobar", component_id: "headbox",
    severity: "warning", risk_score: 48,
    title: "Mild headbox pressure variability",
    description: "Headbox pressure variance 1.4 kPa over 12h, double the 30-day mean. Within tolerance but worth watching.",
    predicted_failure_window_hours: null,
    recommended_action: "Continue monitoring. Re-check pressure regulator at next planned inspection.",
    estimated_cost_if_unaddressed_usd: null,
    created_at: "2026-04-26T14:30:00Z", acknowledged: false,
    _status: "active", _trend: "falling",
  },

  // ─── ACKNOWLEDGED (2) ───
  {
    alert_id: "alt-2026-04-28-0011", machine_id: "al-bardi", component_id: "aircap",
    severity: "warning", risk_score: 61,
    title: "Hood exhaust humidity elevated",
    description: "Hood exhaust humidity 72% vs 60% baseline. Possibly correlated with ambient temperature rise.",
    predicted_failure_window_hours: 336,
    recommended_action: "Verify hood seal integrity at next walkaround.",
    estimated_cost_if_unaddressed_usd: 14000,
    created_at: "2026-04-28T10:30:00Z", acknowledged: true,
    _status: "acknowledged", _trend: "stable",
    _ack_by: "M. Khalid", _ack_at: "2026-04-28T10:45:00Z",
  },
  {
    alert_id: "alt-2026-04-27-0001", machine_id: "al-nakheel", component_id: "headbox",
    severity: "critical", risk_score: 81,
    title: "Drainage rate drop",
    description: "Drainage rate fell 8% over 18h — possible forming-fabric clogging. Predicted failure window: 72h.",
    predicted_failure_window_hours: 72,
    recommended_action: "Inspect forming fabric and drainage elements at next downtime.",
    estimated_cost_if_unaddressed_usd: 145000,
    created_at: "2026-04-27T14:30:00Z", acknowledged: true,
    _status: "scheduled", _trend: "rising",
    _ack_by: "L. Haddad", _ack_at: "2026-04-27T15:30:00Z",
    _scheduled_for: "2026-04-29", _scheduled_by: "L. Haddad",
  },

  // ─── SNOOZED (1) ───
  {
    alert_id: "alt-2026-04-26-0014", machine_id: "al-sindian", component_id: "aircap",
    severity: "watch", risk_score: 42,
    title: "Hood fan speed wobble",
    description: "Hood fan speed showing 2% wobble around setpoint. Not yet impacting energy use.",
    predicted_failure_window_hours: null,
    recommended_action: "Re-evaluate after 24h. Likely benign drift.",
    estimated_cost_if_unaddressed_usd: null,
    created_at: "2026-04-26T18:30:00Z", acknowledged: true,
    _status: "snoozed", _trend: "stable",
    _ack_by: "S. Antar", _ack_at: "2026-04-27T16:30:00Z",
    _snoozed_until: "2026-04-29T16:30:00Z",
  },

  // ─── RESOLVED (5) ───
  {
    alert_id: "alt-2026-04-25-0009", machine_id: "al-snobar", component_id: "yankee",
    severity: "warning", risk_score: 65,
    title: "Steam pressure anomaly",
    description: "Steam pressure spiked to 11.2 bar before settling. Cause: regulator hysteresis.",
    predicted_failure_window_hours: null,
    recommended_action: "Recalibrated steam pressure regulator. Restored to 9 bar setpoint.",
    estimated_cost_if_unaddressed_usd: 28000,
    created_at: "2026-04-25T10:30:00Z", acknowledged: true,
    _status: "resolved", _trend: "stable",
    _ack_by: "M. Khalil", _ack_at: "2026-04-25T11:00:00Z",
    _resolved_at: "2026-04-25T12:30:00Z", _resolved_by: "M. Khalil",
    _resolution_notes: "Recalibrated regulator. Verified steady-state at 9 bar over 4h. No further action.",
  },
  {
    alert_id: "alt-2026-04-23-0004", machine_id: "al-bardi", component_id: "visconip",
    severity: "critical", risk_score: 84,
    title: "Press section vibration spike",
    description: "Press section vibration spiked to 7.1 mm/s. Root cause: bearing wear.",
    predicted_failure_window_hours: 24,
    recommended_action: "Replaced bearing during emergency window. Restored to 3.1 mm/s.",
    estimated_cost_if_unaddressed_usd: 95000,
    created_at: "2026-04-23T11:00:00Z", acknowledged: true,
    _status: "resolved", _trend: "stable",
    _ack_by: "M. Khalil", _ack_at: "2026-04-23T11:30:00Z",
    _resolved_at: "2026-04-23T19:00:00Z", _resolved_by: "M. Khalil",
    _resolution_notes: "Replaced bearing pack. $12,500 part + 6h downtime. Cost saved vs unplanned: ~$95K.",
  },
  {
    alert_id: "alt-2026-04-22-0011", machine_id: "al-sindian", component_id: "rewinder",
    severity: "warning", risk_score: 58,
    title: "Rewinder belt slip",
    description: "Rewinder belt slipped 2 cycles. Recovered automatically.",
    predicted_failure_window_hours: 480,
    recommended_action: "Tightened tension. Belt logged for inspection at next service.",
    estimated_cost_if_unaddressed_usd: 8000,
    created_at: "2026-04-22T09:00:00Z", acknowledged: true,
    _status: "resolved", _trend: "stable",
    _ack_by: "L. Haddad", _ack_at: "2026-04-22T09:20:00Z",
    _resolved_at: "2026-04-22T13:00:00Z", _resolved_by: "L. Haddad",
    _resolution_notes: "Belt tension adjusted. No further slip events.",
  },
  {
    alert_id: "alt-2026-04-20-0003", machine_id: "al-nakheel", component_id: "aircap",
    severity: "warning", risk_score: 60,
    title: "Hood inlet temperature drift",
    description: "Inlet temp drifting 5°C above setpoint. Burner control loop issue.",
    predicted_failure_window_hours: null,
    recommended_action: "Recalibrated burner control loop.",
    estimated_cost_if_unaddressed_usd: 18000,
    created_at: "2026-04-20T15:00:00Z", acknowledged: true,
    _status: "resolved", _trend: "stable",
    _ack_by: "S. Antar", _ack_at: "2026-04-20T15:30:00Z",
    _resolved_at: "2026-04-20T18:30:00Z", _resolved_by: "S. Antar",
    _resolution_notes: "Burner control loop recalibrated. Inlet temp held at setpoint over 24h.",
  },
  {
    alert_id: "alt-2026-04-18-0007", machine_id: "al-bardi", component_id: "headbox",
    severity: "watch", risk_score: 38,
    title: "Stock temperature minor drift",
    description: "Stock temperature drifted +1.2°C over 8h. Sensor recalibration recommended.",
    predicted_failure_window_hours: null,
    recommended_action: "Recalibrated headbox stock-temp sensor.",
    estimated_cost_if_unaddressed_usd: null,
    created_at: "2026-04-18T08:00:00Z", acknowledged: true,
    _status: "resolved", _trend: "stable",
    _ack_by: "H. Naser", _ack_at: "2026-04-18T08:30:00Z",
    _resolved_at: "2026-04-18T11:00:00Z", _resolved_by: "H. Naser",
    _resolution_notes: "Sensor recalibrated. No further drift.",
  },
];

function alertsResponse(filterFn, sort) {
  let list = MOCK_ALL_ALERTS.filter(filterFn || (() => true));
  if (sort === "severity") {
    const order = { critical: 0, warning: 1, watch: 2, info: 3 };
    list = list.slice().sort((a, b) =>
      (order[a.severity] - order[b.severity]) || (b.risk_score - a.risk_score));
  } else if (sort === "created_at") {
    list = list.slice().sort((a, b) => b.created_at.localeCompare(a.created_at));
  } else if (sort === "risk_score") {
    list = list.slice().sort((a, b) => b.risk_score - a.risk_score);
  }
  const counts = { critical: 0, warning: 0, watch: 0, info: 0 };
  list.forEach((a) => { counts[a.severity] = (counts[a.severity] || 0) + 1; });
  return { alerts: list, total: list.length, counts_by_tier: counts };
}

const MOCK_ALERTS_CRITICAL = alertsResponse(
  (a) => a.severity === "critical" && a._status === "active"
);

// UI-extension endpoint: /alerts/kpis  → powers Screen 3 KPI strip.
// 7-day sparkline counts (per day, oldest → newest).
const MOCK_ALERTS_KPIS = {
  active_critical: 1,
  critical_sparkline_7d: [0, 1, 1, 2, 1, 1, 1],
  active_warning: 3,
  warning_sparkline_7d: [2, 2, 3, 4, 3, 3, 3],
  avg_response_time_minutes: 14,
  avg_response_time_delta_minutes: -3,         // -3 = 3 min faster than last week
  acknowledged_today: 8,
  acknowledged_today_total: 12,
  last_updated: "2026-04-28T14:30:00Z",
};

// ────────────── Per-machine risk + components ──────────────
function tierFromScore(s) {
  if (s >= 80) return "critical";
  if (s >= 50) return "warning";
  if (s >= 35) return "watch";
  return "healthy";
}

// Component layout in line order: headbox → visconip → yankee → aircap → softreel → rewinder.
// Each entry only sets risk_score; tier is derived. Hours are arbitrary plausible.
const COMPONENT_RISK_SCORES = {
  "al-nakheel": { headbox: 12, visconip: 24, yankee: 87, aircap: 18, softreel:  8, rewinder: 15 },
  "al-bardi":   { headbox:  8, visconip: 14, yankee: 31, aircap: 12, softreel:  6, rewinder:  9 },
  "al-sindian": { headbox: 18, visconip: 38, yankee: 22, aircap: 25, softreel: 12, rewinder: 14 },
  "al-snobar":  { headbox: 10, visconip: 18, yankee: 25, aircap: 14, softreel:  8, rewinder: 11 },
};

const COMPONENT_NAMES = {
  headbox:  "OptiFlo II TIS Headbox",
  visconip: "Advantage ViscoNip Press",
  yankee:   "Cast Alloy Yankee Cylinder",
  aircap:   "AirCap Hood with Air System",
  softreel: "SoftReel Reel",
  rewinder: "Focus Rewinder",
};

const COMPONENT_HOURS = {
  "al-nakheel": { headbox: 1800, visconip: 2100, yankee: 4200, aircap: 1500, softreel:  900, rewinder: 1300 },
  "al-bardi":   { headbox:  900, visconip: 1100, yankee: 2400, aircap:  600, softreel:  400, rewinder:  700 },
  "al-sindian": { headbox: 1200, visconip: 3100, yankee: 1500, aircap: 1900, softreel:  800, rewinder: 1000 },
  "al-snobar":  { headbox: 2200, visconip: 2600, yankee: 3300, aircap: 1700, softreel: 1100, rewinder: 1500 },
};

const LAST_MAINT_DATE = {
  "al-nakheel": { headbox: "2026-02-12", visconip: "2026-01-29", yankee: "2026-01-15", aircap: "2026-02-22", softreel: "2026-03-04", rewinder: "2026-02-28" },
  "al-bardi":   { headbox: "2026-03-10", visconip: "2026-03-04", yankee: "2026-02-08", aircap: "2026-03-18", softreel: "2026-03-25", rewinder: "2026-03-15" },
  "al-sindian": { headbox: "2026-02-28", visconip: "2026-01-08", yankee: "2026-03-12", aircap: "2026-02-18", softreel: "2026-03-08", rewinder: "2026-03-02" },
  "al-snobar":  { headbox: "2026-01-22", visconip: "2026-01-04", yankee: "2025-12-18", aircap: "2026-02-14", softreel: "2026-02-22", rewinder: "2026-02-08" },
};

const COMPONENT_LIFETIME = { headbox: 60000, visconip: 50000, yankee: 50000, aircap: 55000, softreel: 60000, rewinder: 55000 };

function buildComponents(machineId) {
  const order = ["headbox", "visconip", "yankee", "aircap", "softreel", "rewinder"];
  return {
    machine_id: machineId,
    components: order.map((cid) => {
      const score = COMPONENT_RISK_SCORES[machineId][cid];
      return {
        component_id: cid,
        machine_id: machineId,
        name: COMPONENT_NAMES[cid],
        is_critical: cid === "yankee",
        risk_score: score,
        risk_tier: tierFromScore(score),
        expected_lifetime_hours: COMPONENT_LIFETIME[cid],
        hours_since_last_maintenance: COMPONENT_HOURS[machineId][cid],
        last_maintenance_date: LAST_MAINT_DATE[machineId][cid],
      };
    }),
  };
}

function buildRiskScore(machineId) {
  const scores = COMPONENT_RISK_SCORES[machineId];
  const m = MOCK_MACHINES.machines.find((x) => x.machine_id === machineId);
  // Highest-risk component
  const highest = Object.entries(scores).sort((a, b) => b[1] - a[1])[0][0];
  return {
    machine_id: machineId,
    score: m.risk_score,
    tier: m.risk_tier,
    highest_risk_component_id: highest,
    last_updated: "2026-04-25T14:30:00Z",
  };
}

// ────────────── Per (machine, component) risk-score detail ──────────────
// Each entry → contract shape for GET /machines/{id}/components/{cid}/risk-score:
//   { score, tier, predicted_failure_window_hours, top_contributing_sensors[], last_updated }
// Plus extension fields (read by UI only):
//   _whats_wrong, _recommendation
const COMPONENT_RISK_DETAIL = {
  // ─── Al Nakheel ───
  "al-nakheel:headbox": {
    top_contributing_sensors: [{ sensor_type: "headbox_stock_temp", contribution_percent: 70 }],
    _whats_wrong: "Headbox is operating well within its normal envelope. Stock temperature has held steady at 48°C for the last 30 days, with no slice-lip anomalies detected.",
    _recommendation: "No action required. Next preventive cleaning is scheduled for the standard 90-day interval.",
  },
  "al-nakheel:visconip": {
    top_contributing_sensors: [
      { sensor_type: "visconip_felt_moisture", contribution_percent: 55 },
      { sensor_type: "visconip_nip_pressure",  contribution_percent: 30 },
    ],
    _whats_wrong: "ViscoNip Press is healthy. Felt moisture has trended slightly higher this week (~52% vs 50% baseline) but is still well within normal range.",
    _recommendation: "Continue monitoring. Felt change is on schedule for early May; no acceleration needed.",
  },
  "al-nakheel:yankee": {
    predicted_failure_window_hours: 48,
    top_contributing_sensors: [
      { sensor_type: "yankee_vibration_bearing_3", contribution_percent: 62 },
      { sensor_type: "yankee_surface_temp",        contribution_percent: 18 },
      { sensor_type: "yankee_steam_pressure",      contribution_percent: 12 },
    ],
    _whats_wrong: "Yankee Cylinder is at 87% risk because Bearing 3 vibration has been climbing 0.4 mm/s/day for 11 days. Current reading is 5.8 mm/s; normal range is 2-4 mm/s. The model predicts failure within 48 hours.",
    _recommendation: "Replace Bearing 3 in next planned downtime window. Stockpile spare bearing set BR-7842. Estimated downtime: 6 hours. Cost: $12,500. Cost if ignored: $480K.",
  },
  "al-nakheel:aircap": {
    top_contributing_sensors: [
      { sensor_type: "aircap_inlet_temp", contribution_percent: 58 },
      { sensor_type: "aircap_energy",     contribution_percent: 30 },
    ],
    _whats_wrong: "AirCap Hood is healthy. Inlet temperature is tracking 2°C above target — within tolerance but worth watching as ambient temps rise.",
    _recommendation: "No action required. Re-check burner alignment at next planned hood seal inspection (April 9).",
  },
  "al-nakheel:softreel": {
    top_contributing_sensors: [{ sensor_type: "softreel_tension", contribution_percent: 80 }],
    _whats_wrong: "SoftReel Reel is the lowest-risk component on this machine. Tension is rock-steady at 380 N/m and reel changes have been clean.",
    _recommendation: "No action required.",
  },
  "al-nakheel:rewinder": {
    top_contributing_sensors: [{ sensor_type: "rewinder_speed", contribution_percent: 75 }],
    _whats_wrong: "Rewinder is healthy. Speed control is stable; the belt replaced March 22 is performing as expected.",
    _recommendation: "No action required. Next inspection at standard 60-day interval.",
  },

  // ─── Al Bardi ───
  "al-bardi:headbox": {
    top_contributing_sensors: [{ sensor_type: "headbox_stock_temp", contribution_percent: 80 }],
    _whats_wrong: "Headbox is operating cleanly. Stock temperature variance is among the lowest in the fleet (±0.3°C).",
    _recommendation: "No action required. This component is a candidate baseline for the fleet model.",
  },
  "al-bardi:visconip": {
    top_contributing_sensors: [
      { sensor_type: "visconip_felt_moisture", contribution_percent: 60 },
      { sensor_type: "visconip_nip_pressure",  contribution_percent: 25 },
    ],
    _whats_wrong: "ViscoNip Press is healthy. Felt moisture and nip pressure are both tracking within ±5% of baseline.",
    _recommendation: "No action required. Felt change scheduled for late May per OEM guidance.",
  },
  "al-bardi:yankee": {
    top_contributing_sensors: [
      { sensor_type: "yankee_vibration_bearing_2", contribution_percent: 45 },
      { sensor_type: "yankee_surface_temp",        contribution_percent: 30 },
      { sensor_type: "yankee_steam_pressure",      contribution_percent: 15 },
    ],
    _whats_wrong: "Yankee Cylinder is the highest-risk component on Al Bardi but still safely in the healthy band (31/100). Bearing 2 vibration shows a mild upward drift over the past 14 days — well below threshold.",
    _recommendation: "No action required. The drift will be tracked at the next weekly review; if it continues another 14 days, schedule a baseline reset.",
  },
  "al-bardi:aircap": {
    top_contributing_sensors: [
      { sensor_type: "aircap_inlet_temp", contribution_percent: 65 },
      { sensor_type: "aircap_energy",     contribution_percent: 25 },
    ],
    _whats_wrong: "AirCap Hood is performing well. Energy use is 8% below fleet average for this throughput band.",
    _recommendation: "No action required.",
  },
  "al-bardi:softreel": {
    top_contributing_sensors: [{ sensor_type: "softreel_tension", contribution_percent: 85 }],
    _whats_wrong: "SoftReel Reel is the lowest-risk component on this machine (6/100). Tension control is excellent.",
    _recommendation: "No action required.",
  },
  "al-bardi:rewinder": {
    top_contributing_sensors: [{ sensor_type: "rewinder_speed", contribution_percent: 80 }],
    _whats_wrong: "Rewinder is healthy. Speed control is tight; no recent stoppages.",
    _recommendation: "No action required.",
  },

  // ─── Al Sindian ───
  "al-sindian:headbox": {
    top_contributing_sensors: [{ sensor_type: "headbox_stock_temp", contribution_percent: 75 }],
    _whats_wrong: "Headbox is operating normally. Stock temperature is steady at 47°C; no anomalies in the past 30 days.",
    _recommendation: "No action required.",
  },
  "al-sindian:visconip": {
    top_contributing_sensors: [
      { sensor_type: "visconip_felt_moisture", contribution_percent: 65 },
      { sensor_type: "visconip_nip_pressure",  contribution_percent: 30 },
    ],
    _whats_wrong: "ViscoNip Press is at 38/100 — the highest-risk component on Al Sindian. Felt moisture has crept up from 50% to 56% over 9 days, suggesting felt is approaching end-of-life sooner than the calendar predicts.",
    _recommendation: "Schedule felt change within the next 7 days. Confirm new felt set ML-118 is in inventory; if not, expedite. Estimated downtime: 3 hours. Cost: $5,400.",
  },
  "al-sindian:yankee": {
    top_contributing_sensors: [
      { sensor_type: "yankee_vibration_bearing_1", contribution_percent: 50 },
      { sensor_type: "yankee_surface_temp",        contribution_percent: 30 },
    ],
    _whats_wrong: "Yankee Cylinder is healthy (22/100). Vibration on all three bearings is well within normal range.",
    _recommendation: "No action required.",
  },
  "al-sindian:aircap": {
    top_contributing_sensors: [
      { sensor_type: "aircap_inlet_temp", contribution_percent: 55 },
      { sensor_type: "aircap_energy",     contribution_percent: 35 },
    ],
    _whats_wrong: "AirCap Hood is healthy but energy use has trended 6% above fleet average for the past 5 days. Likely related to ambient temperature increase.",
    _recommendation: "Continue monitoring. If energy use stays elevated past May 1, consider recalibrating burner control loop.",
  },
  "al-sindian:softreel": {
    top_contributing_sensors: [{ sensor_type: "softreel_tension", contribution_percent: 80 }],
    _whats_wrong: "SoftReel Reel is healthy. Tension control is steady.",
    _recommendation: "No action required.",
  },
  "al-sindian:rewinder": {
    top_contributing_sensors: [{ sensor_type: "rewinder_speed", contribution_percent: 78 }],
    _whats_wrong: "Rewinder is healthy. No recent issues.",
    _recommendation: "No action required.",
  },

  // ─── Al Snobar ───
  "al-snobar:headbox": {
    top_contributing_sensors: [{ sensor_type: "headbox_stock_temp", contribution_percent: 75 }],
    _whats_wrong: "Headbox is healthy. The machine is currently idle so values reflect last operating window.",
    _recommendation: "No action required while idle.",
  },
  "al-snobar:visconip": {
    top_contributing_sensors: [
      { sensor_type: "visconip_felt_moisture", contribution_percent: 60 },
      { sensor_type: "visconip_nip_pressure",  contribution_percent: 28 },
    ],
    _whats_wrong: "ViscoNip Press is healthy. Felt is at 45% of expected service life.",
    _recommendation: "No action required. Felt change projected for August.",
  },
  "al-snobar:yankee": {
    top_contributing_sensors: [
      { sensor_type: "yankee_vibration_bearing_3", contribution_percent: 40 },
      { sensor_type: "yankee_surface_temp",        contribution_percent: 35 },
      { sensor_type: "yankee_steam_pressure",      contribution_percent: 18 },
    ],
    _whats_wrong: "Yankee Cylinder is the highest-risk component on Al Snobar but still healthy (25/100). The model is tracking a small Bearing 3 vibration uptick from previous operating runs — likely benign, will reassess once the machine restarts.",
    _recommendation: "No action required. Continue monitoring after restart.",
  },
  "al-snobar:aircap": {
    top_contributing_sensors: [
      { sensor_type: "aircap_inlet_temp", contribution_percent: 62 },
      { sensor_type: "aircap_energy",     contribution_percent: 28 },
    ],
    _whats_wrong: "AirCap Hood is healthy.",
    _recommendation: "No action required.",
  },
  "al-snobar:softreel": {
    top_contributing_sensors: [{ sensor_type: "softreel_tension", contribution_percent: 82 }],
    _whats_wrong: "SoftReel Reel is healthy.",
    _recommendation: "No action required.",
  },
  "al-snobar:rewinder": {
    top_contributing_sensors: [{ sensor_type: "rewinder_speed", contribution_percent: 78 }],
    _whats_wrong: "Rewinder is healthy.",
    _recommendation: "No action required.",
  },
};

function buildComponentRisk(machineId, componentId) {
  const detail = COMPONENT_RISK_DETAIL[`${machineId}:${componentId}`];
  if (!detail) return null;
  const components = buildComponents(machineId).components;
  const comp = components.find((c) => c.component_id === componentId);
  return {
    machine_id: machineId,
    component_id: componentId,
    score: comp.risk_score,
    tier: comp.risk_tier,
    predicted_failure_window_hours: detail.predicted_failure_window_hours ?? null,
    top_contributing_sensors: detail.top_contributing_sensors,
    last_updated: "2026-04-25T14:30:00Z",
    // Extension fields the UI uses for plain-English copy:
    _whats_wrong: detail._whats_wrong,
    _recommendation: detail._recommendation,
  };
}

// ────────────── Per-machine predictions ──────────────
function buildPredictions(machineId) {
  const order = ["headbox", "visconip", "yankee", "aircap", "softreel", "rewinder"];
  const scores = COMPONENT_RISK_SCORES[machineId];
  return {
    machine_id: machineId,
    predictions: order.map((cid) => {
      const score = scores[cid];
      const detail = COMPONENT_RISK_DETAIL[`${machineId}:${cid}`];
      // Failure probability ≈ score/100 with mild dampening for healthy band
      let prob;
      if (score >= 80) prob = score / 100;
      else if (score >= 35) prob = (score / 100) * 0.6;
      else prob = (score / 100) * 0.3;
      prob = Number(prob.toFixed(2));
      return {
        component_id: cid,
        failure_probability: prob,
        predicted_failure_window_hours: detail?.predicted_failure_window_hours ?? null,
        confidence: 0.82,
        recommended_action: detail?._recommendation || "Continue monitoring. No action required.",
      };
    }),
    generated_at: "2026-04-25T14:30:00Z",
  };
}

// ────────────── Per-machine alarms ──────────────
const MOCK_ALARMS_BY_MACHINE = {
  "al-nakheel": [
    { alarm_id: "alm-2026-04-25-0083", timestamp: "2026-04-25T13:45:00Z", severity: "critical", description: "Yankee bearing 3 vibration exceeded 6.0 mm/s — predicted failure imminent", resolved_at: null, downtime_minutes: 0 },
    { alarm_id: "alm-2026-04-25-0079", timestamp: "2026-04-25T11:08:00Z", severity: "warning",  description: "Yankee bearing 3 vibration above 5.0 mm/s threshold", resolved_at: null, downtime_minutes: 0 },
    { alarm_id: "alm-2026-04-25-0064", timestamp: "2026-04-25T05:22:00Z", severity: "warning",  description: "Yankee surface temperature drift outside normal envelope", resolved_at: "2026-04-25T06:01:00Z", downtime_minutes: 0 },
    { alarm_id: "alm-2026-04-24-0118", timestamp: "2026-04-24T22:14:00Z", severity: "info",     description: "AirCap inlet temperature soft-warning, auto-resolved", resolved_at: "2026-04-24T22:16:00Z", downtime_minutes: 0 },
    { alarm_id: "alm-2026-04-24-0101", timestamp: "2026-04-24T17:50:00Z", severity: "info",     description: "Reel diameter target reached — set change complete", resolved_at: "2026-04-24T17:50:00Z", downtime_minutes: 0 },
  ],
  "al-bardi": [
    { alarm_id: "alm-2026-04-25-0091", timestamp: "2026-04-25T12:30:00Z", severity: "info",     description: "Reel diameter target reached — set change complete", resolved_at: "2026-04-25T12:30:00Z", downtime_minutes: 0 },
    { alarm_id: "alm-2026-04-25-0072", timestamp: "2026-04-25T09:14:00Z", severity: "info",     description: "Felt moisture nominal after wash-up cycle", resolved_at: "2026-04-25T09:14:00Z", downtime_minutes: 0 },
    { alarm_id: "alm-2026-04-24-0096", timestamp: "2026-04-24T19:02:00Z", severity: "info",     description: "Stock temperature regulator auto-tuned", resolved_at: "2026-04-24T19:02:00Z", downtime_minutes: 0 },
  ],
  "al-sindian": [
    { alarm_id: "alm-2026-04-25-0085", timestamp: "2026-04-25T13:10:00Z", severity: "warning",  description: "ViscoNip felt moisture trending above 55% baseline", resolved_at: null, downtime_minutes: 0 },
    { alarm_id: "alm-2026-04-25-0070", timestamp: "2026-04-25T08:48:00Z", severity: "info",     description: "AirCap energy use 6% above fleet baseline", resolved_at: null, downtime_minutes: 0 },
    { alarm_id: "alm-2026-04-24-0103", timestamp: "2026-04-24T16:20:00Z", severity: "info",     description: "Reel diameter target reached — set change complete", resolved_at: "2026-04-24T16:20:00Z", downtime_minutes: 0 },
    { alarm_id: "alm-2026-04-24-0088", timestamp: "2026-04-24T11:05:00Z", severity: "info",     description: "Routine self-test passed", resolved_at: "2026-04-24T11:05:00Z", downtime_minutes: 0 },
  ],
  "al-snobar": [
    { alarm_id: "alm-2026-04-25-0061", timestamp: "2026-04-25T07:00:00Z", severity: "info",     description: "Machine entered idle state per scheduled maintenance plan", resolved_at: "2026-04-25T07:00:00Z", downtime_minutes: 0 },
    { alarm_id: "alm-2026-04-24-0094", timestamp: "2026-04-24T18:30:00Z", severity: "info",     description: "Headbox stock temperature normalized", resolved_at: "2026-04-24T18:30:00Z", downtime_minutes: 0 },
  ],
};

// ────────────── Per-machine maintenance log ──────────────
const MOCK_MAINTENANCE_LOG_BY_MACHINE = {
  "al-nakheel": [
    { log_id: "mlog-2026-04-09-002", component_id: "aircap",   maintenance_type: "preventive", date_performed: "2026-04-09", cost_usd:  4200, downtime_hours: 2, technician: "S. Antar",  notes: "Hood seal inspection. Burner alignment verified." },
    { log_id: "mlog-2026-03-22-007", component_id: "rewinder", maintenance_type: "predictive", date_performed: "2026-03-22", cost_usd:  6800, downtime_hours: 3, technician: "M. Khalil", notes: "Replaced rewinder belt — wear flagged by model 5 days early." },
    { log_id: "mlog-2026-02-12-001", component_id: "headbox",  maintenance_type: "preventive", date_performed: "2026-02-12", cost_usd:  3100, downtime_hours: 2, technician: "L. Haddad", notes: "Cleaned slice lip. Stock temperature sensor recalibrated." },
    { log_id: "mlog-2026-01-29-004", component_id: "visconip", maintenance_type: "preventive", date_performed: "2026-01-29", cost_usd:  5400, downtime_hours: 3, technician: "S. Antar",  notes: "Felt change. Nip pressure baseline reset." },
    { log_id: "mlog-2026-01-15-001", component_id: "yankee",   maintenance_type: "preventive", date_performed: "2026-01-15", cost_usd: 12500, downtime_hours: 6, technician: "M. Khalil", notes: "Replaced creping blade. Vibration baseline reset." },
  ],
  "al-bardi": [
    { log_id: "mlog-2026-03-25-002", component_id: "softreel", maintenance_type: "preventive", date_performed: "2026-03-25", cost_usd:  2200, downtime_hours: 1, technician: "H. Naser",  notes: "Routine reel inspection. No findings." },
    { log_id: "mlog-2026-03-18-001", component_id: "aircap",   maintenance_type: "preventive", date_performed: "2026-03-18", cost_usd:  3800, downtime_hours: 2, technician: "S. Antar",  notes: "Hood seal check. All within spec." },
    { log_id: "mlog-2026-03-15-003", component_id: "rewinder", maintenance_type: "preventive", date_performed: "2026-03-15", cost_usd:  3200, downtime_hours: 2, technician: "L. Haddad", notes: "Belt tension verified." },
    { log_id: "mlog-2026-03-10-002", component_id: "headbox",  maintenance_type: "preventive", date_performed: "2026-03-10", cost_usd:  2900, downtime_hours: 2, technician: "H. Naser",  notes: "Slice lip cleaned." },
    { log_id: "mlog-2026-02-08-001", component_id: "yankee",   maintenance_type: "preventive", date_performed: "2026-02-08", cost_usd: 11200, downtime_hours: 6, technician: "M. Khalil", notes: "Creping blade replacement. Baseline reset." },
  ],
  "al-sindian": [
    { log_id: "mlog-2026-03-12-004", component_id: "yankee",   maintenance_type: "preventive", date_performed: "2026-03-12", cost_usd: 11800, downtime_hours: 6, technician: "M. Khalil", notes: "Blade replacement." },
    { log_id: "mlog-2026-03-08-002", component_id: "softreel", maintenance_type: "preventive", date_performed: "2026-03-08", cost_usd:  2400, downtime_hours: 1, technician: "H. Naser",  notes: "Reel hardware tightened." },
    { log_id: "mlog-2026-02-28-003", component_id: "headbox",  maintenance_type: "preventive", date_performed: "2026-02-28", cost_usd:  3000, downtime_hours: 2, technician: "L. Haddad", notes: "Slice cleaned. Sensor recalibrated." },
    { log_id: "mlog-2026-02-18-001", component_id: "aircap",   maintenance_type: "corrective", date_performed: "2026-02-18", cost_usd:  5600, downtime_hours: 3, technician: "S. Antar",  notes: "Burner control loop adjustment after temp drift." },
    { log_id: "mlog-2026-01-08-001", component_id: "visconip", maintenance_type: "preventive", date_performed: "2026-01-08", cost_usd:  5200, downtime_hours: 3, technician: "S. Antar",  notes: "Felt change. Nip pressure baseline reset." },
  ],
  "al-snobar": [
    { log_id: "mlog-2026-02-22-001", component_id: "softreel", maintenance_type: "preventive", date_performed: "2026-02-22", cost_usd:  2300, downtime_hours: 1, technician: "H. Naser",  notes: "Routine inspection." },
    { log_id: "mlog-2026-02-14-002", component_id: "aircap",   maintenance_type: "preventive", date_performed: "2026-02-14", cost_usd:  3900, downtime_hours: 2, technician: "S. Antar",  notes: "Hood seal verified." },
    { log_id: "mlog-2026-02-08-003", component_id: "rewinder", maintenance_type: "preventive", date_performed: "2026-02-08", cost_usd:  3100, downtime_hours: 2, technician: "L. Haddad", notes: "Belt tension verified." },
    { log_id: "mlog-2026-01-22-001", component_id: "headbox",  maintenance_type: "preventive", date_performed: "2026-01-22", cost_usd:  2800, downtime_hours: 2, technician: "L. Haddad", notes: "Slice cleaned." },
    { log_id: "mlog-2026-01-04-002", component_id: "visconip", maintenance_type: "preventive", date_performed: "2026-01-04", cost_usd:  5100, downtime_hours: 3, technician: "S. Antar",  notes: "Felt change." },
    { log_id: "mlog-2025-12-18-005", component_id: "yankee",   maintenance_type: "preventive", date_performed: "2025-12-18", cost_usd: 11500, downtime_hours: 6, technician: "M. Khalil", notes: "Major service. Bearing inspection. Baseline reset." },
  ],
};

// ────────────── Per-page suggested prompts ──────────────
const MOCK_SUGGESTED_PROMPTS_OVERVIEW = {
  prompts: [
    "What's wrong with Al Nakheel right now?",
    "Compare risk across all 4 machines",
    "When should I schedule the next maintenance window?",
    "How will Ramadan affect production capacity?",
  ],
};
const MOCK_SUGGESTED_PROMPTS_ALERTS = {
  prompts: [
    "What's the most urgent alert right now?",
    "Group active alerts by machine",
    "Should I acknowledge the Al Bardi reel oscillation?",
    "What's our average response time this week?",
  ],
};
const MOCK_SUGGESTED_PROMPTS_MACHINE = {
  "al-nakheel": { prompts: [
    "Why is Yankee red?",
    "Should I delay maintenance on this machine?",
    "Compare Bearing 3 to other machines",
    "What caused the last critical alarm?",
  ]},
  "al-bardi": { prompts: [
    "Why is Al Bardi the healthiest machine?",
    "Could Al Bardi cover for Al Nakheel during downtime?",
    "What is OEE on this machine over the last 30 days?",
    "Show me Al Bardi's maintenance schedule",
  ]},
  "al-sindian": { prompts: [
    "Why is ViscoNip orange?",
    "When should I change the felt?",
    "What caused the recent warning alarm?",
    "Compare Al Sindian's OEE to fleet average",
  ]},
  "al-snobar": { prompts: [
    "Why is Al Snobar idle?",
    "When is Al Snobar scheduled to restart?",
    "What was the last major service performed?",
    "Show me Al Snobar's risk trend",
  ]},
};

// ────────────── Sensor history (Yankee deep-dive only) ──────────────
function makeHistory(sensorType, normalMin, normalMax, opts = {}) {
  const days = 30;
  const points = [];
  const start = new Date("2026-03-26T00:00:00Z").getTime();
  const dayMs = 24 * 60 * 60 * 1000;
  const center = (normalMin + normalMax) / 2;
  const spread = (normalMax - normalMin) / 2;
  const climbStart = opts.climbAfter ?? null;
  const climbPerDay = opts.climbPerDay ?? 0;
  const climbBase = opts.climbBase ?? center;
  for (let d = 0; d < days; d++) {
    const ts = new Date(start + d * dayMs).toISOString();
    let v;
    if (climbStart != null && d >= climbStart) {
      v = climbBase + climbPerDay * (d - climbStart);
    } else {
      const wiggle = Math.sin(d * 0.7) * spread * 0.35 + (Math.cos(d * 1.3) * spread * 0.18);
      v = center + wiggle;
    }
    points.push({
      timestamp: ts,
      value: Number(v.toFixed(2)),
      min: Number((v - spread * 0.18).toFixed(2)),
      max: Number((v + spread * 0.18).toFixed(2)),
    });
  }
  return {
    machine_id: "al-nakheel",
    sensor_type: sensorType,
    unit: opts.unit,
    window: "30d",
    aggregation: "daily",
    normal_range: { min: normalMin, max: normalMax },
    points,
  };
}

const MOCK_SENSOR_HISTORY = {
  yankee_surface_temp:        makeHistory("yankee_surface_temp",        100, 120, { unit: "°C" }),
  yankee_steam_pressure:      makeHistory("yankee_steam_pressure",        8,  10, { unit: "bar" }),
  yankee_vibration_bearing_1: makeHistory("yankee_vibration_bearing_1",   2,   4, { unit: "mm/s" }),
  yankee_vibration_bearing_2: makeHistory("yankee_vibration_bearing_2",   2,   4, { unit: "mm/s" }),
  yankee_vibration_bearing_3: makeHistory("yankee_vibration_bearing_3",   2,   4, { unit: "mm/s", climbAfter: 19, climbPerDay: 0.4, climbBase: 3.4 }),
  yankee_blade_pressure:      makeHistory("yankee_blade_pressure",       80, 120, { unit: "kPa" }),
};

// ────────────── /products + /markets + /forecast + /demand/seasonality ──────────────
const MOCK_MARKETS = {
  markets: [
    { market_id: "uae",     name: "United Arab Emirates", currency: "AED" },
    { market_id: "ksa",     name: "Saudi Arabia",         currency: "SAR" },
    { market_id: "jordan",  name: "Jordan",               currency: "JOD" },
    { market_id: "egypt",   name: "Egypt",                currency: "EGP" },
    { market_id: "morocco", name: "Morocco",              currency: "MAD" },
  ],
};

const PRODUCT_CATALOG = [
  // tissue
  ["fine-facial-100",   "Fine Facial Tissue 100ct",        "tissue",     "box"],
  ["fine-facial-150",   "Fine Facial Tissue 150ct",        "tissue",     "box"],
  ["fine-facial-200",   "Fine Facial Tissue 200ct",        "tissue",     "box"],
  ["fine-facial-cube",  "Fine Facial Cube 80ct",           "tissue",     "box"],
  ["fine-facial-pocket","Fine Facial Pocket Pack 10ct",    "tissue",     "pack"],
  ["fine-bath-double",  "Fine Bath Tissue Double Roll",    "tissue",     "pack"],
  ["fine-bath-mega",    "Fine Bath Tissue Mega Roll",      "tissue",     "pack"],
  ["fine-bath-12",      "Fine Bath Tissue 12 Pack",        "tissue",     "pack"],
  ["fine-kitchen-2pk",  "Fine Kitchen Towel 2 Pack",       "tissue",     "pack"],
  ["fine-kitchen-mega", "Fine Kitchen Towel Mega",         "tissue",     "pack"],
  ["fine-napkin-100",   "Fine Napkin 100ct",               "tissue",     "pack"],
  ["fine-napkin-200",   "Fine Napkin 200ct",               "tissue",     "pack"],
  ["fine-tabletop",     "Fine Tabletop Napkins",           "tissue",     "pack"],
  // baby_care
  ["fine-baby-s1",      "Fine Baby Diaper Size 1",         "baby_care",  "pack"],
  ["fine-baby-s2",      "Fine Baby Diaper Size 2",         "baby_care",  "pack"],
  ["fine-baby-s3",      "Fine Baby Diaper Size 3",         "baby_care",  "pack"],
  ["fine-baby-s4",      "Fine Baby Diaper Size 4",         "baby_care",  "pack"],
  ["fine-baby-s5",      "Fine Baby Diaper Size 5",         "baby_care",  "pack"],
  ["fine-baby-wipes",   "Fine Baby Wet Wipes 64ct",        "baby_care",  "pack"],
  // adult_care
  ["fine-adult-m",      "Fine Adult Pants Medium",         "adult_care", "pack"],
  ["fine-adult-l",      "Fine Adult Pants Large",          "adult_care", "pack"],
  ["fine-adult-xl",     "Fine Adult Pants XL",             "adult_care", "pack"],
  ["fine-adult-pads",   "Fine Adult Pads",                 "adult_care", "pack"],
  // fine_guard (antibacterial line)
  ["fineguard-wipes",   "FineGuard Antibacterial Wipes",   "fine_guard", "pack"],
  ["fineguard-spray",   "FineGuard Surface Spray",         "fine_guard", "bottle"],
  ["fineguard-soap",    "FineGuard Hand Soap",             "fine_guard", "bottle"],
  ["fineguard-gel",     "FineGuard Hand Sanitizer Gel",    "fine_guard", "bottle"],
  // wellness
  ["wellness-fem-reg",  "Wellness Pads Regular",           "wellness",   "pack"],
  ["wellness-fem-sup",  "Wellness Pads Super",             "wellness",   "pack"],
  ["wellness-fem-night","Wellness Pads Overnight",         "wellness",   "pack"],
  ["wellness-tampons",  "Wellness Tampons Regular",        "wellness",   "pack"],
  ["wellness-panty",    "Wellness Pantyliners",            "wellness",   "pack"],
  // cosmetics
  ["cosmo-pads-round",  "Cosmetic Round Pads 80ct",        "cosmetics",  "pack"],
  ["cosmo-pads-square", "Cosmetic Square Pads 100ct",      "cosmetics",  "pack"],
  ["cosmo-rem-wipes",   "Cosmetic Makeup Remover Wipes",   "cosmetics",  "pack"],
  ["cosmo-cotton-buds", "Cosmetic Cotton Buds 200ct",      "cosmetics",  "pack"],
  ["cosmo-cotton-balls","Cosmetic Cotton Balls 100ct",     "cosmetics",  "pack"],
];
const MOCK_PRODUCTS = {
  products: PRODUCT_CATALOG.map(([sku, name, category, unit]) =>
    ({ sku, name, category, unit })),
  total: PRODUCT_CATALOG.length,
};

// MENA holiday calendar — Hijri-based, hand-tabulated for 2023-2026
const RAMADAN_RANGES = [
  { start: "2023-03-23", end: "2023-04-21" },
  { start: "2024-03-11", end: "2024-04-09" },
  { start: "2025-02-28", end: "2025-03-30" },
  { start: "2026-02-17", end: "2026-03-18" },
];
const EID_FITR_RANGES = [
  { start: "2023-04-22", end: "2023-04-25" },
  { start: "2024-04-10", end: "2024-04-13" },
  { start: "2025-03-31", end: "2025-04-03" },
  { start: "2026-03-19", end: "2026-03-22" },
];
const EID_ADHA_RANGES = [
  { start: "2023-06-28", end: "2023-07-01" },
  { start: "2024-06-16", end: "2024-06-19" },
  { start: "2025-06-06", end: "2025-06-09" },
  { start: "2026-05-26", end: "2026-05-29" },
];
function inRange(dateStr, ranges) {
  return ranges.find((r) => dateStr >= r.start && dateStr <= r.end);
}
function preRamadanWindow(dateStr) {
  for (const r of RAMADAN_RANGES) {
    const start = new Date(r.start);
    const stockStart = new Date(start.getTime() - 7 * 86400000).toISOString().slice(0, 10);
    const stockEnd   = new Date(start.getTime() - 1 * 86400000).toISOString().slice(0, 10);
    if (dateStr >= stockStart && dateStr <= stockEnd) return true;
  }
  return false;
}

// hash helper for deterministic per-SKU/market noise
function hash(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0);
}
function seededRand(seed) {
  let x = seed % 2147483647;
  return () => {
    x = (x * 16807) % 2147483647;
    return x / 2147483647;
  };
}

// per-SKU baseline daily volume (UAE × fine-facial-100 ≈ 6000)
function baselineDaily(sku, market) {
  const cat = (PRODUCT_CATALOG.find((p) => p[0] === sku) || [])[2] || "tissue";
  const catBase = {
    tissue: 5800, baby_care: 4400, adult_care: 1800,
    fine_guard: 1200, wellness: 2000, cosmetics: 1500,
  }[cat];
  const marketMul = { uae: 1.0, ksa: 1.45, jordan: 0.55, egypt: 1.25, morocco: 0.7 }[market] || 1;
  const skuVar = 0.7 + (hash(sku) % 1000) / 1500; // 0.7-1.36
  return Math.round(catBase * marketMul * skuVar);
}

// generate one daily series (history + forecast). yIsoStart inclusive, days count.
function generateDailySeries(sku, market, isoStart, days, isForecast) {
  const base = baselineDaily(sku, market);
  const start = new Date(isoStart);
  const cat = (PRODUCT_CATALOG.find((p) => p[0] === sku) || [])[2] || "tissue";
  const trendPctYear = 0.08; // +8% YoY underlying
  const rng = seededRand(hash(sku + market));
  const out = [];
  for (let i = 0; i < days; i++) {
    const d = new Date(start.getTime() + i * 86400000);
    const iso = d.toISOString().slice(0, 10);

    // trend (vs anchor 2025-04-30)
    const anchor = new Date("2025-04-30");
    const yearsFromAnchor = (d.getTime() - anchor.getTime()) / (365.25 * 86400000);
    const trend = Math.pow(1 + trendPctYear, yearsFromAnchor);

    // yearly seasonality — Gulf summer dip ~ -15%
    const dayOfYear = (d - new Date(d.getFullYear(), 0, 0)) / 86400000;
    const yearly = 1 + 0.06 * Math.cos((dayOfYear / 365) * 2 * Math.PI)         // mild winter peak
                     - 0.09 * Math.exp(-Math.pow((dayOfYear - 200) / 35, 2));   // Jul-Aug dip

    // weekly seasonality
    const dow = d.getDay();
    const weekly = [1.02, 0.96, 0.93, 0.96, 1.05, 1.10, 1.04][dow];

    // holiday effects
    let event = 1;
    if (preRamadanWindow(iso)) event *= (cat === "tissue" ? 1.43 : 1.30);
    if (inRange(iso, RAMADAN_RANGES)) event *= 1.21;
    const f = inRange(iso, EID_FITR_RANGES);
    if (f) {
      const dayIdx = (new Date(iso) - new Date(f.start)) / 86400000;
      event *= dayIdx === 0 ? 0.50 : dayIdx === 1 ? 1.05 : dayIdx === 2 ? 1.18 : 1.10;
    }
    const a = inRange(iso, EID_ADHA_RANGES);
    if (a) {
      const dayIdx = (new Date(iso) - new Date(a.start)) / 86400000;
      event *= dayIdx === 0 ? 0.70 : dayIdx === 1 ? 1.08 : 1.12;
    }

    const noise = 1 + (rng() - 0.5) * (isForecast ? 0.04 : 0.10);
    const value = Math.round(base * trend * yearly * weekly * event * noise);

    if (isForecast) {
      const ci = 0.22; // ±22% of forecast value (widens slightly with horizon)
      const horizPct = i / days * 0.06;
      out.push({
        date: iso,
        forecast_value: value,
        lower_bound: Math.round(value * (1 - ci - horizPct)),
        upper_bound: Math.round(value * (1 + ci + horizPct)),
      });
    } else {
      out.push({ date: iso, actual: value });
    }
  }
  return out;
}

// /forecast?sku=...&market=...&horizon_months=...
function buildForecastResponse(sku, market, horizonDays) {
  // Demo anchor: today is 2026-04-30. History 365d back, forecast 120d ahead.
  const today = new Date("2026-04-30");
  const historyStart = new Date(today.getTime() - 365 * 86400000).toISOString().slice(0, 10);
  const forecastStart = new Date(today.getTime() + 1 * 86400000).toISOString().slice(0, 10);
  const history = generateDailySeries(sku, market, historyStart, 365, false);
  const forecast = generateDailySeries(sku, market, forecastStart, horizonDays, true);

  const seasonality_events = [
    { date: "2026-02-10", label: "Pre-Ramadan stockup begins", expected_lift_percent: 43 },
    { date: "2026-02-17", label: "Ramadan begins",             expected_lift_percent: 21 },
    { date: "2026-03-19", label: "Eid al-Fitr",                expected_lift_percent: 22 },
    { date: "2026-05-26", label: "Eid al-Adha",                expected_lift_percent: 12 },
  ];
  return {
    sku, market,
    horizon_months: Math.round(horizonDays / 30),
    model: "prophet",
    history,                 // UI-extension: daily history alongside forecast
    forecast,
    seasonality_events,
    regressors_used: [
      "historical_sales", "ramadan_calendar", "is_ramadan", "ramadan_day",
      "is_eid_alfitr", "is_eid_aladha", "is_pre_ramadan_stockup",
      "weekly_seasonality", "yearly_seasonality", "trend",
    ],
    accuracy: {
      mape_percent: 4.25,
      forecast_confidence_percent: 96,
      last_month_actual: 8720,
      last_month_predicted: 8400,
      last_month_variance_percent: 3.8,
      best_market: { market_id: "ksa", accuracy_percent: 96.1 },
      worst_market: { market_id: "morocco", accuracy_percent: 89.3 },
    },
    drivers: [
      { id: "ramadan",          icon: "🌙", label: "Ramadan effect",       lift_percent: 21.0,  detail: "March 2026 elevation over baseline." },
      { id: "eid_fitr_dip",     icon: "🎉", label: "Eid Al-Fitr Day-1 dip", lift_percent: -50.0, detail: "Factory shutdown effect on first day of Eid." },
      { id: "yoy_trend",        icon: "📈", label: "Year-over-year trend",   lift_percent: 8.0,   detail: "Underlying market growth, sustained 24+ months." },
      { id: "summer_dip",       icon: "🌡️", label: "Summer (Jun–Aug)",      lift_percent: -15.0, detail: "Gulf summer slowdown across tissue category." },
      { id: "pre_ramadan",      icon: "🛍️", label: "Pre-Ramadan stockup",  lift_percent: 43.3,  detail: "7-day window before Ramadan; retailers restock." },
      { id: "marketing",        icon: "🎯", label: "Last marketing campaign", lift_percent: 18.0,  detail: "+18% lift over 6 days following the March 2026 push." },
    ],
    generated_at: "2026-04-28T14:30:00Z",
  };
}

// /demand/seasonality?sku=...&market=...
function buildSeasonalityResponse(sku, market) {
  const yearly_pattern = [];
  for (let m = 1; m <= 12; m++) {
    // heuristic: winter slight peak, summer dip
    const base = 1 + 0.08 * Math.cos(((m - 1) / 12) * 2 * Math.PI)
                   - 0.10 * Math.exp(-Math.pow((m - 7) / 1.6, 2));
    yearly_pattern.push({ month: m, index: +base.toFixed(3) });
  }
  return {
    sku, market,
    yearly_pattern,
    events: [
      { name: "ramadan",       average_lift_percent: 21 },
      { name: "eid_al_fitr",   average_lift_percent: 22 },
      { name: "eid_al_adha",   average_lift_percent: 12 },
      { name: "pre_ramadan",   average_lift_percent: 43 },
      { name: "back_to_school", average_lift_percent: 12 },
    ],
  };
}

const MOCK_SUGGESTED_PROMPTS_DEMAND = {
  prompts: [
    "Why is March forecast so high?",
    "How will Ramadan affect production?",
    "Compare UAE and KSA demand",
    "What if Ramadan started a week earlier?",
  ],
};
window.api = {
  async get(path, params = {}) {
    const qs = Object.keys(params).length
      ? "?" + new URLSearchParams(params).toString()
      : "";
    console.log("GET", path + qs);
    await new Promise((r) => setTimeout(r, 60));

    if (path === "/kpis/overview") return MOCK_KPIS_OVERVIEW;
    if (path === "/machines") return MOCK_MACHINES;

    // /machines/{id}
    const machineMatch = path.match(/^\/machines\/([a-z-]+)$/);
    if (machineMatch) {
      return MOCK_MACHINES.machines.find((m) => m.machine_id === machineMatch[1]);
    }
    // /machines/{id}/risk-score
    const riskMatch = path.match(/^\/machines\/([a-z-]+)\/risk-score$/);
    if (riskMatch) return buildRiskScore(riskMatch[1]);

    // /machines/{id}/components
    const compsMatch = path.match(/^\/machines\/([a-z-]+)\/components$/);
    if (compsMatch) return buildComponents(compsMatch[1]);

    // /machines/{id}/components/{cid}/risk-score
    const compRiskMatch = path.match(/^\/machines\/([a-z-]+)\/components\/([a-z]+)\/risk-score$/);
    if (compRiskMatch) return buildComponentRisk(compRiskMatch[1], compRiskMatch[2]);

    // /machines/{id}/predictions
    const predMatch = path.match(/^\/machines\/([a-z-]+)\/predictions$/);
    if (predMatch) return buildPredictions(predMatch[1]);

    // /machines/{id}/alarms
    const alarmsMatch = path.match(/^\/machines\/([a-z-]+)\/alarms$/);
    if (alarmsMatch) {
      const list = MOCK_ALARMS_BY_MACHINE[alarmsMatch[1]] || [];
      return { machine_id: alarmsMatch[1], alarms: list, total: list.length };
    }

    // /machines/{id}/maintenance-log
    const mlogMatch = path.match(/^\/machines\/([a-z-]+)\/maintenance-log$/);
    if (mlogMatch) {
      const logs = MOCK_MAINTENANCE_LOG_BY_MACHINE[mlogMatch[1]] || [];
      return { machine_id: mlogMatch[1], logs };
    }

    // /machines/al-nakheel/sensors/{type}/history
    const sensMatch = path.match(/^\/machines\/al-nakheel\/sensors\/([a-z0-9_]+)\/history$/);
    if (sensMatch) return MOCK_SENSOR_HISTORY[sensMatch[1]];

    if (path === "/alerts") {
      const filters = (a) => {
        if (params.severity && a.severity !== params.severity) return false;
        if (params.machine_id && a.machine_id !== params.machine_id) return false;
        if (params.acknowledged != null) {
          const ackBool = String(params.acknowledged) === "true";
          if (a.acknowledged !== ackBool) return false;
        }
        if (params.status && a._status !== params.status) return false;
        return true;
      };
      const resp = alertsResponse(filters, params.sort || "severity");
      if (params.limit) resp.alerts = resp.alerts.slice(0, +params.limit);
      return resp;
    }

    // /alerts/{alert_id}
    const alertOneMatch = path.match(/^\/alerts\/(alt-[\w-]+)$/);
    if (alertOneMatch) {
      return MOCK_ALL_ALERTS.find((a) => a.alert_id === alertOneMatch[1]);
    }

    // /alerts/kpis  — UI extension; powers Screen 3 KPI strip
    if (path === "/alerts/kpis") return MOCK_ALERTS_KPIS;

    if (path === "/products") return MOCK_PRODUCTS;
    if (path === "/markets") return MOCK_MARKETS;
    if (path === "/forecast") {
      const horizonDays = (+params.horizon_months || 4) * 30;
      return buildForecastResponse(params.sku, params.market, horizonDays);
    }
    if (path === "/demand/seasonality") {
      return buildSeasonalityResponse(params.sku, params.market);
    }
    if (path === "/chat/suggested-prompts") {
      if (params.current_page === "demand_forecast") return MOCK_SUGGESTED_PROMPTS_DEMAND;
      if (params.current_page === "alerts") return MOCK_SUGGESTED_PROMPTS_ALERTS;
      if (params.current_page === "machine_detail" && params.current_machine_id) {
        return MOCK_SUGGESTED_PROMPTS_MACHINE[params.current_machine_id]
          || MOCK_SUGGESTED_PROMPTS_OVERVIEW;
      }
      return MOCK_SUGGESTED_PROMPTS_OVERVIEW;
    }
    throw new Error("no mock for " + path);
  },
  async post(path, body) {
    console.log("POST", path, body);
    if (path === "/chat") return await postChat(body);
    throw new Error("no mock for " + path);
  },
  async del(path) {
    console.log("DELETE", path);
    return null;
  },
};

// ────────────── POST /chat — Claude-powered ──────────────
async function postChat(body) {
  const { message, conversation_id, context } = body;
  const cid = conversation_id || "conv-" + Math.random().toString(36).slice(2, 9);

  const sysContext = `
You are FHH AI, an embedded assistant inside the FHH AI Optimizer dashboard for a tissue-paper manufacturer with 4 Valmet machines: Al Nakheel (Abu Dhabi, UAE), Al Bardi (Egypt), Al Sindian (Egypt), Al Snobar (Jordan).

Live fleet snapshot (you may reference these numbers verbatim):
- Fleet avg OEE: 93.7%
- Machines running: 3 of 4 (Al Snobar idle)
- Active critical alerts: 1, warning alerts: 2
- Cost saved MTD: $280,000

Machine risk scores (0–100):
- Al Nakheel: 67 (warning) — 2 alerts. Yankee Cylinder bearing 3 vibration at 5.8 mm/s vs 2–4 mm/s normal range, climbing 0.4 mm/s/day for 11 days. Predicted failure in 48h. Cost if ignored: $480K.
- Al Sindian: 45 (watch) — 1 alert. ViscoNip felt moisture trending up; felt change recommended within 7 days.
- Al Bardi: 28 (healthy)
- Al Snobar: 22 (healthy, idle)

Current page context: ${context?.current_page || "unknown"}${
    context?.current_machine_id ? `, machine=${context.current_machine_id}` : ""
  }${context?.current_component_id ? `, component=${context.current_component_id}` : ""}.

Reply in 2–4 sentences, conversational, plain English. Reference real numbers and IDs from above. End with a JSON block of this exact shape on its own line:
<<META>>{"data_sources_used":["..."],"suggested_followups":["...","...","..."]}<<END>>

User message: ${message}
`.trim();

  let raw;
  try {
    raw = await window.claude.complete(sysContext);
  } catch (e) {
    raw = "I couldn't reach the model just now. Try again in a moment.<<META>>{\"data_sources_used\":[],\"suggested_followups\":[]}<<END>>";
  }

  let reply = raw;
  let data_sources_used = [];
  let suggested_followups = [];
  const m = raw.match(/<<META>>([\s\S]*?)<<END>>/);
  if (m) {
    reply = raw.slice(0, m.index).trim();
    try {
      const parsed = JSON.parse(m[1]);
      data_sources_used = parsed.data_sources_used || [];
      suggested_followups = parsed.suggested_followups || [];
    } catch (e) {}
  }

  return {
    conversation_id: cid,
    reply,
    data_sources_used,
    suggested_followups,
    timestamp: new Date().toISOString(),
  };
}
