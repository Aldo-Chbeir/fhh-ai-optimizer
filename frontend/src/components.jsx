// Shared UI atoms used across the dashboard. Names are intentionally specific
// (no global `styles` collisions).

const TIER_META = {
  healthy:  { label: "Healthy",  fg: "#0F8B5C", bg: "#E6F6EE", dot: "#15A56C" },
  watch:    { label: "Watch",    fg: "#9A7700", bg: "#FFF6D6", dot: "#E2B400" },
  warning:  { label: "Warning",  fg: "#B14A00", bg: "#FFEDDD", dot: "#E66A12" },
  critical: { label: "Critical", fg: "#B31E2B", bg: "#FCE3E5", dot: "#D7263D" },
};

function TierPill({ tier, size = "md" }) {
  const m = TIER_META[tier] || TIER_META.healthy;
  const px = size === "sm" ? "4px 8px" : "6px 10px";
  const fz = size === "sm" ? 11 : 12;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: px, borderRadius: 999,
      background: m.bg, color: m.fg,
      fontSize: fz, fontWeight: 600, letterSpacing: 0.2,
      textTransform: "uppercase",
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: "50%", background: m.dot,
        boxShadow: `0 0 0 2px ${m.bg}`,
      }} />
      {m.label}
    </span>
  );
}

function StatusDot({ status }) {
  const color = status === "running" ? "#15A56C"
              : status === "idle" ? "#9CA3AF"
              : status === "maintenance" ? "#E66A12"
              : "#6B7280";
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6,
      fontSize: 11, color: "#6B7280", fontWeight: 500, letterSpacing: 0.3,
      textTransform: "uppercase" }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", background: color,
        boxShadow: status === "running" ? `0 0 0 3px ${color}22` : "none" }} />
      {status}
    </span>
  );
}

function formatUsdCompact(n) {
  if (n == null) return "—";
  if (Math.abs(n) >= 1_000_000) return "$" + (n / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  if (Math.abs(n) >= 1_000) return "$" + Math.round(n / 1_000) + "K";
  return "$" + n;
}

function formatRelative(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return Math.floor(diff / 60) + "m ago";
  if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
  return Math.floor(diff / 86400) + "d ago";
}

Object.assign(window, { TIER_META, TierPill, StatusDot, formatUsdCompact, formatRelative });
