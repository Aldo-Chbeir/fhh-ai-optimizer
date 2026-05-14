// Overview screen: KPI strip + critical banner + 4-machine grid.
// Every component pulls from a /kpis/overview, /alerts, or /machines call —
// data wiring is shown in the console. Fields used (verbatim from contract):
//   /kpis/overview → fleet_avg_oee_percent, active_critical_alerts,
//                    active_warning_alerts, machines_running,
//                    machines_total, last_updated
//   /alerts (severity=critical) → alerts[].title, machine_id, component_id,
//                    risk_score, predicted_failure_window_hours
//   /machines → machines[].machine_id, name, location, status,
//                    current_speed_mpm, risk_score, risk_tier, active_alerts_count

const { useEffect, useState } = React;

function KpiTile({ label, value, sub, accent }) {
  return (
    <div style={{
      background: "#FFFFFF",
      border: "1px solid #E5E8EE",
      borderRadius: 10,
      padding: "16px 18px",
      minHeight: 130,                    // grows if content needs more room
      display: "flex", flexDirection: "column",
      gap: 8,
      boxShadow: "0 1px 2px rgba(10,31,68,0.04)",
      minWidth: 0,
    }}>
      {/* label — wraps to a second line if needed, never clipped */}
      <div style={{
        fontSize: 11, fontWeight: 600, letterSpacing: 0.6,
        textTransform: "uppercase", color: "#6B7280",
        lineHeight: 1.3,
      }}>{label}</div>

      {/* hero number — identical metrics across all 4 tiles */}
      <div style={{
        flex: 1,
        display: "flex", alignItems: "center",
      }}>
        <div style={{
          fontSize: 26, fontWeight: 600, lineHeight: 1,
          color: accent || "#0A1F44",
          fontVariantNumeric: "tabular-nums",
          letterSpacing: -0.4,
          whiteSpace: "nowrap",
        }}>{value}</div>
      </div>

      {/* sub-text — wraps to a second line if needed, never clipped */}
      <div style={{
        fontSize: 12, color: "#6B7280", lineHeight: 1.35,
        textWrap: "balance",
      }}>{sub || "\u00A0"}</div>
    </div>
  );
}

function KpiStrip({ kpis }) {
  if (!kpis) return <div style={{ height: 132 }} />;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 12 }}>
      <KpiTile
        label="Fleet Avg OEE"
        value={kpis.fleet_avg_oee_percent.toFixed(1) + "%"}
        sub={`Across ${kpis.machines_total} machines`}
      />
      <KpiTile
        label="Critical Machines"
        value={kpis.active_critical_alerts}
        accent={kpis.active_critical_alerts > 0 ? "#D7263D" : "#0A1F44"}
        sub="ML risk ≥ 70 — action needed now"
      />
      <KpiTile
        label="Warning Machines"
        value={kpis.active_warning_alerts}
        accent={kpis.active_warning_alerts > 0 ? "#E66A12" : "#0A1F44"}
        sub="ML risk 50–69 — schedule within 7 days"
      />
    </div>
  );
}

function CriticalBanner({ alerts, machines, onOpenMachine }) {
  if (!alerts || alerts.length === 0) return null;
  const a = alerts[0]; // surface the top one in the banner
  const machine = machines?.find((m) => m.machine_id === a.machine_id);
  const machineName = machine?.name || a.machine_id;
  // Translate component_id (e.g. "yankee") into a readable label.
  const compMap = {
    headbox: "Headbox",
    visconip: "ViscoNip Press",
    yankee: "Yankee Cylinder",
    aircap: "AirCap Hood",
    softreel: "SoftReel Reel",
    rewinder: "Rewinder",
  };
  const componentName = compMap[a.component_id] || a.component_id;
  const failProb = a.risk_score; // contract: risk_score is 0-100

  return (
    <button
      onClick={() => onOpenMachine && onOpenMachine(a.machine_id)}
      style={{
        width: "100%",
        textAlign: "left",
        background: "linear-gradient(180deg, #FCE3E5 0%, #F9D5D8 100%)",
        border: "1px solid #F0B5BB",
        borderLeft: "4px solid #D7263D",
        borderRadius: 10,
        padding: "14px 18px",
        display: "flex", alignItems: "center", gap: 14,
        cursor: "pointer",
        fontFamily: "inherit",
      }}
    >
      <div style={{
        width: 32, height: 32, borderRadius: 8,
        background: "#D7263D", color: "white",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 18, fontWeight: 700, flexShrink: 0,
      }}>!</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 11, fontWeight: 700, color: "#B31E2B",
          letterSpacing: 0.6, textTransform: "uppercase",
        }}>Critical · Action needed in {a.predicted_failure_window_hours}h</div>
        <div style={{ fontSize: 14, color: "#3A1217", marginTop: 2, fontWeight: 500 }}>
          {a.title} on <b>{machineName}</b> ({componentName}) — failure probability {failProb}%
        </div>
      </div>
      <div style={{
        fontSize: 12, color: "#B31E2B", fontWeight: 600,
        display: "flex", alignItems: "center", gap: 4, flexShrink: 0,
      }}>View machine →</div>
    </button>
  );
}

function MachineCard({ m, onClick }) {
  const tier = TIER_META[m.risk_tier] || TIER_META.healthy;
  return (
    <button
      onClick={() => onClick && onClick(m.machine_id)}
      style={{
        textAlign: "left",
        background: "white",
        border: "1px solid #E5E8EE",
        borderRadius: 10,
        padding: "20px 22px",
        cursor: "pointer",
        display: "flex", flexDirection: "column", gap: 16,
        fontFamily: "inherit",
        boxShadow: "0 1px 2px rgba(10,31,68,0.04)",
        transition: "transform .15s ease, box-shadow .15s ease, border-color .15s ease",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = "translateY(-1px)";
        e.currentTarget.style.boxShadow = "0 4px 14px rgba(10,31,68,0.08)";
        e.currentTarget.style.borderColor = "#CBD2DC";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = "none";
        e.currentTarget.style.boxShadow = "0 1px 2px rgba(10,31,68,0.04)";
        e.currentTarget.style.borderColor = "#E5E8EE";
      }}
    >
      {/* header */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{
            fontSize: 11, color: "#6B7280", fontWeight: 600,
            letterSpacing: 0.5, textTransform: "uppercase", marginBottom: 4,
          }}>{m.machine_id}</div>
          <div style={{
            fontSize: 22, fontWeight: 600, color: "#0A1F44",
            letterSpacing: -0.4, lineHeight: 1.1,
          }}>{m.name}</div>
          <div style={{ fontSize: 13, color: "#6B7280", marginTop: 4 }}>{m.location}</div>
        </div>
        <TierPill tier={m.risk_tier} />
      </div>

      {/* metric row */}
      <div style={{
        display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16,
        paddingTop: 14, borderTop: "1px solid #EFF1F5",
      }}>
        <div>
          <div style={{
            fontSize: 10, color: "#6B7280", fontWeight: 600,
            letterSpacing: 0.5, textTransform: "uppercase",
          }}>Risk score</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginTop: 2 }}>
            <div style={{
              fontSize: 28, fontWeight: 600, color: tier.fg,
              fontVariantNumeric: "tabular-nums", letterSpacing: -0.5,
            }}>{m.risk_score}</div>
            <div style={{ fontSize: 13, color: "#9CA3AF" }}>/ 100</div>
          </div>
          {/* tier bar */}
          <div style={{ marginTop: 8, height: 4, borderRadius: 2, background: "#EFF1F5", overflow: "hidden" }}>
            <div style={{
              width: `${m.risk_score}%`, height: "100%", background: tier.dot,
              transition: "width .4s ease",
            }} />
          </div>
        </div>
        <div>
          <div style={{
            fontSize: 10, color: "#6B7280", fontWeight: 600,
            letterSpacing: 0.5, textTransform: "uppercase",
          }}>Speed</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginTop: 2 }}>
            <div style={{
              fontSize: 28, fontWeight: 600, color: "#0A1F44",
              fontVariantNumeric: "tabular-nums", letterSpacing: -0.5,
            }}>{m.current_speed_mpm.toLocaleString()}</div>
            <div style={{ fontSize: 13, color: "#9CA3AF" }}>m/min</div>
          </div>
          <div style={{ marginTop: 8 }}>
            <StatusDot status={m.status} />
          </div>
        </div>
      </div>

      {/* footer */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        paddingTop: 12, borderTop: "1px solid #EFF1F5",
      }}>
        {m.active_alerts_count > 0 ? (
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 6,
            padding: "4px 10px", borderRadius: 999,
            background: "#FFEDDD", color: "#B14A00",
            fontSize: 12, fontWeight: 600,
          }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#E66A12" }} />
            {m.active_alerts_count} active alert{m.active_alerts_count > 1 ? "s" : ""}
          </div>
        ) : (
          <div style={{ fontSize: 12, color: "#6B7280" }}>No active alerts</div>
        )}
        <div style={{ fontSize: 12, color: "#6B7280", fontWeight: 500 }}>
          OEE {m.current_oee_percent.toFixed(1)}%
        </div>
      </div>
    </button>
  );
}

function OverviewScreen({ onOpenMachine }) {
  const [kpis, setKpis] = useState(null);
  const [machines, setMachines] = useState(null);
  const [criticalAlerts, setCriticalAlerts] = useState(null);

  useEffect(() => {
    window.api.get("/kpis/overview").then(setKpis);
    window.api.get("/machines").then((r) => setMachines(r.machines));
    window.api
      .get("/alerts", { severity: "critical", limit: 3 })
      .then((r) => setCriticalAlerts(r.alerts));
  }, []);

  return (
    <div style={{ padding: "28px 32px 40px", display: "flex", flexDirection: "column", gap: 20 }}>
      {/* page heading */}
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between" }}>
        <div>
          <div style={{
            fontSize: 11, color: "#6B7280", fontWeight: 600,
            letterSpacing: 0.6, textTransform: "uppercase",
          }}>Fleet overview</div>
          <h1 style={{
            margin: "4px 0 0", fontSize: 26, fontWeight: 600,
            color: "#0A1F44", letterSpacing: -0.6,
          }}>Operations Dashboard</h1>
        </div>
        <div style={{ fontSize: 12, color: "#6B7280" }}>
          {kpis ? `Last sync ${formatRelative(kpis.last_updated)}` : "Loading…"}
        </div>
      </div>

      <KpiStrip kpis={kpis} />

      {kpis && kpis.active_critical_alerts > 0 && (
        <CriticalBanner
          alerts={criticalAlerts}
          machines={machines}
          onOpenMachine={onOpenMachine}
        />
      )}

      {/* Machines section */}
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginTop: 6 }}>
        <div>
          <h2 style={{
            margin: 0, fontSize: 16, fontWeight: 600, color: "#0A1F44",
            letterSpacing: -0.2,
          }}>Machines</h2>
          <div style={{ fontSize: 12, color: "#6B7280", marginTop: 2 }}>
            Click a card to inspect components, sensors, and alarms
          </div>
        </div>
        <div style={{ fontSize: 12, color: "#6B7280" }}>
          {machines ? `${machines.length} total` : ""}
        </div>
      </div>

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(2, 1fr)",
        gap: 14,
      }}>
        {machines
          ? machines.map((m) => (
              <MachineCard key={m.machine_id} m={m} onClick={onOpenMachine} />
            ))
          : Array.from({ length: 4 }).map((_, i) => (
              <div key={i} style={{ height: 220, background: "#F4F6FA", border: "1px solid #E5E8EE", borderRadius: 10 }} />
            ))}
      </div>
    </div>
  );
}

Object.assign(window, { OverviewScreen });
