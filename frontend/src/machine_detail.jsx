// Machine Detail screen — wired entirely against /machines/{id}/* endpoints.

const { useEffect: useEffectMd, useState: useStateMd, useMemo } = React;

// Component label map — never expose component_ids directly to the user.
const COMPONENT_LABEL = {
  headbox:  "Headbox",
  visconip: "ViscoNip Press",
  yankee:   "Yankee Cylinder",
  aircap:   "AirCap Hood",
  softreel: "SoftReel Reel",
  rewinder: "Rewinder",
};
// Sensor plain-English labels — never expose sensor_type IDs.
const SENSOR_LABEL = {
  yankee_surface_temp:        "Surface temperature",
  yankee_steam_pressure:      "Steam pressure",
  yankee_vibration_bearing_1: "Bearing 1 vibration",
  yankee_vibration_bearing_2: "Bearing 2 vibration",
  yankee_vibration_bearing_3: "Bearing 3 vibration",
  yankee_blade_pressure:      "Blade pressure",
  visconip_nip_pressure:      "Nip pressure",
  visconip_felt_moisture:     "Felt moisture",
  aircap_inlet_temp:          "Hood inlet temp",
  aircap_energy:              "Hood energy use",
  headbox_stock_temp:         "Stock temperature",
  softreel_tension:           "Reel tension",
  rewinder_speed:             "Rewinder speed",
  qcs_softness_index:         "Softness index",
};

// ───────────────────────────── Risk Gauge ─────────────────────────────
function RiskGauge({ score, tier, highestRiskComponentId }) {
  const meta = TIER_META[tier] || TIER_META.healthy;
  const size = 168, stroke = 14;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const dash = (score / 100) * c;
  return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "center",
      justifyContent: "center", padding: "8px 12px",
    }}>
      <div style={{ position: "relative", width: size, height: size }}>
        <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
          <circle cx={size/2} cy={size/2} r={r} stroke="#EFF1F5" strokeWidth={stroke} fill="none" />
          <circle cx={size/2} cy={size/2} r={r} stroke={meta.dot} strokeWidth={stroke} fill="none"
            strokeDasharray={`${dash} ${c-dash}`} strokeLinecap="round"
            style={{ transition: "stroke-dasharray .6s ease" }} />
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column",
          alignItems: "center", justifyContent: "center" }}>
          <div style={{ fontSize: 44, fontWeight: 600, color: meta.fg, lineHeight: 1,
            fontVariantNumeric: "tabular-nums", letterSpacing: -1 }}>{score}</div>
          <div style={{ fontSize: 12, color: "#9CA3AF", marginTop: 2 }}>/ 100</div>
        </div>
      </div>
      <div style={{ marginTop: 12 }}><TierPill tier={tier} /></div>
      {highestRiskComponentId && (
        <div style={{ marginTop: 10, fontSize: 12, color: "#6B7280", textAlign: "center" }}>
          Highest-risk component:{" "}
          <span style={{ color: "#0A1F44", fontWeight: 600 }}>
            {COMPONENT_LABEL[highestRiskComponentId] || highestRiskComponentId}
          </span>
        </div>
      )}
    </div>
  );
}

// ─────────────────── Predicted Failure & Quick Stats ───────────────────
// Per-machine subhead/blurb for the Predicted Failure panel — keyed by
// machine_id and the component the model thinks is highest-risk.
const PREDICTED_FAILURE_BLURB = {
  "al-nakheel:yankee":   { sub: "Bearing 3",      blurb: "Bearing 3 vibration trending toward failure" },
  "al-sindian:visconip": { sub: "Felt service",   blurb: "Felt moisture trending above 55% baseline" },
  "al-bardi:yankee":     { sub: "Bearing 2 drift",blurb: "Mild drift inside healthy band — monitoring" },
  "al-snobar:yankee":    { sub: "Idle",           blurb: "Will reassess once machine restarts" },
};

function PredictedFailurePanel({ machineId, topPrediction, hot }) {
  if (!topPrediction) return <PanelShell />;
  const compName = COMPONENT_LABEL[topPrediction.component_id] || topPrediction.component_id;
  const pct = Math.round(topPrediction.failure_probability * 100);
  const blurb = PREDICTED_FAILURE_BLURB[`${machineId}:${topPrediction.component_id}`] || {};
  return (
    <div style={panelShell}>
      <div style={panelHeader}>Predicted Failure</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginTop: 12, flexWrap: "wrap" }}>
        <div style={{ fontSize: 40, fontWeight: 600, color: hot ? "#D7263D" : "#0F8B5C",
          fontVariantNumeric: "tabular-nums", letterSpacing: -1, lineHeight: 1 }}>{pct}%</div>
        {topPrediction.predicted_failure_window_hours != null ? (
          <div style={{ fontSize: 13, color: "#6B7280" }}>
            in {topPrediction.predicted_failure_window_hours}h
          </div>
        ) : (
          <div style={{ fontSize: 13, color: "#6B7280" }}>no near-term failure</div>
        )}
      </div>
      <div style={{ marginTop: 14, fontSize: 13, color: "#0A1F44", fontWeight: 600 }}>
        {compName}{blurb.sub ? ` · ${blurb.sub}` : ""}
      </div>
      <div style={{ fontSize: 12.5, color: "#4B5563", marginTop: 4, lineHeight: 1.45,
        textWrap: "pretty" }}>
        {blurb.blurb || (hot ? "Action needed soon" : "All components within normal envelope")}
      </div>
      {hot && (
        <button style={{ ...primaryBtn, marginTop: 16 }}
          onClick={() => window.dispatchEvent(new CustomEvent("fhh:chat:send",
            { detail: "Help me schedule maintenance for this machine" }))}>
          Schedule Maintenance
        </button>
      )}
    </div>
  );
}

function QuickStatsPanel({ machine, highestRiskComp, alertsCount }) {
  if (!machine) return <PanelShell />;
  const rows = [
    { label: "Speed",          val: `${machine.current_speed_mpm.toLocaleString()} m/min` },
    { label: "OEE",            val: `${machine.current_oee_percent.toFixed(1)}%` },
    { label: "Hours since maint.", val: highestRiskComp ? `${highestRiskComp.hours_since_last_maintenance.toLocaleString()} h` : "—" },
    { label: "Active alerts",  val: alertsCount, accent: alertsCount > 0 },
  ];
  return (
    <div style={panelShell}>
      <div style={panelHeader}>Quick Stats</div>
      <div style={{ display: "flex", flexDirection: "column", marginTop: 8 }}>
        {rows.map((r, i) => (
          <div key={i} style={{
            display: "flex", justifyContent: "space-between", alignItems: "center",
            padding: "11px 0",
            borderBottom: i < rows.length - 1 ? "1px solid #EFF1F5" : "none",
          }}>
            <div style={{ fontSize: 12.5, color: "#6B7280" }}>{r.label}</div>
            {r.accent ? (
              <span style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "3px 10px", borderRadius: 999,
                background: "#FFEDDD", color: "#B14A00",
                fontSize: 12.5, fontWeight: 600, fontVariantNumeric: "tabular-nums",
              }}>{r.val}</span>
            ) : (
              <div style={{ fontSize: 13, color: "#0A1F44", fontWeight: 600,
                fontVariantNumeric: "tabular-nums" }}>{r.val}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ───────────────────────── Component selector row ─────────────────────────
function ComponentTile({ comp, selected, onClick }) {
  const meta = TIER_META[comp.risk_tier] || TIER_META.healthy;
  return (
    <button
      onClick={() => onClick(comp.component_id)}
      style={{
        textAlign: "left",
        background: "white",
        border: selected ? "2px solid #0A1F44" : "1px solid #E5E8EE",
        borderRadius: 10,
        padding: selected ? "13px 15px" : "14px 16px",
        cursor: "pointer", fontFamily: "inherit",
        boxShadow: selected
          ? "0 4px 16px rgba(10,31,68,0.10)"
          : "0 1px 2px rgba(10,31,68,0.04)",
        transition: "transform .2s ease, box-shadow .2s ease, border-color .2s ease",
        display: "flex", flexDirection: "column", gap: 10,
        minHeight: 116,
      }}
      onMouseEnter={(e) => { if (!selected) { e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.boxShadow = "0 4px 14px rgba(10,31,68,0.08)"; }}}
      onMouseLeave={(e) => { if (!selected) { e.currentTarget.style.transform = "none"; e.currentTarget.style.boxShadow = "0 1px 2px rgba(10,31,68,0.04)"; }}}
    >
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 6 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: "#0A1F44", lineHeight: 1.3 }}>
          {COMPONENT_LABEL[comp.component_id]}
        </div>
        <TierPill tier={comp.risk_tier} size="sm" />
      </div>
      <div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
          <div style={{
            fontSize: 22, fontWeight: 600, color: meta.fg,
            fontVariantNumeric: "tabular-nums", letterSpacing: -0.4, lineHeight: 1,
          }}>{comp.risk_score}</div>
          <div style={{ fontSize: 12, color: "#9CA3AF" }}>/ 100</div>
        </div>
        <div style={{ marginTop: 8, height: 4, borderRadius: 2, background: "#EFF1F5", overflow: "hidden" }}>
          <div style={{ width: `${comp.risk_score}%`, height: "100%", background: meta.dot,
            transition: "width .4s ease" }} />
        </div>
      </div>
    </button>
  );
}

function ComponentRow({ components, selectedId, onSelect }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(6, minmax(0, 1fr))", gap: 10 }}>
      {components.map((c) => (
        <ComponentTile key={c.component_id} comp={c}
          selected={c.component_id === selectedId} onClick={onSelect} />
      ))}
    </div>
  );
}

// ─────────────────────── Component Detail Panel ───────────────────────
// Severity buckets:
//   critical / warning → red "What's wrong" card
//   watch              → orange "Watching" card
//   healthy            → green "Status check" card
function WhatsWrongCard({ component, risk }) {
  if (!component || !risk) return null;
  const tier = component.risk_tier;
  const tone = tier === "critical" || tier === "warning"
    ? "hot"
    : tier === "watch" ? "warm" : "cool";
  const palette = {
    hot:  { bg: "#FDEEF0", border: "#F0B5BB", chip: "#D7263D", fg: "#B31E2B", icon: "!", header: "What's wrong" },
    warm: { bg: "#FFF6EC", border: "#FFD4A8", chip: "#E66A12", fg: "#B14A00", icon: "!", header: "Watching" },
    cool: { bg: "#EAF7F0", border: "#BFE3CE", chip: "#15A56C", fg: "#0F8B5C", icon: "✓", header: "Status check" },
  }[tone];
  const body = risk._whats_wrong
    || `${COMPONENT_LABEL[component.component_id]} is at ${risk.score}/100 risk.`;
  return (
    <div style={{
      borderRadius: 10, border: `1px solid ${palette.border}`,
      background: palette.bg, padding: "16px 18px",
      display: "flex", gap: 12,
    }}>
      <div style={{
        width: 28, height: 28, borderRadius: 8,
        background: palette.chip, color: "white",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 14, fontWeight: 700, flexShrink: 0,
      }}>{palette.icon}</div>
      <div style={{ minWidth: 0 }}>
        <div style={{
          fontSize: 11, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase",
          color: palette.fg,
        }}>{palette.header}</div>
        <div style={{ fontSize: 13.5, color: "#1A2438", lineHeight: 1.55, marginTop: 4,
          textWrap: "pretty" }}>{body}</div>
      </div>
    </div>
  );
}

function ContributingSensorsCard({ sensors }) {
  if (!sensors || sensors.length === 0) return null;
  return (
    <div style={panelShell}>
      <div style={panelHeader}>Top contributing sensors</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
        {sensors.map((s) => (
          <div key={s.sensor_type}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
              <div style={{ fontSize: 13, color: "#0A1F44", fontWeight: 500 }}>
                {SENSOR_LABEL[s.sensor_type] || s.sensor_type}
              </div>
              <div style={{ fontSize: 13, color: "#0A1F44", fontWeight: 600,
                fontVariantNumeric: "tabular-nums" }}>{s.contribution_percent}%</div>
            </div>
            <div style={{ height: 8, background: "#EFF1F5", borderRadius: 4, overflow: "hidden" }}>
              <div style={{
                width: `${s.contribution_percent}%`, height: "100%",
                background: s.contribution_percent >= 50 ? "#D7263D"
                          : s.contribution_percent >= 25 ? "#E66A12" : "#15A56C",
                transition: "width .4s ease",
              }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RecommendedActionCard({ component, risk }) {
  if (!component || !risk) return null;
  const tier = component.risk_tier;
  const isHot = tier === "critical" || tier === "warning";
  const isWarm = tier === "watch";
  const accent = isHot ? "#D7263D" : isWarm ? "#E66A12" : "#15A56C";
  const body = risk._recommendation || "Continue monitoring. No action required.";
  return (
    <div style={{
      borderRadius: 10,
      border: "1px solid #E5E8EE",
      borderLeft: `3px solid ${accent}`,
      background: "white",
      padding: "16px 18px",
    }}>
      <div style={panelHeader}>Recommended action</div>
      <div style={{ fontSize: 13.5, color: "#1A2438", lineHeight: 1.55, marginTop: 8,
        textWrap: "pretty" }}>{body}</div>
      {(isHot || isWarm) && (
        <div style={{ display: "flex", gap: 10, marginTop: 14, flexWrap: "wrap" }}>
          <button style={primaryBtn}
            onClick={() => window.dispatchEvent(new CustomEvent("fhh:chat:send",
              { detail: `Help me schedule maintenance for ${COMPONENT_LABEL[component.component_id]} on this machine` }))}
          >Schedule Maintenance</button>
          <button style={secondaryBtn}
            onClick={() => window.dispatchEvent(new CustomEvent("fhh:chat:send",
              { detail: `Acknowledge the active alert on ${COMPONENT_LABEL[component.component_id]}` }))}
          >Acknowledge Alert</button>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────── Mini sensor chart ───────────────────────────
function SensorMiniChart({ sensorType, history, highlight }) {
  if (!history) return <div style={{ height: 150 }} />;
  const w = 280, h = 110, pad = 8;
  const pts = history.points;
  const allVals = pts.flatMap(p => [p.value, p.min, p.max]);
  const dataMin = Math.min(...allVals, history.normal_range.min);
  const dataMax = Math.max(...allVals, history.normal_range.max);
  const range = (dataMax - dataMin) || 1;
  const x = (i) => pad + (i / (pts.length - 1)) * (w - pad * 2);
  const y = (v) => pad + (1 - (v - dataMin) / range) * (h - pad * 2);
  const path = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(p.value).toFixed(1)}`).join(" ");

  // Normal range band
  const yNormalTop = y(history.normal_range.max);
  const yNormalBot = y(history.normal_range.min);
  const lastVal = pts[pts.length - 1].value;
  const inRange = lastVal >= history.normal_range.min && lastVal <= history.normal_range.max;

  const stroke = highlight ? "#D7263D" : (inRange ? "#0F8B5C" : "#E66A12");

  return (
    <div style={{
      background: "white",
      border: highlight ? "1.5px solid #F0B5BB" : "1px solid #E5E8EE",
      borderRadius: 10, padding: "12px 14px",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: "#0A1F44" }}>
          {SENSOR_LABEL[sensorType] || sensorType}
        </div>
        <div style={{ fontSize: 12, color: highlight ? "#D7263D" : "#0A1F44",
          fontVariantNumeric: "tabular-nums", fontWeight: 600 }}>
          {lastVal} {history.unit}
        </div>
      </div>
      <div style={{ fontSize: 10.5, color: "#6B7280", marginTop: 2 }}>
        Normal {history.normal_range.min}–{history.normal_range.max} {history.unit} · last 30 days
      </div>
      <svg width="100%" viewBox={`0 0 ${w} ${h}`} style={{ display: "block", marginTop: 6 }}>
        {/* normal range green band */}
        <rect x={pad} y={yNormalTop} width={w - pad*2} height={Math.max(0, yNormalBot - yNormalTop)}
          fill="#E6F6EE" />
        <line x1={pad} y1={yNormalTop} x2={w - pad} y2={yNormalTop} stroke="#0F8B5C" strokeDasharray="2 3" strokeWidth="0.75" />
        <line x1={pad} y1={yNormalBot} x2={w - pad} y2={yNormalBot} stroke="#0F8B5C" strokeDasharray="2 3" strokeWidth="0.75" />
        <path d={path} fill="none" stroke={stroke} strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={x(pts.length - 1)} cy={y(lastVal)} r="3" fill={stroke} />
      </svg>
    </div>
  );
}

function RawSensorsSection({ componentId, machineId }) {
  const [open, setOpen] = useStateMd(false);
  const [hist, setHist] = useStateMd({});
  // We only have rich daily history mocked for Al Nakheel's Yankee bearings.
  // For every other case, hide the section entirely — better than empty charts.
  const sensorTypes = useMemo(() => {
    if (machineId !== "al-nakheel" || componentId !== "yankee") return [];
    return [
      "yankee_surface_temp",
      "yankee_steam_pressure",
      "yankee_vibration_bearing_1",
      "yankee_vibration_bearing_2",
      "yankee_vibration_bearing_3",
      "yankee_blade_pressure",
    ];
  }, [componentId, machineId]);

  useEffectMd(() => {
    if (!open) return;
    sensorTypes.forEach((s) => {
      if (hist[s]) return;
      window.api
        .get(`/machines/${machineId}/sensors/${s}/history`, { window: "30d", aggregation: "daily" })
        .then((r) => setHist((prev) => ({ ...prev, [s]: r })));
    });
  }, [open, sensorTypes, machineId]);

  if (sensorTypes.length === 0) return null;

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        style={{
          background: "transparent", border: "none", padding: "6px 0",
          color: "#0A1F44", fontSize: 13, fontWeight: 600, cursor: "pointer",
          fontFamily: "inherit", display: "inline-flex", alignItems: "center", gap: 6,
        }}
      >
        <span style={{
          display: "inline-block", transition: "transform .2s ease",
          transform: open ? "rotate(90deg)" : "rotate(0deg)",
        }}>▸</span>
        {open ? "Hide raw sensor signals" : "View raw sensor signals →"}
        <span style={{ fontSize: 11, color: "#9CA3AF", fontWeight: 500 }}>
          (engineer view)
        </span>
      </button>

      {open && (
        <div style={{
          marginTop: 12,
          display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10,
        }}>
          {sensorTypes.map((s) => (
            <SensorMiniChart key={s} sensorType={s} history={hist[s]}
              highlight={s === "yankee_vibration_bearing_3"} />
          ))}
        </div>
      )}
    </div>
  );
}

// ───────────────────────── Bottom panels ─────────────────────────
const SEVERITY_META = {
  info:     { fg: "#1F4FB1", bg: "#E5EDFB", dot: "#3D6FD9", label: "Info" },
  warning:  { fg: "#B14A00", bg: "#FFEDDD", dot: "#E66A12", label: "Warning" },
  critical: { fg: "#B31E2B", bg: "#FCE3E5", dot: "#D7263D", label: "Critical" },
};

function SeverityPill({ severity }) {
  const m = SEVERITY_META[severity] || SEVERITY_META.info;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      padding: "3px 9px", borderRadius: 999,
      background: m.bg, color: m.fg, fontSize: 11, fontWeight: 600,
      letterSpacing: 0.3, textTransform: "uppercase",
    }}>
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: m.dot }} />
      {m.label}
    </span>
  );
}

function RecentAlarmsPanel({ alarms }) {
  if (!alarms) return <PanelShell />;
  if (alarms.length === 0) {
    return (
      <div style={panelShell}>
        <div style={panelHeader}>Recent Alarms (0)</div>
        <div style={{ marginTop: 12, padding: "24px 0", textAlign: "center",
          color: "#6B7280", fontSize: 13 }}>
          No recent alarms
        </div>
      </div>
    );
  }
  return (
    <div style={panelShell}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={panelHeader}>Recent Alarms ({alarms.length})</div>
        <button
          style={textBtn}
          onClick={() => window.dispatchEvent(new CustomEvent("fhh:chat:send",
            { detail: "Take me to the alerts page" }))}
          onMouseEnter={(e) => { e.currentTarget.style.color = "#1B3568"; e.currentTarget.style.textDecoration = "underline"; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = "#0A1F44"; e.currentTarget.style.textDecoration = "none"; }}
        >View all →</button>
      </div>
      <div style={{ marginTop: 10, display: "flex", flexDirection: "column" }}>
        {alarms.map((a, i) => (
          <div key={a.alarm_id} style={{
            display: "grid", gridTemplateColumns: "62px 90px 1fr",
            gap: 10, alignItems: "center",
            padding: "11px 0",
            borderTop: i === 0 ? "1px solid #EFF1F5" : "none",
            borderBottom: "1px solid #EFF1F5",
          }}>
            <div style={{ fontSize: 12, color: "#6B7280", fontVariantNumeric: "tabular-nums" }}>
              {formatRelative(a.timestamp)}
            </div>
            <SeverityPill severity={a.severity} />
            <div style={{
              fontSize: 12.5, color: "#1A2438", lineHeight: 1.4,
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            }} title={a.description}>{a.description}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

const MAINT_TYPE_META = {
  preventive: { fg: "#0F8B5C", bg: "#E6F6EE", label: "Preventive" },
  predictive: { fg: "#1F4FB1", bg: "#E5EDFB", label: "Predictive" },
  corrective: { fg: "#B14A00", bg: "#FFEDDD", label: "Corrective" },
  emergency:  { fg: "#B31E2B", bg: "#FCE3E5", label: "Emergency" },
};
function MaintTypePill({ type }) {
  const m = MAINT_TYPE_META[type] || MAINT_TYPE_META.preventive;
  return (
    <span style={{
      display: "inline-flex", padding: "2px 8px", borderRadius: 4,
      background: m.bg, color: m.fg, fontSize: 10.5, fontWeight: 600,
      letterSpacing: 0.3, textTransform: "uppercase",
    }}>{m.label}</span>
  );
}

function MaintenanceHistoryPanel({ logs }) {
  if (!logs) return <PanelShell />;
  return (
    <div style={panelShell}>
      <div style={panelHeader}>Maintenance History</div>
      <div style={{ marginTop: 12, position: "relative" }}>
        {/* timeline rail */}
        <div style={{ position: "absolute", left: 7, top: 8, bottom: 8, width: 2, background: "#EFF1F5" }} />
        {logs.map((l, i) => (
          <div key={l.log_id} style={{
            position: "relative",
            paddingLeft: 28, paddingBottom: i === logs.length - 1 ? 0 : 14,
          }}>
            <div style={{
              position: "absolute", left: 2, top: 4,
              width: 12, height: 12, borderRadius: "50%",
              background: "white", border: `2px solid ${MAINT_TYPE_META[l.maintenance_type]?.fg || "#15A56C"}`,
            }} />
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <div style={{ fontSize: 12, color: "#6B7280", fontVariantNumeric: "tabular-nums" }}>
                  {l.date_performed}
                </div>
                <MaintTypePill type={l.maintenance_type} />
              </div>
              <div style={{ fontSize: 12, color: "#0A1F44", fontWeight: 600,
                fontVariantNumeric: "tabular-nums" }}>
                {formatUsdCompact(l.cost_usd)}
              </div>
            </div>
            <div style={{ fontSize: 13, color: "#0A1F44", fontWeight: 500, marginTop: 3 }}>
              {COMPONENT_LABEL[l.component_id]}
            </div>
            <div style={{ fontSize: 11.5, color: "#6B7280", marginTop: 2 }}>
              {l.technician} · {l.downtime_hours}h downtime
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────── shared styles ───────────────────────────
const panelShell = {
  background: "white",
  border: "1px solid #E5E8EE",
  borderRadius: 10,
  padding: "16px 18px",
  boxShadow: "0 1px 2px rgba(10,31,68,0.04)",
};
const panelHeader = {
  fontSize: 11, fontWeight: 700, letterSpacing: 0.6,
  textTransform: "uppercase", color: "#6B7280",
};
const primaryBtn = {
  background: "#0A1F44", color: "white",
  border: "none", borderRadius: 8,
  padding: "9px 14px", fontSize: 13, fontWeight: 600,
  cursor: "pointer", fontFamily: "inherit",
  transition: "background .2s ease, transform .15s ease",
};
const secondaryBtn = {
  background: "white", color: "#0A1F44",
  border: "1px solid #0A1F44", borderRadius: 8,
  padding: "8px 14px", fontSize: 13, fontWeight: 600,
  cursor: "pointer", fontFamily: "inherit",
};
const textBtn = {
  background: "transparent", color: "#0A1F44",
  border: "none", padding: 0, fontSize: 12, fontWeight: 600,
  cursor: "pointer", fontFamily: "inherit",
};

function PanelShell() {
  return <div style={{ ...panelShell, height: 200, background: "#F4F6FA" }} />;
}

// ────────────────────────────── Screen ──────────────────────────────
function MachineDetailScreen({ machineId, onBack, onSelectComponent }) {
  const [machine, setMachine] = useStateMd(null);
  const [risk, setRisk] = useStateMd(null);
  const [components, setComponents] = useStateMd(null);
  const [predictions, setPredictions] = useStateMd(null);
  const [alarms, setAlarms] = useStateMd(null);
  const [maintLog, setMaintLog] = useStateMd(null);
  const [selectedComp, setSelectedComp] = useStateMd(null);
  const [compRisk, setCompRisk] = useStateMd(null);

  // Reload everything when machine changes — reset selection so the new
  // machine's highest-risk component takes the spotlight.
  useEffectMd(() => {
    setMachine(null); setRisk(null); setComponents(null);
    setPredictions(null); setAlarms(null); setMaintLog(null);
    setSelectedComp(null); setCompRisk(null);
    window.api.get(`/machines/${machineId}`).then(setMachine);
    window.api.get(`/machines/${machineId}/risk-score`).then((r) => {
      setRisk(r);
      // default-select the highest-risk component for this machine
      if (r?.highest_risk_component_id) setSelectedComp(r.highest_risk_component_id);
    });
    window.api.get(`/machines/${machineId}/components`).then((r) => setComponents(r.components));
    window.api.get(`/machines/${machineId}/predictions`).then(setPredictions);
    window.api.get(`/machines/${machineId}/alarms`, { limit: 5 }).then((r) => setAlarms(r.alarms));
    window.api.get(`/machines/${machineId}/maintenance-log`).then((r) => setMaintLog(r.logs));
  }, [machineId]);

  useEffectMd(() => {
    if (!selectedComp) return;
    setCompRisk(null);
    window.api
      .get(`/machines/${machineId}/components/${selectedComp}/risk-score`)
      .then(setCompRisk);
    onSelectComponent && onSelectComponent(selectedComp);
  }, [selectedComp, machineId]);

  const topPrediction = predictions?.predictions
    ?.slice()
    .sort((a, b) => b.failure_probability - a.failure_probability)[0];

  const selectedComponent = components?.find((c) => c.component_id === selectedComp);

  return (
    <div style={{ padding: "20px 28px 40px", display: "flex", flexDirection: "column", gap: 16 }}>
      {/* breadcrumb */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, color: "#6B7280" }}>
        <button onClick={onBack} style={{
          background: "transparent", border: "none", color: "#0A1F44",
          fontSize: 12.5, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
          padding: 0, display: "inline-flex", alignItems: "center", gap: 4,
        }}>← Overview</button>
        <span style={{ color: "#9CA3AF" }}>/</span>
        <span style={{ color: "#0A1F44", fontWeight: 600 }}>
          {machine?.name || machineId}
        </span>
      </div>

      {/* header */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16 }}>
        <div>
          <div style={{
            fontSize: 11, color: "#6B7280", fontWeight: 600,
            letterSpacing: 0.6, textTransform: "uppercase",
          }}>{machineId}</div>
          <h1 style={{
            margin: "4px 0 0", fontSize: 30, fontWeight: 600,
            color: "#0A1F44", letterSpacing: -0.6, lineHeight: 1.1,
          }}>{machine?.name || ""}</h1>
          {machine && (
            <div style={{ fontSize: 13, color: "#6B7280", marginTop: 6 }}>
              {machine.location} · {machine.model}
            </div>
          )}
        </div>
        {machine && (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
            <TierPill tier={machine.risk_tier} />
            <StatusDot status={machine.status} />
          </div>
        )}
      </div>

      {/* top stats row — responsive: 3 cols when wide, then 1 + 2 split, then stacked */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
        gap: 14,
      }}>
        <div style={{ ...panelShell, display: "flex", alignItems: "center", justifyContent: "center",
          minHeight: 280 }}>
          {risk && <RiskGauge score={risk.score} tier={risk.tier}
            highestRiskComponentId={risk.highest_risk_component_id} />}
        </div>
        <PredictedFailurePanel
          machineId={machineId}
          topPrediction={topPrediction}
          hot={topPrediction && topPrediction.predicted_failure_window_hours != null}
        />
        <QuickStatsPanel
          machine={machine}
          highestRiskComp={components?.find(c => c.component_id === risk?.highest_risk_component_id)}
          alertsCount={machine?.active_alerts_count || 0}
        />
      </div>

      {/* component selector */}
      <div style={{ marginTop: 4 }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 10 }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: "#0A1F44", letterSpacing: -0.2 }}>
            Components
          </h2>
          <div style={{ fontSize: 12, color: "#6B7280" }}>
            Select to see diagnosis
          </div>
        </div>
        {components && (
          <ComponentRow components={components} selectedId={selectedComp} onSelect={setSelectedComp} />
        )}
      </div>

      {/* component detail panel */}
      {compRisk && selectedComponent && (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          gap: 14,
          alignItems: "start",
        }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 0 }}>
            <WhatsWrongCard component={selectedComponent} risk={compRisk} />
            <RecommendedActionCard component={selectedComponent} risk={compRisk} />
            <RawSensorsSection componentId={selectedComp} machineId={machineId} />
          </div>
          <ContributingSensorsCard sensors={compRisk.top_contributing_sensors} />
        </div>
      )}

      {/* bottom row */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
        gap: 14, marginTop: 4,
      }}>
        <RecentAlarmsPanel alarms={alarms} />
        <MaintenanceHistoryPanel logs={maintLog} />
      </div>
    </div>
  );
}

Object.assign(window, { MachineDetailScreen });
