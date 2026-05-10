// Alerts screen — full-fleet triage inbox.
// Endpoints consumed (all from /alerts and /machines):
//   GET /alerts/kpis                          → KPI strip
//   GET /alerts?sort=...                      → main list
//   GET /machines                             → machine name lookup for filter chip
// Local-only state:
//   localStorage["fhh_alert_overrides"]       → user-applied status changes (ack/snooze/schedule/resolve)
//   localStorage["fhh_alert_notes"]           → free-form note per alert_id

const { useState: useStateAlerts, useEffect: useEffectAlerts, useMemo: useMemoAlerts, useRef: useRefAlerts } = React;

// ───────────── localStorage helpers ─────────────
// One-time migration: clear the legacy `fhh_alert_overrides` blob (alert
// state now persists in the database via PATCH /alerts/{id}/{action}).
// Keep this no-op around for a release or two so users with stale local
// data don't see ghost statuses.
try { localStorage.removeItem("fhh_alert_overrides"); } catch (_) {}

// ───────────── meta tables ─────────────
// Indexed by the LIVE 4-value `tier` field on each alert (computed from the
// current ML risk score, not the seeded alarm severity). `info` is kept
// here for backward-compat — it's still the legacy alarm severity that we
// surface in tooltips ("Originally fired as: info") and never as a tier.
const SEV_META = {
  critical: { label: "Critical", fg: "#B31E2B", bg: "#FCE3E5", dot: "#D7263D", border: "#F0B5BB" },
  warning:  { label: "Warning",  fg: "#B14A00", bg: "#FFEDDD", dot: "#E66A12", border: "#FFD4A8" },
  watch:    { label: "Watch",    fg: "#4B5563", bg: "#EEF1F6", dot: "#6B7280", border: "#D8DEE8" },
  healthy:  { label: "Healthy",  fg: "#0F8B5C", bg: "#E6F6EE", dot: "#15A56C", border: "#B7E2C7" },
  info:     { label: "Info",     fg: "#1F4FB1", bg: "#E5EDFB", dot: "#3D6FD9", border: "#C9D6F2" },
};
const STATUS_META = {
  active:       { label: "Active",       fg: "#B14A00", bg: "#FFEDDD", icon: "●" },
  acknowledged: { label: "Acknowledged", fg: "#1F4FB1", bg: "#E5EDFB", icon: "✓" },
  snoozed:      { label: "Snoozed",      fg: "#6B7280", bg: "#EEF1F6", icon: "⏰" },
  scheduled:    { label: "Scheduled",    fg: "#0F8B5C", bg: "#E6F6EE", icon: "📅" },
  resolved:     { label: "Resolved",     fg: "#0F8B5C", bg: "#E6F6EE", icon: "✓" },
};
const COMPONENT_LABEL_ALERTS = {
  headbox:  "Headbox",
  visconip: "ViscoNip Press",
  yankee:   "Yankee Cylinder",
  aircap:   "AirCap Hood",
  softreel: "SoftReel Reel",
  rewinder: "Rewinder",
};
const MACHINE_NAMES = {
  "al-nakheel": "Al Nakheel",
  "al-bardi":   "Al Bardi",
  "al-sindian": "Al Sindian",
  "al-snobar":  "Al Snobar",
};
const TECHNICIAN_LIST = [
  "M. Khalil", "L. Haddad", "S. Antar", "H. Naser", "M. Khalid",
];

// ───────────── KPI strip ─────────────
function Sparkline({ values, color, height = 28, width = 80 }) {
  if (!values || values.length === 0) return null;
  const max = Math.max(...values, 1);
  const stepX = width / (values.length - 1 || 1);
  const path = values.map((v, i) =>
    `${i === 0 ? "M" : "L"} ${(i * stepX).toFixed(1)} ${(height - (v / max) * (height - 4) - 2).toFixed(1)}`
  ).join(" ");
  const areaPath = path + ` L ${width} ${height} L 0 ${height} Z`;
  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      <path d={areaPath} fill={color} fillOpacity="0.15" />
      <path d={path} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      {values.map((v, i) => i === values.length - 1 && (
        <circle key={i} cx={i * stepX} cy={height - (v / max) * (height - 4) - 2} r="2.5" fill={color} />
      ))}
    </svg>
  );
}

function KpiCard({ label, value, accent, sub, sparkline, sparkColor, progress }) {
  return (
    <div style={{
      background: "white", border: "1px solid #E5E8EE", borderRadius: 10,
      padding: "16px 18px", minHeight: 116,
      display: "flex", flexDirection: "column", gap: 8,
      boxShadow: "0 1px 2px rgba(10,31,68,0.04)",
      minWidth: 0,
    }}>
      <div style={{
        fontSize: 11, fontWeight: 600, letterSpacing: 0.6,
        textTransform: "uppercase", color: "#6B7280",
      }}>{label}</div>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 12, flex: 1 }}>
        <div style={{
          fontSize: 28, fontWeight: 600, lineHeight: 1,
          color: accent || "#0A1F44",
          fontVariantNumeric: "tabular-nums", letterSpacing: -0.4,
          whiteSpace: "nowrap",
        }}>{value}</div>
        {sparkline && <Sparkline values={sparkline} color={sparkColor || "#0A1F44"} />}
      </div>
      {progress != null && (
        <div style={{ height: 4, background: "#EFF1F5", borderRadius: 2, overflow: "hidden" }}>
          <div style={{
            width: `${Math.min(100, progress)}%`, height: "100%",
            background: "#15A56C", transition: "width .4s ease",
          }} />
        </div>
      )}
      <div style={{ fontSize: 12, color: "#6B7280", lineHeight: 1.35 }}>{sub || "\u00A0"}</div>
    </div>
  );
}

function AlertsKpiStrip({ kpis }) {
  if (!kpis) {
    return (
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
        {[0,1,2,3].map((i) => <div key={i} style={{ height: 116, background: "#EEF1F6", borderRadius: 10 }} />)}
      </div>
    );
  }
  const ackPct = Math.round((kpis.acknowledged_today / kpis.acknowledged_today_total) * 100);
  const delta = kpis.avg_response_time_delta_minutes;
  const deltaTxt = delta === 0 ? "no change vs last week"
    : delta < 0 ? `${Math.abs(delta)} min faster vs last week`
                : `${delta} min slower vs last week`;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
      <KpiCard
        label="Critical Alerts"
        value={kpis.active_critical}
        accent={kpis.active_critical > 0 ? "#D7263D" : "#0A1F44"}
        sparkline={kpis.critical_sparkline_7d}
        sparkColor="#D7263D"
        sub="Active · last 7 days trend"
      />
      <KpiCard
        label="Warning Alerts"
        value={kpis.active_warning}
        accent={kpis.active_warning > 0 ? "#E66A12" : "#0A1F44"}
        sparkline={kpis.warning_sparkline_7d}
        sparkColor="#E66A12"
        sub="Active · last 7 days trend"
      />
      <KpiCard
        label="Avg Response Time"
        value={`${kpis.avg_response_time_minutes} min`}
        accent="#0A1F44"
        sub={deltaTxt}
      />
      <KpiCard
        label="Acknowledged Today"
        value={`${kpis.acknowledged_today} / ${kpis.acknowledged_today_total}`}
        accent="#0F8B5C"
        progress={ackPct}
        sub={`${ackPct}% of today's alerts handled`}
      />
    </div>
  );
}

// ───────────── filter chip dropdown ─────────────
function FilterChip({ label, options, selected, onChange }) {
  const [open, setOpen] = useStateAlerts(false);
  const ref = useRefAlerts(null);
  useEffectAlerts(() => {
    function close(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }
    if (open) document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  const count = selected.length;
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          display: "inline-flex", alignItems: "center", gap: 6,
          padding: "7px 12px", borderRadius: 999,
          border: count > 0 ? "1px solid #0A1F44" : "1px solid #DCE2EC",
          background: count > 0 ? "#EAEFF8" : "white",
          color: "#0A1F44",
          fontSize: 12.5, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
          transition: "background .15s, border-color .15s",
        }}
      >
        {label}
        {count > 0 && (
          <span style={{
            background: "#0A1F44", color: "white", fontSize: 10.5, fontWeight: 700,
            padding: "1px 6px", borderRadius: 999, minWidth: 16, textAlign: "center",
          }}>{count}</span>
        )}
        <span style={{ fontSize: 9, opacity: 0.7, transform: open ? "rotate(180deg)" : "none", transition: "transform .15s" }}>▼</span>
      </button>
      {open && (
        <div style={{
          position: "absolute", top: "calc(100% + 6px)", left: 0, zIndex: 30,
          minWidth: 200, background: "white",
          border: "1px solid #DCE2EC", borderRadius: 8,
          boxShadow: "0 8px 24px rgba(10,31,68,0.12)",
          padding: 6,
        }}>
          {options.map((opt) => {
            const isOn = selected.includes(opt.id);
            return (
              <button
                key={opt.id}
                onClick={() => {
                  const next = isOn ? selected.filter((s) => s !== opt.id) : [...selected, opt.id];
                  onChange(next);
                }}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  width: "100%", textAlign: "left",
                  padding: "8px 10px", borderRadius: 6,
                  background: isOn ? "#EAEFF8" : "transparent",
                  border: "none", cursor: "pointer", fontFamily: "inherit",
                  fontSize: 13, color: "#0A1F44", fontWeight: 500,
                }}
                onMouseEnter={(e) => { if (!isOn) e.currentTarget.style.background = "#F4F7FC"; }}
                onMouseLeave={(e) => { if (!isOn) e.currentTarget.style.background = "transparent"; }}
              >
                <span style={{
                  width: 16, height: 16, borderRadius: 4,
                  border: "1.5px solid #B0B8C8",
                  background: isOn ? "#0A1F44" : "white",
                  borderColor: isOn ? "#0A1F44" : "#B0B8C8",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  flexShrink: 0,
                }}>
                  {isOn && <svg width="10" height="10" viewBox="0 0 16 16" fill="none">
                    <path d="M3 8 L7 12 L13 4" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>}
                </span>
                {opt.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function SortMenu({ value, onChange }) {
  const [open, setOpen] = useStateAlerts(false);
  const ref = useRefAlerts(null);
  useEffectAlerts(() => {
    function close(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }
    if (open) document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  const opts = [
    { id: "created_at_desc", label: "Newest first" },
    { id: "created_at_asc",  label: "Oldest first" },
    { id: "severity",        label: "Severity (high → low)" },
    { id: "machine",         label: "Machine name" },
  ];
  const current = opts.find((o) => o.id === value) || opts[0];
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          display: "inline-flex", alignItems: "center", gap: 6,
          padding: "7px 12px", borderRadius: 8,
          border: "1px solid #DCE2EC", background: "white", color: "#0A1F44",
          fontSize: 12.5, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
        }}
      >
        Sort: {current.label}
        <span style={{ fontSize: 9, opacity: 0.7, transform: open ? "rotate(180deg)" : "none", transition: "transform .15s" }}>▼</span>
      </button>
      {open && (
        <div style={{
          position: "absolute", top: "calc(100% + 6px)", right: 0, zIndex: 30,
          minWidth: 220, background: "white", border: "1px solid #DCE2EC", borderRadius: 8,
          boxShadow: "0 8px 24px rgba(10,31,68,0.12)", padding: 6,
        }}>
          {opts.map((o) => (
            <button key={o.id}
              onClick={() => { onChange(o.id); setOpen(false); }}
              style={{
                display: "block", width: "100%", textAlign: "left",
                padding: "8px 10px", borderRadius: 6,
                background: value === o.id ? "#EAEFF8" : "transparent",
                border: "none", cursor: "pointer", fontFamily: "inherit",
                fontSize: 13, color: "#0A1F44", fontWeight: 500,
              }}
              onMouseEnter={(e) => { if (value !== o.id) e.currentTarget.style.background = "#F4F7FC"; }}
              onMouseLeave={(e) => { if (value !== o.id) e.currentTarget.style.background = "transparent"; }}
            >{o.label}</button>
          ))}
        </div>
      )}
    </div>
  );
}

// ───────────── tab switcher ─────────────
function StatusTabs({ active, onChange, counts }) {
  const tabs = [
    { id: "active",       label: "Active" },
    { id: "acknowledged", label: "Acknowledged" },
    { id: "snoozed",      label: "Snoozed" },
    { id: "scheduled",    label: "Scheduled" },
    { id: "resolved",     label: "Resolved" },
    { id: "all",          label: "All" },
  ];
  return (
    <div role="tablist" style={{
      display: "inline-flex",
      background: "#EEF1F6", borderRadius: 10, padding: 4, gap: 2,
    }}>
      {tabs.map((t) => {
        const on = active === t.id;
        return (
          <button key={t.id}
            role="tab" aria-selected={on}
            onClick={() => onChange(t.id)}
            style={{
              padding: "7px 14px", borderRadius: 7,
              background: on ? "white" : "transparent",
              color: "#0A1F44",
              fontSize: 12.5, fontWeight: 600,
              border: "none", cursor: "pointer", fontFamily: "inherit",
              boxShadow: on ? "0 1px 3px rgba(10,31,68,0.08)" : "none",
              transition: "background .15s",
              display: "inline-flex", alignItems: "center", gap: 6,
            }}
          >
            {t.label}
            <span style={{
              fontSize: 11, fontWeight: 600,
              background: on ? "#EAEFF8" : "rgba(255,255,255,0.7)",
              padding: "1px 7px", borderRadius: 999,
              color: "#4B5563",
              minWidth: 18, textAlign: "center",
            }}>{counts[t.id] || 0}</span>
          </button>
        );
      })}
    </div>
  );
}

// ───────────── alert card ─────────────
function TrendArrow({ trend }) {
  if (trend === "rising")  return <span style={{ color: "#D7263D", fontSize: 14 }} aria-label="rising">↗</span>;
  if (trend === "falling") return <span style={{ color: "#0F8B5C", fontSize: 14 }} aria-label="falling">↘</span>;
  return <span style={{ color: "#9CA3AF", fontSize: 14 }} aria-label="stable">→</span>;
}

function StatusPill({ status, alert }) {
  const m = STATUS_META[status] || STATUS_META.active;
  let label = m.label;
  if (status === "scheduled" && alert?.status_metadata?.scheduled_date) label = `Scheduled · ${alert.status_metadata.scheduled_date}`;
  if (status === "snoozed"   && alert?.status_metadata?.snooze_until)   label = `Snoozed · ${formatRelativeFuture(alert.status_metadata.snooze_until)}`;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      padding: "3px 9px", borderRadius: 999,
      background: m.bg, color: m.fg,
      fontSize: 11, fontWeight: 600, letterSpacing: 0.3, textTransform: "uppercase",
      whiteSpace: "nowrap",
    }}>
      <span aria-hidden="true">{m.icon}</span>
      {label}
    </span>
  );
}

function formatRelativeFuture(iso) {
  if (!iso) return "";
  const diff = (new Date(iso).getTime() - Date.now()) / 1000;
  if (diff <= 0) return "now";
  if (diff < 3600) return `${Math.round(diff / 60)}m`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h`;
  return `${Math.round(diff / 86400)}d`;
}

function Pill({ children, color = "#4B5563" }) {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center",
      padding: "3px 8px", borderRadius: 6,
      background: "#F4F6FA", color, fontSize: 11.5, fontWeight: 500,
      border: "1px solid #E5E8EE",
    }}>{children}</span>
  );
}

function OverflowMenu({ alert, onAct }) {
  const [open, setOpen] = useStateAlerts(false);
  const ref = useRefAlerts(null);
  useEffectAlerts(() => {
    function close(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }
    if (open) document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  const items = [
    alert._status === "active" && { id: "snooze",   label: "Snooze 24h" },
    alert._status !== "resolved" && { id: "resolve", label: "Mark resolved" },
    { id: "note",     label: "Add note" },
  ].filter(Boolean);
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        aria-label="More actions"
        onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
        style={{
          width: 28, height: 28, borderRadius: 6,
          border: "1px solid #DCE2EC", background: "white", color: "#0A1F44",
          cursor: "pointer", fontFamily: "inherit", fontSize: 14,
          display: "flex", alignItems: "center", justifyContent: "center",
        }}
        onMouseEnter={(e) => { e.currentTarget.style.background = "#F4F7FC"; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = "white"; }}
      >⋯</button>
      {open && (
        <div style={{
          position: "absolute", top: "calc(100% + 6px)", right: 0, zIndex: 30,
          minWidth: 170, background: "white", border: "1px solid #DCE2EC", borderRadius: 8,
          boxShadow: "0 8px 24px rgba(10,31,68,0.12)", padding: 6,
        }}>
          {items.map((it) => (
            <button key={it.id}
              onClick={(e) => { e.stopPropagation(); setOpen(false); onAct(it.id); }}
              style={{
                display: "block", width: "100%", textAlign: "left",
                padding: "8px 10px", borderRadius: 6,
                background: "transparent", border: "none", cursor: "pointer",
                fontFamily: "inherit", fontSize: 13, color: "#0A1F44", fontWeight: 500,
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "#F4F7FC"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
            >{it.label}</button>
          ))}
        </div>
      )}
    </div>
  );
}

function AlertCard({ alert, onOpenMachine, onAck, onSchedule, onSnooze, onResolve, onAddNote, bulkMode, checked, onToggleCheck, isExpanded, onToggleExpand }) {
  // Badge reflects the LIVE risk-score tier, not the seeded alarm severity.
  // Fall back to severity for older payloads / mock data that don't carry
  // tier yet (e.g. the optimistic-update path) so nothing renders blank.
  const liveTier = alert.tier || alert.severity || "healthy";
  const sevMeta = SEV_META[liveTier] || SEV_META.healthy;
  // When the live tier disagrees with how the alarm originally fired, the
  // tooltip surfaces the original severity so the operator isn't confused
  // by "Speed setpoint reached" being tagged CRITICAL — the description
  // is from the historical alarm, the tier is the model's current view.
  const originalSev = alert.original_severity || alert.severity;
  const tierMismatch = originalSev && originalSev !== liveTier;
  const badgeTitle = tierMismatch
    ? `Originally fired as: ${originalSev}`
    : undefined;
  // _status is set by optimistic mutations; status comes from the server.
  // Backend-loaded alerts only have `status` (the Pydantic model strips
  // `_status`), so we need both fallbacks or every server-loaded alert
  // renders as "active" regardless of its real triage state.
  const status = alert._status || alert.status || "active";
  const dim = status === "acknowledged" || status === "resolved" || status === "snoozed";
  const isHot = liveTier === "critical" || liveTier === "warning";
  // ML-only detection: tier is critical/warning but every underlying alarm
  // event in the bucket fired as plain `info` (status messages, recoveries).
  // The model sees risk that the DCS alarm log doesn't reflect — the
  // headline should say so, with the original description preserved as a
  // smaller subline + still in the expanded panel for audit.
  const mlOnlyDetection = (
    (liveTier === "critical" || liveTier === "warning") &&
    Array.isArray(alert.underlying_events) &&
    alert.underlying_events.length > 0 &&
    alert.underlying_events.every((u) => u.severity === "info")
  );
  const headlineTitle = mlOnlyDetection
    ? "ML detected risk — no DCS alarm fired"
    : alert.title;
  return (
    <div
      onClick={(e) => {
        if (bulkMode) { e.stopPropagation(); onToggleCheck(); return; }
        // ignore clicks bubbling from buttons / menus
        if (e.target.closest("button, a")) return;
        onOpenMachine(alert.machine_id);
      }}
      style={{
        background: "white",
        border: "1px solid #E5E8EE",
        borderLeft: liveTier === "critical" ? `4px solid ${sevMeta.dot}`
                  : `1px solid #E5E8EE`,
        borderRadius: 10,
        padding: "16px 18px",
        boxShadow: "0 1px 2px rgba(10,31,68,0.04)",
        opacity: dim ? 0.72 : 1,
        cursor: "pointer",
        display: "grid",
        gridTemplateColumns: bulkMode ? "32px 88px 1fr 200px" : "88px 1fr 200px",
        gap: 16, alignItems: "stretch",
        transition: "transform .15s ease, box-shadow .15s ease, opacity .2s ease",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.boxShadow = "0 4px 14px rgba(10,31,68,0.08)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.boxShadow = "0 1px 2px rgba(10,31,68,0.04)"; }}
    >
      {/* bulk checkbox */}
      {bulkMode && (
        <div style={{ display: "flex", alignItems: "center" }}>
          <span
            onClick={(e) => { e.stopPropagation(); onToggleCheck(); }}
            style={{
              width: 18, height: 18, borderRadius: 4,
              border: "1.5px solid #B0B8C8",
              background: checked ? "#0A1F44" : "white",
              borderColor: checked ? "#0A1F44" : "#B0B8C8",
              display: "flex", alignItems: "center", justifyContent: "center",
              cursor: "pointer", flexShrink: 0,
            }}>
            {checked && <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
              <path d="M3 8 L7 12 L13 4" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>}
          </span>
        </div>
      )}

      {/* LEFT: severity + score + trend */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 6 }}>
        <span title={badgeTitle} style={{
          display: "inline-flex", alignItems: "center", gap: 5,
          padding: "3px 8px", borderRadius: 999,
          background: sevMeta.bg, color: sevMeta.fg,
          fontSize: 10.5, fontWeight: 700, letterSpacing: 0.3, textTransform: "uppercase",
          cursor: tierMismatch ? "help" : "default",
        }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: sevMeta.dot }} />
          {sevMeta.label}
        </span>
        <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
          <div style={{
            fontSize: 32, fontWeight: 600, color: sevMeta.fg, lineHeight: 1,
            fontVariantNumeric: "tabular-nums", letterSpacing: -0.6,
          }}>{alert.risk_score}</div>
          <TrendArrow trend={alert._trend} />
        </div>
        <div style={{ fontSize: 10.5, color: "#9CA3AF", textTransform: "uppercase", letterSpacing: 0.5 }}>
          / 100
        </div>
      </div>

      {/* MIDDLE: headline + sub + tags + impact */}
      <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "#0A1F44", lineHeight: 1.35,
          textWrap: "balance", display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ flex: 1, minWidth: 0 }}>
            {MACHINE_NAMES[alert.machine_id]} · {COMPONENT_LABEL_ALERTS[alert.component_id]} · {headlineTitle}
          </span>
          {alert.event_count > 1 && onToggleExpand && (
            <button
              onClick={(e) => { e.stopPropagation(); onToggleExpand(); }}
              title={isExpanded ? "Hide underlying events" : "Show underlying events"}
              style={{
                flexShrink: 0,
                padding: "2px 8px", borderRadius: 999,
                border: "1px solid #DCE2EC", background: "white",
                color: "#0A1F44", cursor: "pointer", fontFamily: "inherit",
                fontSize: 11, fontWeight: 700, lineHeight: 1.2,
              }}
            >
              {isExpanded ? "▾" : "▸"} {alert.event_count}
            </button>
          )}
        </div>
        {mlOnlyDetection ? (
          // Subline preserves the original DCS log line so the audit trail
          // is intact even though the headline is overridden. Smaller +
          // dimmed so it reads as supporting context, not the main signal.
          <div style={{ fontSize: 11.5, color: "#9CA3AF", lineHeight: 1.45, fontStyle: "italic" }}>
            DCS log: {alert.title}
          </div>
        ) : (
          <div style={{ fontSize: 12.5, color: "#6B7280", lineHeight: 1.45, textWrap: "pretty" }}>
            {alert.description}
          </div>
        )}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 2 }}>
          <Pill>{MACHINE_NAMES[alert.machine_id]}</Pill>
          <Pill>{COMPONENT_LABEL_ALERTS[alert.component_id]}</Pill>
          {alert.top_contributing_sensors?.[0] && (
            <Pill>{alert.top_contributing_sensors[0].sensor_type}</Pill>
          )}
          {alert.is_informational && (
            <Pill>Informational</Pill>
          )}
        </div>
        {alert.event_count > 1 && (
          <div style={{ fontSize: 11.5, color: "#6B7280", marginTop: 2 }}>
            First seen {formatRelative(alert.first_triggered_at || alert.created_at)}
            {" · "}
            Latest {formatRelative(alert.latest_triggered_at || alert.created_at)}
            {" · "}
            <span style={{ fontWeight: 600 }}>{alert.event_count} events</span>
          </div>
        )}
        {isExpanded && alert.underlying_events && alert.underlying_events.length > 0 && (
          <div style={{
            marginTop: 6, paddingTop: 8, borderTop: "1px dashed #DCE2EC",
            display: "flex", flexDirection: "column", gap: 4,
          }}>
            {alert.underlying_events.map((u) => (
              <div key={u.alarm_id} style={{
                display: "flex", gap: 10, alignItems: "baseline",
                fontSize: 11.5, color: "#4B5563",
              }}>
                <span style={{
                  flexShrink: 0,
                  width: 56,
                  fontSize: 9.5, fontWeight: 700,
                  letterSpacing: 0.4, textTransform: "uppercase",
                  color: SEV_META[u.severity]?.fg || "#6B7280",
                }}>{u.severity}</span>
                <span style={{
                  flexShrink: 0, color: "#9CA3AF",
                  fontVariantNumeric: "tabular-nums", fontSize: 11,
                }}>{formatRelative(u.timestamp)}</span>
                <span style={{
                  flex: 1, minWidth: 0,
                  fontStyle: u.is_informational ? "italic" : "normal",
                  color: u.is_informational ? "#9CA3AF" : "#374151",
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                }} title={u.description}>{u.description}</span>
              </div>
            ))}
          </div>
        )}
        {(alert.predicted_failure_window_hours || alert.estimated_cost_if_unaddressed_usd) && isHot && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 14, marginTop: 4 }}>
            {alert.predicted_failure_window_hours != null && (
              <div style={{ fontSize: 12, color: "#B14A00", fontWeight: 600 }}>
                ⏱ Predicted failure ~{alert.predicted_failure_window_hours}h
              </div>
            )}
            {liveTier === "critical" && alert.estimated_cost_if_unaddressed_usd != null && (
              <div style={{ fontSize: 12, color: "#B31E2B", fontWeight: 600 }}>
                💰 Est. impact if unaddressed: {formatUsdCompact(alert.estimated_cost_if_unaddressed_usd)}
              </div>
            )}
          </div>
        )}
        {(status === "acknowledged" || status === "scheduled") && alert.status_changed_by && (
          <div style={{ fontSize: 11.5, color: "#1F4FB1", marginTop: 2 }}>
            ✓ Acknowledged by {alert.status_changed_by} · {formatRelative(alert.status_changed_at)}
            {status === "scheduled" && alert.status_metadata?.scheduled_date && ` · 📅 Scheduled ${alert.status_metadata.scheduled_date}`}
          </div>
        )}
        {status === "resolved" && (
          <div style={{ fontSize: 11.5, color: "#0F8B5C", marginTop: 2, lineHeight: 1.45 }}>
            ✓ Resolved by {alert.status_changed_by} · {formatRelative(alert.status_changed_at)}
            {alert.status_metadata?.resolution_notes && (
              <div style={{ color: "#6B7280", fontWeight: 400, marginTop: 2 }}>
                {alert.status_metadata.resolution_notes}
              </div>
            )}
          </div>
        )}
      </div>

      {/* RIGHT: timestamp + status pill + actions */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8 }}>
        <div title={alert.latest_triggered_at || alert.created_at}
             style={{ fontSize: 11, color: "#9CA3AF", fontVariantNumeric: "tabular-nums" }}>
          {alert.event_count > 1 ? "Latest" : "Triggered"}{" "}
          {formatRelative(alert.latest_triggered_at || alert.created_at)}
        </div>
        <StatusPill status={status} alert={alert} />
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 6, width: "100%" }}>
          <button
            onClick={(e) => { e.stopPropagation(); onOpenMachine(alert.machine_id); }}
            style={{
              padding: "7px 12px", borderRadius: 7, border: "none",
              background: "#0A1F44", color: "white",
              fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
              transition: "background .15s",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "#1B3568"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "#0A1F44"; }}
          >View Machine</button>
          {status === "active" && (
            <button
              onClick={(e) => { e.stopPropagation(); onAck(); }}
              style={{
                padding: "7px 12px", borderRadius: 7,
                border: "1px solid #DCE2EC", background: "white", color: "#0A1F44",
                fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "#F4F7FC"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "white"; }}
            >Acknowledge</button>
          )}
          {(status === "active" || status === "acknowledged") && (
            <button
              onClick={(e) => { e.stopPropagation(); onSchedule(); }}
              style={{
                padding: "6px 12px", borderRadius: 7,
                border: "none", background: "transparent", color: "#0A1F44",
                fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
                textAlign: "right",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.textDecoration = "underline"; }}
              onMouseLeave={(e) => { e.currentTarget.style.textDecoration = "none"; }}
            >Schedule Maintenance →</button>
          )}
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 2 }}>
            <OverflowMenu alert={alert} onAct={(id) => {
              if (id === "snooze")  onSnooze();
              if (id === "resolve") onResolve();
              if (id === "note")    onAddNote();
            }} />
          </div>
        </div>
      </div>
    </div>
  );
}

// ───────────── schedule maintenance modal ─────────────
function ScheduleModal({ alert, onClose, onSubmit }) {
  const tomorrow = new Date(Date.now() + 24*60*60*1000).toISOString().slice(0, 10);
  const [date, setDate] = useStateAlerts(tomorrow);
  const [tech, setTech] = useStateAlerts(TECHNICIAN_LIST[0]);
  const [priority, setPriority] = useStateAlerts("normal");
  const [notes, setNotes] = useStateAlerts("");
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 100,
        background: "rgba(10,31,68,0.45)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 24,
      }}>
      <div onClick={(e) => e.stopPropagation()}
        style={{
          background: "white", borderRadius: 12, width: 480, maxWidth: "100%",
          padding: "22px 24px", boxShadow: "0 20px 60px rgba(10,31,68,0.25)",
          display: "flex", flexDirection: "column", gap: 14,
        }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.6, textTransform: "uppercase", color: "#6B7280" }}>
            Schedule Maintenance
          </div>
          <div style={{ fontSize: 18, fontWeight: 600, color: "#0A1F44", marginTop: 4, letterSpacing: -0.3 }}>
            {MACHINE_NAMES[alert.machine_id]} · {COMPONENT_LABEL_ALERTS[alert.component_id]}
          </div>
          <div style={{ fontSize: 12.5, color: "#6B7280", marginTop: 2 }}>{alert.title}</div>
        </div>

        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: "#4B5563" }}>Date</span>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
            style={modalInput} />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: "#4B5563" }}>Technician</span>
          <select value={tech} onChange={(e) => setTech(e.target.value)} style={modalInput}>
            {TECHNICIAN_LIST.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: "#4B5563", marginBottom: 6 }}>Priority</div>
          <div style={{ display: "flex", gap: 8 }}>
            {["low", "normal", "high", "emergency"].map((p) => (
              <button key={p}
                onClick={() => setPriority(p)}
                style={{
                  padding: "6px 12px", borderRadius: 6,
                  background: priority === p ? "#0A1F44" : "white",
                  color: priority === p ? "white" : "#0A1F44",
                  border: "1px solid " + (priority === p ? "#0A1F44" : "#DCE2EC"),
                  fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
                  textTransform: "capitalize",
                }}>{p}</button>
            ))}
          </div>
        </div>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: "#4B5563" }}>Notes (optional)</span>
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3}
            placeholder="Anything the technician should know..."
            style={{ ...modalInput, resize: "vertical", fontFamily: "inherit" }} />
        </label>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 4 }}>
          <button onClick={onClose} style={{
            padding: "8px 14px", borderRadius: 7,
            border: "1px solid #DCE2EC", background: "white", color: "#0A1F44",
            fontSize: 13, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
          }}>Cancel</button>
          <button onClick={() => onSubmit({ date, tech, priority, notes })} style={{
            padding: "8px 14px", borderRadius: 7,
            border: "none", background: "#0A1F44", color: "white",
            fontSize: 13, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
          }}>Schedule</button>
        </div>
      </div>
    </div>
  );
}
const modalInput = {
  padding: "8px 10px", border: "1px solid #DCE2EC", borderRadius: 6,
  background: "white", fontSize: 13, color: "#0A1F44", fontFamily: "inherit",
  outline: "none",
};

// ───────────── note modal ─────────────
function NoteModal({ alert, onClose, onSubmit }) {
  const [val, setVal] = useStateAlerts(localStorage.getItem(`fhh_alert_note_${alert.alert_id}`) || "");
  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, zIndex: 100,
      background: "rgba(10,31,68,0.45)",
      display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderRadius: 12, width: 440, maxWidth: "100%",
        padding: "22px 24px", boxShadow: "0 20px 60px rgba(10,31,68,0.25)",
        display: "flex", flexDirection: "column", gap: 14,
      }}>
        <div style={{ fontSize: 16, fontWeight: 600, color: "#0A1F44" }}>Add note</div>
        <textarea value={val} onChange={(e) => setVal(e.target.value)} rows={4}
          style={{ ...modalInput, resize: "vertical", fontFamily: "inherit" }}
          placeholder="Notes for the team..." />
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button onClick={onClose} style={{
            padding: "8px 14px", borderRadius: 7, border: "1px solid #DCE2EC",
            background: "white", color: "#0A1F44", fontSize: 13, fontWeight: 600,
            cursor: "pointer", fontFamily: "inherit",
          }}>Cancel</button>
          <button onClick={() => onSubmit(val)} style={{
            padding: "8px 14px", borderRadius: 7, border: "none",
            background: "#0A1F44", color: "white", fontSize: 13, fontWeight: 600,
            cursor: "pointer", fontFamily: "inherit",
          }}>Save</button>
        </div>
      </div>
    </div>
  );
}

// ───────────── toast ─────────────
function Toast({ message }) {
  if (!message) return null;
  return (
    <div style={{
      position: "fixed", bottom: 24, left: "50%", transform: "translateX(-50%)",
      background: "#0A1F44", color: "white", padding: "10px 18px",
      borderRadius: 999, fontSize: 13, fontWeight: 500,
      boxShadow: "0 8px 24px rgba(10,31,68,0.25)", zIndex: 200,
      animation: "fhhToastIn 200ms ease",
    }}>{message}</div>
  );
}

// ───────────── empty state ─────────────
function EmptyState({ onClear }) {
  return (
    <div style={{
      background: "white", border: "1px dashed #DCE2EC", borderRadius: 12,
      padding: "40px 24px", textAlign: "center",
    }}>
      <div style={{
        width: 48, height: 48, borderRadius: "50%",
        background: "#EAF7F0",
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        color: "#0F8B5C", fontSize: 20, marginBottom: 8,
      }}>✓</div>
      <div style={{ fontSize: 16, fontWeight: 600, color: "#0A1F44", letterSpacing: -0.2 }}>
        No alerts match your filters
      </div>
      <div style={{ fontSize: 13, color: "#6B7280", marginTop: 4 }}>
        Try widening the criteria or clearing filters.
      </div>
      {onClear && (
        <button onClick={onClear} style={{
          marginTop: 14, padding: "8px 14px", borderRadius: 7,
          border: "1px solid #DCE2EC", background: "white", color: "#0A1F44",
          fontSize: 13, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
        }}>Clear filters</button>
      )}
    </div>
  );
}

// ───────────── screen ─────────────
function AlertsScreen({ onOpenMachine }) {
  const [kpis, setKpis] = useStateAlerts(null);
  const [allAlerts, setAllAlerts] = useStateAlerts(null);
  // Default to "All" so the page surfaces every state — including
  // critical groups currently parked in `scheduled` (e.g. the demo's
  // Al Nakheel · Yankee row) which would otherwise be hidden behind the
  // Active tab. Operators can still pivot to Active for triage focus.
  const [tab, setTab] = useStateAlerts("all");
  const [search, setSearch] = useStateAlerts("");
  const [machineFilter, setMachineFilter] = useStateAlerts([]);
  const [sevFilter, setSevFilter] = useStateAlerts([]);
  const [compFilter, setCompFilter] = useStateAlerts([]);
  const [sort, setSort] = useStateAlerts("created_at_desc");
  const [bulkMode, setBulkMode] = useStateAlerts(false);
  const [selected, setSelected] = useStateAlerts(new Set());
  const [scheduleFor, setScheduleFor] = useStateAlerts(null);
  const [noteFor, setNoteFor] = useStateAlerts(null);
  const [toast, setToast] = useStateAlerts(null);
  // Hide informational rows by default (Phase F2). Toggle in the toolbar
  // shows "Show informational (N hidden)" with the live hidden-count.
  const [showInformational, setShowInformational] = useStateAlerts(false);
  // Per-row expand state for grouped rows. Map<alert_id, bool>.
  const [expanded, setExpanded] = useStateAlerts({});

  function toggleExpanded(id) {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  // The "include_resolved=true" flag pulls every triage state from the
  // server (active / acknowledged / scheduled / snoozed / resolved) so
  // every tab in the screen header has data without a separate fetch.
  //
  // group_by=component buckets multi-event component rows into single
  // grouped rows with `event_count`, `first_triggered_at`,
  // `latest_triggered_at`, and `underlying_events` for the expand toggle.
  //
  // KPIs (sparklines + active counters at the top of the page) get a
  // machine_id query param when a single machine is selected so the
  // strip pivots together with the tab counts. Multiple machines or no
  // filter both fall through to fleet-wide.
  function refetchAlerts() {
    const kpiParams = (machineFilter.length === 1) ? { machine_id: machineFilter[0] } : null;
    window.api.get("/alerts/kpis", kpiParams || undefined).then(setKpis);
    window.api
      .get("/alerts", {
        sort: "created_at", include_resolved: "true",
        group_by: "component",
      })
      .then((r) => setAllAlerts(r.alerts));
  }
  useEffectAlerts(() => { refetchAlerts(); }, []);
  // Re-fetch KPIs whenever the machine filter changes so the strip
  // re-pivots. The /alerts list itself is fetched once and re-filtered
  // client-side (it already carries every triage state on every row).
  useEffectAlerts(() => {
    const kpiParams = (machineFilter.length === 1) ? { machine_id: machineFilter[0] } : null;
    window.api.get("/alerts/kpis", kpiParams || undefined).then(setKpis).catch(() => {});
  }, [machineFilter.join(",")]);

  function showToast(msg) {
    setToast(msg);
    setTimeout(() => setToast(null), 2400);
  }

  // ─────────────────────────────────────────────────────────────────
  // Persisted alert actions — backed by PATCH /alerts/{id}/{action}.
  // We optimistically patch the local list so the alert moves into the
  // new tab instantly; on backend failure we roll back and surface a
  // toast. After every successful action we refetch /alerts/kpis so the
  // header counters stay in sync with the DB.
  // ─────────────────────────────────────────────────────────────────

  async function applyServerStatus(alert, { action, body, optimistic, successMsg, errorMsg }) {
    const id = alert.alert_id;
    const previous = allAlerts;
    setAllAlerts((prev) =>
      (prev || []).map((a) => (a.alert_id === id ? { ...a, ...optimistic } : a))
    );
    try {
      await window.api.patch(`/alerts/${id}/${action}`, body);
      window.api.get("/alerts/kpis").then(setKpis);
      showToast(successMsg);
    } catch (e) {
      setAllAlerts(previous); // rollback
      const msg = errorMsg || e?.body?.error?.message || e?.message || "Action failed.";
      showToast("⚠ " + msg);
    }
  }

  function ack(alert) {
    const now = new Date().toISOString();
    return applyServerStatus(alert, {
      action: "acknowledge",
      body: { acknowledged_by: "Operations Manager" },
      optimistic: {
        _status: "acknowledged", status: "acknowledged",
        acknowledged: true,
        status_changed_by: "Operations Manager",
        status_changed_at: now,
        // Legacy fields the existing JSX still reads:
        _ack_by: "Operations Manager", _ack_at: now,
      },
      successMsg: "Alert acknowledged",
    });
  }

  function snooze(alert) {
    const now = new Date().toISOString();
    const until = new Date(Date.now() + 24*60*60*1000).toISOString();
    return applyServerStatus(alert, {
      action: "snooze",
      body: { snooze_until: until, reason: "Snoozed 24h" },
      optimistic: {
        _status: "snoozed", status: "snoozed",
        acknowledged: true,
        status_changed_by: "Operations Manager",
        status_changed_at: now,
        status_metadata: { snooze_until: until },
        _ack_by: "Operations Manager", _ack_at: now,
        _snoozed_until: until,
      },
      successMsg: "Snoozed for 24 hours",
    });
  }

  function schedule(alert, { date, tech, priority, notes }) {
    const now = new Date().toISOString();
    setScheduleFor(null);
    return applyServerStatus(alert, {
      action: "schedule",
      body: {
        scheduled_date: date,
        technician: tech,
        priority: priority || "normal",
        notes: notes || undefined,
      },
      optimistic: {
        _status: "scheduled", status: "scheduled",
        acknowledged: true,
        status_changed_by: tech,
        status_changed_at: now,
        status_metadata: {
          scheduled_date: date, technician: tech,
          priority: priority || "normal", notes,
        },
        _ack_by: "Operations Manager", _ack_at: now,
        _scheduled_for: date, _scheduled_by: tech,
        _scheduled_priority: priority, _scheduled_notes: notes,
      },
      successMsg: `Maintenance scheduled for ${date}`,
    });
  }

  function resolve(alert) {
    const now = new Date().toISOString();
    return applyServerStatus(alert, {
      action: "resolve",
      body: {
        resolved_by: "Operations Manager",
        resolution_notes: "Marked resolved by operator.",
      },
      optimistic: {
        _status: "resolved", status: "resolved",
        acknowledged: true,
        status_changed_by: "Operations Manager",
        status_changed_at: now,
        status_metadata: { resolution_notes: "Marked resolved by operator." },
        _resolved_at: now, _resolved_by: "Operations Manager",
        _resolution_notes: "Marked resolved by operator.",
      },
      successMsg: "Alert marked resolved",
    });
  }
  function addNote(alert, text) {
    if (text.trim()) {
      localStorage.setItem(`fhh_alert_note_${alert.alert_id}`, text);
      showToast("Note saved");
    }
    setNoteFor(null);
  }

  // bulk actions
  function bulkAck() {
    Array.from(selected).forEach((id) => {
      const a = allAlerts.find((x) => x.alert_id === id);
      if (a) ack(a);
    });
    setSelected(new Set()); setBulkMode(false);
    showToast(`${selected.size} alerts acknowledged`);
  }
  function bulkSnooze() {
    Array.from(selected).forEach((id) => {
      const a = allAlerts.find((x) => x.alert_id === id);
      if (a) snooze(a);
    });
    setSelected(new Set()); setBulkMode(false);
    showToast(`${selected.size} alerts snoozed`);
  }

  // The server now ships the persisted triage status on every alert
  // (`_status` / `status`); no client-side override layer needed.
  const merged = allAlerts || [];

  // Tab counts pivot off the same persisted statuses but MUST respect the
  // machine + component filters — otherwise the strip says "Active 3,
  // Scheduled 1, Resolved 18" identical for every machine pick, which
  // operators rightly read as broken. The informational toggle is NOT
  // applied here on purpose: the tab strip is a status pivot, not a
  // visibility pivot, and hiding informational rows from a count would
  // hide work that the operator can opt in to see.
  const tabScoped = useMemoAlerts(() => {
    let list = merged;
    if (machineFilter.length) list = list.filter((a) => machineFilter.includes(a.machine_id));
    if (compFilter.length)    list = list.filter((a) => compFilter.includes(a.component_id));
    return list;
  }, [merged, machineFilter, compFilter]);

  const counts = useMemoAlerts(() => {
    const c = { active: 0, acknowledged: 0, snoozed: 0, scheduled: 0, resolved: 0, all: tabScoped.length };
    tabScoped.forEach((a) => {
      const s = a._status || a.status || "active";
      if (c[s] != null) c[s]++;
    });
    return c;
  }, [tabScoped]);

  // apply tab + filters + search + sort
  const visible = useMemoAlerts(() => {
    let list = merged;
    if (tab !== "all") list = list.filter((a) => (a._status || a.status || "active") === tab);
    if (machineFilter.length) list = list.filter((a) => machineFilter.includes(a.machine_id));
    // Filter chips key off the LIVE tier (not the seeded alarm severity)
    // so "Critical" matches anything the model currently scores 70+, even
    // if it fired originally as info.
    if (sevFilter.length)     list = list.filter((a) => sevFilter.includes(a.tier || a.severity));
    // Suppress benign "everything's fine" rows unless the operator opts in.
    // The backend flag is set only when ALL events in a grouped row are
    // status-message-style descriptions AND the live tier is healthy.
    if (!showInformational)   list = list.filter((a) => !a.is_informational);
    if (compFilter.length)    list = list.filter((a) => compFilter.includes(a.component_id));
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter((a) =>
        a.title.toLowerCase().includes(q) ||
        a.description.toLowerCase().includes(q) ||
        MACHINE_NAMES[a.machine_id].toLowerCase().includes(q) ||
        COMPONENT_LABEL_ALERTS[a.component_id].toLowerCase().includes(q) ||
        a.component_id.includes(q) || a.machine_id.includes(q)
      );
    }
    const sorters = {
      created_at_desc: (a, b) => b.created_at.localeCompare(a.created_at),
      created_at_asc:  (a, b) => a.created_at.localeCompare(b.created_at),
      severity:        (a, b) => {
        // Sort by live tier (4 buckets); fall back to legacy severity for
        // older payloads. Tie-break on risk_score so a 79 and a 95 in the
        // same critical bucket render in the obvious order.
        const order = { critical: 0, warning: 1, watch: 2, healthy: 3, info: 4 };
        const at = a.tier || a.severity;
        const bt = b.tier || b.severity;
        return (order[at] ?? 9) - (order[bt] ?? 9) || (b.risk_score - a.risk_score);
      },
      machine:         (a, b) => MACHINE_NAMES[a.machine_id].localeCompare(MACHINE_NAMES[b.machine_id]),
    };
    return list.slice().sort(sorters[sort] || sorters.created_at_desc);
  }, [merged, tab, machineFilter, sevFilter, compFilter, search, sort, showInformational]);

  // Count rows currently suppressed by the informational toggle — scoped
  // to the same filter pipeline the visible list uses (tab / machine /
  // component / search), so the "(N hidden)" badge always tells the
  // truth about what's missing from THIS view, not from the fleet.
  const hiddenInformationalCount = React.useMemo(() => {
    if (showInformational) return 0;
    let list = merged;
    if (tab !== "all") list = list.filter((a) => (a._status || a.status || "active") === tab);
    if (machineFilter.length) list = list.filter((a) => machineFilter.includes(a.machine_id));
    if (compFilter.length)    list = list.filter((a) => compFilter.includes(a.component_id));
    if (sevFilter.length)     list = list.filter((a) => sevFilter.includes(a.tier || a.severity));
    return list.filter((a) => a.is_informational).length;
  }, [merged, tab, machineFilter, compFilter, sevFilter, showInformational]);

  const anyFilter = machineFilter.length + sevFilter.length + compFilter.length > 0 || search.trim();
  function clearFilters() {
    setMachineFilter([]); setSevFilter([]); setCompFilter([]); setSearch("");
  }

  const machineOpts = Object.entries(MACHINE_NAMES).map(([id, label]) => ({ id, label }));
  // Filter chips list the four LIVE tiers. `info` is the legacy alarm
  // severity and never appears as a `tier` value, so it's intentionally
  // dropped from the chip set even though SEV_META still defines it for
  // tooltip rendering ("Originally fired as: info").
  const sevOpts = [
    { id: "critical", label: "Critical" },
    { id: "warning",  label: "Warning" },
    { id: "watch",    label: "Watch" },
    { id: "healthy",  label: "Healthy" },
  ];
  const compOpts = Object.entries(COMPONENT_LABEL_ALERTS).map(([id, label]) => ({ id, label }));

  return (
    <div style={{ padding: "20px 28px 100px", display: "flex", flexDirection: "column", gap: 16 }}>
      {/* page header */}
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 0.6, textTransform: "uppercase", color: "#6B7280" }}>
            Triage inbox
          </div>
          <h1 style={{ margin: "4px 0 0", fontSize: 28, fontWeight: 600, color: "#0A1F44", letterSpacing: -0.6 }}>
            Alerts
          </h1>
          <div style={{ fontSize: 13, color: "#6B7280", marginTop: 4 }}>
            Every active maintenance signal across the fleet, prioritized.
          </div>
        </div>
      </div>

      {/* KPI strip */}
      <AlertsKpiStrip kpis={kpis} />

      {/* sticky toolbar */}
      <div style={{
        position: "sticky", top: 0, zIndex: 20,
        background: "#F4F6FA", paddingTop: 4, paddingBottom: 8,
        marginTop: 4,
      }}>
        <div style={{
          background: "white", border: "1px solid #E5E8EE", borderRadius: 10,
          padding: "12px 14px", boxShadow: "0 1px 2px rgba(10,31,68,0.04)",
          display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center",
        }}>
          {/* search */}
          <div style={{ position: "relative", flex: "1 1 240px", minWidth: 180 }}>
            <span style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: "#9CA3AF", fontSize: 14 }}>⌕</span>
            <input
              type="text" value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="Search alerts by machine, component, sensor..."
              style={{
                width: "100%",
                padding: "8px 10px 8px 32px",
                border: "1px solid #DCE2EC", borderRadius: 7,
                fontSize: 13, color: "#0A1F44", fontFamily: "inherit",
                outline: "none", background: "white",
              }}
              onFocus={(e) => { e.currentTarget.style.borderColor = "#0A1F44"; }}
              onBlur={(e) => { e.currentTarget.style.borderColor = "#DCE2EC"; }}
            />
          </div>
          <FilterChip label="Machine"   options={machineOpts} selected={machineFilter} onChange={setMachineFilter} />
          <FilterChip label="Severity"  options={sevOpts}     selected={sevFilter}     onChange={setSevFilter} />
          <FilterChip label="Component" options={compOpts}    selected={compFilter}    onChange={setCompFilter} />
          {/* Informational toggle — visible whenever there's something to
              toggle in the current filter scope (or the user has opted to
              show them). Renders across all tabs since informational rows
              can land in active/acknowledged/scheduled/etc. */}
          {(showInformational || hiddenInformationalCount > 0) && (
            <button
              onClick={() => setShowInformational((v) => !v)}
              title="Status-message rows (e.g. 'within band', 'stable') are hidden by default. Toggle to include them."
              style={{
                padding: "7px 12px", borderRadius: 8,
                border: showInformational ? "1px solid #0F8B5C" : "1px dashed #B0B8C8",
                background: showInformational ? "#E6F6EE" : "white",
                color: showInformational ? "#0F8B5C" : "#6B7280",
                fontSize: 12.5, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
              }}
            >
              {showInformational
                ? "✓ Showing informational"
                : `Show informational (${hiddenInformationalCount} hidden)`}
            </button>
          )}
          <div style={{ flex: 1 }} />
          <SortMenu value={sort} onChange={setSort} />
          <button
            onClick={() => { setBulkMode(!bulkMode); setSelected(new Set()); }}
            style={{
              padding: "7px 12px", borderRadius: 8,
              border: bulkMode ? "1px solid #0A1F44" : "1px solid #DCE2EC",
              background: bulkMode ? "#0A1F44" : "white",
              color: bulkMode ? "white" : "#0A1F44",
              fontSize: 12.5, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
            }}
          >{bulkMode ? "Done" : "Select"}</button>
        </div>

        {/* active filter pills */}
        {(anyFilter) && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8, alignItems: "center" }}>
            {machineFilter.map((id) => (
              <ActivePill key={`m-${id}`} label={`Machine: ${MACHINE_NAMES[id]}`}
                onRemove={() => setMachineFilter(machineFilter.filter((x) => x !== id))} />
            ))}
            {sevFilter.map((id) => (
              <ActivePill key={`s-${id}`} label={`Severity: ${SEV_META[id].label}`}
                onRemove={() => setSevFilter(sevFilter.filter((x) => x !== id))} />
            ))}
            {compFilter.map((id) => (
              <ActivePill key={`c-${id}`} label={`Component: ${COMPONENT_LABEL_ALERTS[id]}`}
                onRemove={() => setCompFilter(compFilter.filter((x) => x !== id))} />
            ))}
            {search.trim() && (
              <ActivePill label={`Search: "${search}"`} onRemove={() => setSearch("")} />
            )}
            <button onClick={clearFilters} style={{
              background: "transparent", border: "none", color: "#0A1F44",
              fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
              textDecoration: "underline", padding: 0, marginLeft: 4,
            }}>Clear all filters</button>
          </div>
        )}
      </div>

      {/* status tabs */}
      <StatusTabs active={tab} onChange={setTab} counts={counts} />

      {/* list */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {!allAlerts && <div style={{ height: 120, background: "#EEF1F6", borderRadius: 10 }} />}
        {allAlerts && visible.length === 0 && (
          <EmptyState onClear={anyFilter ? clearFilters : null} />
        )}
        {visible.map((a) => (
          <AlertCard
            key={a.alert_id}
            alert={a}
            bulkMode={bulkMode}
            checked={selected.has(a.alert_id)}
            onToggleCheck={() => {
              const next = new Set(selected);
              if (next.has(a.alert_id)) next.delete(a.alert_id);
              else next.add(a.alert_id);
              setSelected(next);
            }}
            onOpenMachine={onOpenMachine}
            onAck={() => ack(a)}
            onSchedule={() => setScheduleFor(a)}
            onSnooze={() => snooze(a)}
            onResolve={() => resolve(a)}
            onAddNote={() => setNoteFor(a)}
            isExpanded={!!expanded[a.alert_id]}
            onToggleExpand={() => toggleExpanded(a.alert_id)}
          />
        ))}
      </div>

      {/* bulk action bar */}
      {bulkMode && selected.size > 0 && (
        <div style={{
          position: "fixed", bottom: 24, left: "50%", transform: "translateX(-50%)",
          background: "#0A1F44", color: "white",
          padding: "10px 18px", borderRadius: 999,
          boxShadow: "0 12px 30px rgba(10,31,68,0.3)",
          display: "flex", alignItems: "center", gap: 14, zIndex: 90,
        }}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>{selected.size} selected</div>
          <div style={{ width: 1, height: 18, background: "rgba(255,255,255,0.2)" }} />
          <button onClick={bulkAck} style={bulkBtn}>Acknowledge All</button>
          <button onClick={bulkSnooze} style={bulkBtn}>Snooze All</button>
          <button onClick={() => { setSelected(new Set()); setBulkMode(false); }} style={{
            ...bulkBtn, background: "transparent", border: "1px solid rgba(255,255,255,0.3)",
          }}>Cancel</button>
        </div>
      )}

      {scheduleFor && (
        <ScheduleModal alert={scheduleFor} onClose={() => setScheduleFor(null)}
          onSubmit={(payload) => schedule(scheduleFor, payload)} />
      )}
      {noteFor && (
        <NoteModal alert={noteFor} onClose={() => setNoteFor(null)}
          onSubmit={(text) => addNote(noteFor, text)} />
      )}
      <Toast message={toast} />
    </div>
  );
}

const bulkBtn = {
  background: "rgba(255,255,255,0.12)", color: "white",
  border: "none", padding: "6px 12px", borderRadius: 999,
  fontSize: 12.5, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
  transition: "background .15s",
};

function ActivePill({ label, onRemove }) {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "4px 10px", borderRadius: 999,
      background: "#EAEFF8", color: "#0A1F44",
      fontSize: 12, fontWeight: 600,
    }}>
      {label}
      <button
        aria-label={`Remove filter ${label}`}
        onClick={onRemove}
        style={{
          width: 14, height: 14, borderRadius: "50%",
          border: "none", background: "rgba(10,31,68,0.15)", color: "#0A1F44",
          fontSize: 10, fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
          display: "inline-flex", alignItems: "center", justifyContent: "center",
        }}
      >×</button>
    </span>
  );
}

Object.assign(window, { AlertsScreen });
