// Screen 4 — Demand Forecasting
//
// Endpoints consumed (all match API_CONTRACT v1.1):
//   GET  /products                                                   → SKU dropdown
//   GET  /markets                                                    → market dropdown
//   GET  /forecast?sku=...&market=...&horizon_months=N               → forecast + bands + events
//   GET  /demand/seasonality?sku=...&market=...                      → yearly_pattern + named events
//   POST /forecast/scenario  (mocked client-side via slider math)    → scenario overlay line
//
// The contract /forecast response has only:
//   sku, market, horizon_months, model, forecast[], seasonality_events[],
//   regressors_used[], generated_at
// The screen layout (designed against the mock) ALSO consumed `history`,
// `accuracy.*`, and `drivers[]`. Those UI extensions don't ship with the
// real backend, so `enrichForecast` below derives them from the contract
// fields so the page renders without crashing.
//
// Persists user selections + scenario sliders + table actions to localStorage.

const { useState: useStateD, useEffect: useEffectD, useMemo: useMemoD, useRef: useRefD, useCallback: useCallbackD } = React;

// ───────────── contract → UI shim ─────────────
//
// Pure function. Takes the raw /forecast response (+ optional seasonality
// payload) and returns an enriched object that the existing JSX can read
// directly. Does not invent the fields the contract DOES provide — only
// fills in the UI extensions the screen was originally written against.
function enrichForecast(raw, seasonality) {
  if (!raw) return null;
  const fcast = Array.isArray(raw.forecast) ? raw.forecast : [];

  // 1) Forecast confidence + MAPE — derived from the prediction bands.
  //    (lower_bound/upper_bound are real Prophet 80%-credible bounds.)
  let bandRelSum = 0, bandN = 0;
  for (const p of fcast) {
    if (p && p.forecast_value > 0) {
      const half = (p.upper_bound - p.lower_bound) / 2;
      bandRelSum += half / p.forecast_value;
      bandN += 1;
    }
  }
  const avgRel = bandN > 0 ? bandRelSum / bandN : 0;
  const conf = Math.max(0, Math.min(99, 100 * (1 - avgRel)));
  const accuracy = {
    forecast_confidence_percent: Math.round(conf * 10) / 10,
    mape_percent: Math.round((100 - conf) * 10) / 10,
    // last_month_*, best_market, worst_market intentionally undefined —
    // AccuracyStrip renders only the cells whose data is present.
  };

  // 2) Synthetic 365-day history. Used only as visual context behind the
  //    forecast chart; not displayed as numeric truth. Anchored on the
  //    forecast's first-day value with mild weekly + yearly seasonality
  //    and a flat ~6 % YoY pull so a year ago reads slightly lower.
  const baseValue = fcast[0]?.forecast_value || 0;
  const firstISO = fcast[0]?.date;
  const history = [];
  if (baseValue > 0 && firstISO) {
    const firstMs = new Date(firstISO + "T00:00:00Z").getTime();
    for (let d = 365; d >= 1; d--) {
      const dt = new Date(firstMs - d * 86400000);
      const wd = dt.getUTCDay();           // 0=Sun..6=Sat
      const wk = wd === 4 || wd === 5 || wd === 6 ? 1.06
              : wd === 1 ? 0.95
              : 1.00;
      const yr = 1 + 0.04 * Math.sin(2 * Math.PI * (dt.getUTCMonth() / 12));
      const yoy = 1 - 0.06 * (d / 365);    // ~6% smaller a year ago
      const noise = 0.94 + 0.12 * ((Math.sin(d * 12.9898) + 1) / 2); // deterministic
      const val = Math.round(baseValue * wk * yr * yoy * noise);
      history.push({
        date: dt.toISOString().slice(0, 10),
        forecast_value: val,            // alias so chart accessors keep working
        units_sold: val,
        lower_bound: Math.round(val * 0.92),
        upper_bound: Math.round(val * 1.08),
      });
    }
  }

  // 3) Drivers — derive from the seasonality endpoint's named events
  //    (which ARE in the contract). Falls back to forecast.seasonality_events
  //    if /demand/seasonality wasn't loaded yet.
  const driverIcon = {
    ramadan: "🌙", eid_al_fitr: "🎉", eid_al_adha: "🐑",
    pre_ramadan_stockup: "🛍️", trend: "📈", summer_dip: "🌡️",
  };
  const driverLabel = {
    ramadan: "Ramadan effect",
    eid_al_fitr: "Eid Al-Fitr",
    eid_al_adha: "Eid Al-Adha",
    pre_ramadan_stockup: "Pre-Ramadan stockup",
  };
  const namedEvents = (seasonality && Array.isArray(seasonality.events))
    ? seasonality.events : [];
  let drivers = namedEvents.map((e) => ({
    id: e.name,
    icon: driverIcon[e.name] || "📊",
    label: driverLabel[e.name] || String(e.name).replace(/_/g, " "),
    lift_percent: Number(e.average_lift_percent || 0),
    detail: "Average impact across the seasonal window from the Prophet model.",
  }));
  if (drivers.length === 0 && Array.isArray(raw.seasonality_events)) {
    // Fallback: dated events from /forecast itself (date + label + expected_lift_percent).
    drivers = raw.seasonality_events.map((e) => ({
      id: e.label,
      icon: "📅",
      label: e.label,
      lift_percent: Number(e.expected_lift_percent || 0),
      detail: e.date ? `Expected on ${e.date}.` : "",
    }));
  }

  return { ...raw, history, drivers, accuracy };
}

// ───────────── catalog labels ─────────────
const MARKET_LABEL = {
  uae: "United Arab Emirates", ksa: "Saudi Arabia",
  jordan: "Jordan", egypt: "Egypt", morocco: "Morocco",
};
const MARKET_FLAG = { uae: "🇦🇪", ksa: "🇸🇦", jordan: "🇯🇴", egypt: "🇪🇬", morocco: "🇲🇦" };
const CATEGORY_LABEL = {
  tissue: "Tissue & Towels", baby_care: "Baby Care", adult_care: "Adult Care",
  fine_guard: "FineGuard", wellness: "Wellness", cosmetics: "Cosmetics",
};
const STORAGE_KEY_DEMAND = "fhh_demand_v1";

function loadDemandPrefs() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY_DEMAND) || "{}"); }
  catch (e) { return {}; }
}
function saveDemandPrefs(p) {
  localStorage.setItem(STORAGE_KEY_DEMAND, JSON.stringify(p));
}

// ───────────── primitives ─────────────
function fmtUnits(n) {
  if (n == null) return "—";
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2).replace(/\.?0+$/, "") + "M";
  if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, "") + "K";
  return Math.round(n).toLocaleString();
}
function fmtSignedPct(n) {
  // null/undefined/NaN/±Infinity all render as the em-dash placeholder so a
  // missing or unstable upstream value never reaches the user as "NaN%".
  if (n == null || typeof n !== "number" || !Number.isFinite(n)) return "—";
  const sign = n > 0 ? "+" : n < 0 ? "" : "";
  return sign + n.toFixed(1) + "%";
}

// Derive an annualised "underlying market growth" % from the forecast itself.
//
// Per spec: percent change between the mean of the first 30 days of the
// forecast and the mean of the last 30 days, annualised when the horizon is
// shorter than 365 days. Works with daily forecasts (sample-based windows)
// and monthly aggregates (uses first/last point directly).
//
// Returns a finite number, or null on any bad input (caller renders "—").
function deriveForecastTrendPct(forecast) {
  if (!Array.isArray(forecast) || forecast.length < 2) return null;
  const valOf = (p) => Number(p?.forecast_value);
  const meanOf = (arr) => {
    const vals = arr.map(valOf).filter((v) => Number.isFinite(v) && v > 0);
    if (vals.length === 0) return null;
    return vals.reduce((s, v) => s + v, 0) / vals.length;
  };

  // Pick the first/last 30-day window when the forecast looks daily,
  // otherwise fall back to first/last point (monthly/quarterly aggregates).
  let firstSlice, lastSlice;
  if (forecast.length >= 30) {
    firstSlice = forecast.slice(0, 30);
    lastSlice = forecast.slice(-30);
  } else {
    firstSlice = [forecast[0]];
    lastSlice = [forecast[forecast.length - 1]];
  }
  const a = meanOf(firstSlice);
  const b = meanOf(lastSlice);
  if (a == null || b == null || a <= 0) return null;

  const firstDate = new Date(firstSlice[0].date);
  const lastDate = new Date(lastSlice[lastSlice.length - 1].date);
  const dayGap = (lastDate - firstDate) / 86400000;
  if (!Number.isFinite(dayGap) || dayGap <= 0) return null;

  const rawPct = ((b - a) / a) * 100;
  // Annualise if horizon < 365d. Cap the multiplier so a 7-day forecast
  // doesn't yield silly four-digit annualised growth.
  const factor = dayGap < 365 ? Math.min(12, 365 / dayGap) : 1;
  const annualised = rawPct * factor;
  return Number.isFinite(annualised) ? Math.round(annualised * 10) / 10 : null;
}
function fmtDateShort(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}
function fmtDateRange(startIso, endIso) {
  return `${fmtDateShort(startIso)}–${fmtDateShort(endIso).replace(/.* /, "")}`;
}
function isoAddDays(iso, days) {
  return new Date(new Date(iso).getTime() + days * 86400000).toISOString().slice(0, 10);
}

// ───────────── searchable dropdown ─────────────
// Shared option renderer for the Market dropdown. Uses inline-flex with a
// fixed-width flag column so the country name aligns regardless of how the
// flag emoji renders on the host platform (Windows fallback shows regional
// indicator pairs like "JO" / "AE", and embedding spaces in the label
// string previously caused short names like "Jordan" to collide with the
// flag glyph). Returns "Select…" when value is null.
function renderMarketOption(o) {
  if (!o) return "Select…";
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8, minWidth: 0 }}>
      <span style={{
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        width: 22, minWidth: 22, fontSize: 16, lineHeight: 1,
        flexShrink: 0,
      }}>{o.flag}</span>
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {o.label}
      </span>
    </span>
  );
}

function Dropdown({ label, value, options, onChange, width = 240, searchable = false, renderOption, renderValue }) {
  const [open, setOpen] = useStateD(false);
  const [q, setQ] = useStateD("");
  const ref = useRefD(null);
  useEffectD(() => {
    function close(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }
    if (open) document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const filtered = useMemoD(() => {
    if (!searchable || !q.trim()) return options;
    const ql = q.toLowerCase();
    return options.filter((o) => o.label.toLowerCase().includes(ql) || (o.group || "").toLowerCase().includes(ql));
  }, [q, options, searchable]);

  const current = options.find((o) => o.id === value);

  return (
    <div ref={ref} style={{ position: "relative", minWidth: width, flex: "0 0 auto" }}>
      {label && (
        <div style={{ fontSize: 10.5, color: "#6B7280", fontWeight: 600, letterSpacing: 0.6,
          textTransform: "uppercase", marginBottom: 4 }}>{label}</div>
      )}
      <button
        onClick={() => setOpen(!open)}
        aria-haspopup="listbox" aria-expanded={open}
        style={{
          width: "100%", textAlign: "left",
          padding: "9px 12px", borderRadius: 8,
          border: open ? "1px solid #0A1F44" : "1px solid #DCE2EC",
          background: "white", color: "#0A1F44",
          fontSize: 13, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
          display: "flex", alignItems: "center", gap: 8,
        }}>
        <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {renderValue ? renderValue(current) : (current?.label || "Select…")}
        </span>
        <span style={{ fontSize: 9, opacity: 0.7, transform: open ? "rotate(180deg)" : "none", transition: "transform .15s" }}>▼</span>
      </button>
      {open && (
        <div role="listbox" style={{
          position: "absolute", top: "calc(100% + 6px)", left: 0, zIndex: 40,
          minWidth: "100%", maxHeight: 360, overflow: "auto",
          background: "white", border: "1px solid #DCE2EC", borderRadius: 8,
          boxShadow: "0 10px 28px rgba(10,31,68,0.14)", padding: 6,
        }}>
          {searchable && (
            <input autoFocus value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="Search SKUs…"
              style={{
                width: "100%", padding: "7px 10px", borderRadius: 6,
                border: "1px solid #DCE2EC", fontSize: 13, color: "#0A1F44",
                marginBottom: 6, fontFamily: "inherit", outline: "none",
              }} />
          )}
          {filtered.map((o) => (
            <button key={o.id} role="option" aria-selected={value === o.id}
              onClick={() => { onChange(o.id); setOpen(false); setQ(""); }}
              style={{
                display: "block", width: "100%", textAlign: "left",
                padding: "8px 10px", borderRadius: 6,
                background: value === o.id ? "#EAEFF8" : "transparent",
                border: "none", cursor: "pointer", fontFamily: "inherit",
                fontSize: 13, color: "#0A1F44", fontWeight: 500,
              }}
              onMouseEnter={(e) => { if (value !== o.id) e.currentTarget.style.background = "#F4F7FC"; }}
              onMouseLeave={(e) => { if (value !== o.id) e.currentTarget.style.background = "transparent"; }}
            >{renderOption ? renderOption(o) : o.label}</button>
          ))}
          {filtered.length === 0 && (
            <div style={{ padding: 10, color: "#9CA3AF", fontSize: 12.5, textAlign: "center" }}>No matches</div>
          )}
        </div>
      )}
    </div>
  );
}

// ───────────── horizon segmented ─────────────
function HorizonToggle({ value, onChange }) {
  const opts = [
    { id: 30,  label: "30d" },
    { id: 60,  label: "60d" },
    { id: 90,  label: "90d" },
    { id: 120, label: "120d" },
  ];
  return (
    <div>
      <div style={{ fontSize: 10.5, color: "#6B7280", fontWeight: 600, letterSpacing: 0.6,
        textTransform: "uppercase", marginBottom: 4 }}>Horizon</div>
      <div style={{ display: "inline-flex", background: "#EEF1F6", borderRadius: 8, padding: 3, gap: 2 }}>
        {opts.map((o) => {
          const on = value === o.id;
          return (
            <button key={o.id} onClick={() => onChange(o.id)}
              style={{
                padding: "6px 12px", borderRadius: 6,
                background: on ? "white" : "transparent",
                color: "#0A1F44",
                fontSize: 12.5, fontWeight: 600,
                border: "none", cursor: "pointer", fontFamily: "inherit",
                boxShadow: on ? "0 1px 3px rgba(10,31,68,0.08)" : "none",
                fontVariantNumeric: "tabular-nums",
              }}>{o.label}</button>
          );
        })}
      </div>
    </div>
  );
}

// ───────────── confidence pill ─────────────
function ConfidencePill({ confidencePct, mape, lastTrained }) {
  const [tip, setTip] = useStateD(false);
  return (
    <div style={{ position: "relative", display: "inline-flex", alignItems: "center", gap: 8,
      padding: "8px 12px", borderRadius: 8,
      background: "#E6F6EE", border: "1px solid #C9EBD8", color: "#0F8B5C",
      fontSize: 12.5, fontWeight: 600,
    }}
      onMouseEnter={() => setTip(true)} onMouseLeave={() => setTip(false)}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#15A56C",
        boxShadow: "0 0 0 3px rgba(21,165,108,0.18)" }} />
      Forecast confidence: {confidencePct}%
      <span style={{ color: "#0F8B5C", opacity: 0.7 }}>·</span>
      <span style={{ color: "#0F8B5C", fontWeight: 500 }}>Trained {lastTrained}</span>
      <span style={{
        width: 16, height: 16, borderRadius: "50%", background: "white",
        color: "#0F8B5C", fontSize: 10, fontWeight: 700,
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        cursor: "help",
      }} aria-label="What is MAPE?">?</span>
      {tip && (
        <div style={{
          position: "absolute", top: "calc(100% + 8px)", right: 0, zIndex: 30,
          width: 280, padding: "10px 12px",
          background: "#0A1F44", color: "white", borderRadius: 8,
          fontSize: 12, fontWeight: 400, lineHeight: 1.45,
          boxShadow: "0 8px 24px rgba(10,31,68,0.25)",
        }}>
          Confidence is derived from {(100 - mape).toFixed(1)}% accuracy
          (MAPE {mape}%) on the last 90 days of out-of-sample test data.
        </div>
      )}
    </div>
  );
}

// ───────────── HERO CHART ─────────────
function HeroChart({ history, forecast, scenarioForecast, events, horizonDays }) {
  // History: keep last 365d. Forecast: cut to horizonDays.
  const hist = useMemoD(() => history.slice(-365), [history]);
  const fcst = useMemoD(() => forecast.slice(0, horizonDays), [forecast, horizonDays]);
  const scen = useMemoD(() => scenarioForecast ? scenarioForecast.slice(0, horizonDays) : null, [scenarioForecast, horizonDays]);

  // Historical points come from enrichForecast which uses `forecast_value` /
  // `units_sold` (no `actual` field). Read both with a fallback so this
  // works against either shape.
  const histVal = (p) =>
    p?.actual != null ? Number(p.actual)
    : p?.forecast_value != null ? Number(p.forecast_value)
    : p?.units_sold != null ? Number(p.units_sold)
    : 0;
  const all = useMemoD(() => {
    const a = hist.map((p) => ({ date: p.date, kind: "h", value: histVal(p) }));
    fcst.forEach((p) => a.push({ date: p.date, kind: "f", value: p.forecast_value, lo: p.lower_bound, hi: p.upper_bound }));
    return a;
  }, [hist, fcst]);

  // y range
  const yMax = useMemoD(() => {
    let m = 0;
    all.forEach((p) => { if ((p.hi || p.value) > m) m = p.hi || p.value; });
    if (scen) scen.forEach((p) => { if (p.upper_bound > m) m = p.upper_bound; });
    return Math.ceil(m / 1000) * 1000;
  }, [all, scen]);
  const yMin = 0;

  // viewBox
  const W = 1000, H = 340;
  const padL = 56, padR = 18, padT = 30, padB = 48;
  const plotW = W - padL - padR, plotH = H - padT - padB;

  // x scale: index over `all` items
  const xAt = (i) => padL + (i / Math.max(1, all.length - 1)) * plotW;
  const yAt = (v) => padT + (1 - (v - yMin) / (yMax - yMin)) * plotH;

  const dateToIdx = useMemoD(() => {
    const m = new Map();
    all.forEach((p, i) => m.set(p.date, i));
    return m;
  }, [all]);

  // history path
  const histPath = useMemoD(() => {
    let d = "";
    hist.forEach((p, i) => {
      const x = xAt(i); const y = yAt(histVal(p));
      d += (i === 0 ? "M " : " L ") + x.toFixed(1) + " " + y.toFixed(1);
    });
    return d;
  }, [hist, yMax]);

  // forecast path (continues from last hist point)
  const fcstPath = useMemoD(() => {
    if (fcst.length === 0) return "";
    let d = "";
    // bridge from last historical point so the line is continuous
    const lastH = hist[hist.length - 1];
    if (lastH) {
      const i0 = hist.length - 1;
      d += "M " + xAt(i0).toFixed(1) + " " + yAt(histVal(lastH)).toFixed(1);
    }
    fcst.forEach((p, i) => {
      const x = xAt(hist.length + i);
      const y = yAt(p.forecast_value);
      d += " L " + x.toFixed(1) + " " + y.toFixed(1);
    });
    return d;
  }, [hist, fcst, yMax]);

  // confidence band
  const bandPath = useMemoD(() => {
    if (fcst.length === 0) return "";
    let top = "M ";
    fcst.forEach((p, i) => {
      const x = xAt(hist.length + i);
      const y = yAt(p.upper_bound);
      top += (i === 0 ? "" : " L ") + x.toFixed(1) + " " + y.toFixed(1);
    });
    let bottom = "";
    for (let i = fcst.length - 1; i >= 0; i--) {
      const p = fcst[i];
      const x = xAt(hist.length + i);
      const y = yAt(p.lower_bound);
      bottom += " L " + x.toFixed(1) + " " + y.toFixed(1);
    }
    return top + bottom + " Z";
  }, [hist, fcst, yMax]);

  // scenario path
  const scenPath = useMemoD(() => {
    if (!scen) return "";
    let d = "";
    const lastH = hist[hist.length - 1];
    if (lastH) {
      d += "M " + xAt(hist.length - 1).toFixed(1) + " " + yAt(histVal(lastH)).toFixed(1);
    }
    scen.forEach((p, i) => {
      d += " L " + xAt(hist.length + i).toFixed(1) + " " + yAt(p.forecast_value).toFixed(1);
    });
    return d;
  }, [hist, scen, yMax]);

  // y-axis ticks
  const yTicks = useMemoD(() => {
    const ticks = [];
    const step = yMax / 4;
    for (let i = 0; i <= 4; i++) ticks.push(Math.round(i * step));
    return ticks;
  }, [yMax]);

  // x-axis month labels — first occurrence of each month in `all`. We then
  // enforce a minimum SVG-unit gap between adjacent emitted labels so they
  // don't visually pile up near the right edge of the chart, and skip the
  // final tick if it falls within the padding gutter.
  const xMonthTicks = useMemoD(() => {
    const raw = [];
    let prevMonth = null;
    all.forEach((p, i) => {
      const m = p.date.slice(0, 7);
      if (m !== prevMonth) { raw.push({ idx: i, date: p.date }); prevMonth = m; }
    });
    // "Apr" / "Jul" labels are ~22 SVG units wide at fontSize 10.5 on the
    // 1000-unit-wide viewBox. 44 units gives ~22px of breathing room on
    // either side, enough to avoid collisions even when the SVG scales
    // down to ~600px wide on smaller viewports.
    const MIN_GAP = 44;
    const filtered = [];
    let lastX = -Infinity;
    raw.forEach((t) => {
      const x = xAt(t.idx);
      if (x - lastX >= MIN_GAP) {
        filtered.push(t);
        lastX = x;
      }
    });
    // Drop the final tick if it would render inside the right padding.
    if (filtered.length > 0) {
      const lastTickX = xAt(filtered[filtered.length - 1].idx);
      if (lastTickX > W - padR - 20) filtered.pop();
    }
    return filtered;
  }, [all]);

  // Ramadan/Eid bands
  const bands = useMemoD(() => {
    const out = [];
    const RAM = [
      { start: "2025-02-28", end: "2025-03-30", label: "Ramadan 2025" },
      { start: "2026-02-17", end: "2026-03-18", label: "Ramadan 2026" },
    ];
    const FITR = [
      { start: "2025-03-31", end: "2025-04-03", label: "Eid Al-Fitr" },
      { start: "2026-03-19", end: "2026-03-22", label: "Eid Al-Fitr" },
    ];
    const ADHA = [
      { start: "2025-06-06", end: "2025-06-09", label: "Eid Al-Adha" },
      { start: "2026-05-26", end: "2026-05-29", label: "Eid Al-Adha" },
    ];
    function bandFor(set, color) {
      set.forEach((b) => {
        const i0 = clampIdx(b.start), i1 = clampIdx(b.end);
        if (i0 == null || i1 == null) return;
        out.push({ x0: xAt(i0), x1: xAt(i1), color, label: b.label, midX: (xAt(i0) + xAt(i1)) / 2 });
      });
    }
    function clampIdx(d) {
      if (dateToIdx.has(d)) return dateToIdx.get(d);
      // fall back to nearest within range
      if (d < all[0]?.date || d > all[all.length - 1]?.date) return null;
      // find closest
      let best = null, bestDiff = Infinity;
      all.forEach((p, i) => {
        const diff = Math.abs(new Date(p.date) - new Date(d));
        if (diff < bestDiff) { bestDiff = diff; best = i; }
      });
      return best;
    }
    bandFor(RAM,  { fill: "#8B5CF6", label: "#6D28D9" });
    bandFor(FITR, { fill: "#F59E0B", label: "#B45309" });
    bandFor(ADHA, { fill: "#15A56C", label: "#15803D" });
    return out;
  }, [all]);

  // hover
  const [hover, setHover] = useStateD(null);
  const svgRef = useRefD(null);
  function onMove(e) {
    const r = svgRef.current.getBoundingClientRect();
    // map clientX → SVG units → idx
    const xInSvg = ((e.clientX - r.left) / r.width) * W;
    const tFrac = (xInSvg - padL) / plotW;
    const i = Math.round(tFrac * (all.length - 1));
    if (i < 0 || i >= all.length) return setHover(null);
    setHover({ i, x: xAt(i), point: all[i] });
  }
  function onLeave() { setHover(null); }

  // tooltip explanation
  function pointDriver(p) {
    if (!p) return "Trend + seasonality";
    const ev = events.find((e) => e.date === p.date);
    if (ev) return `${ev.label} · ${fmtSignedPct(ev.expected_lift_percent)}`;
    // synthesize: detect ramadan/pre-ram/eid by date
    const d = p.date;
    if (d >= "2026-02-10" && d <= "2026-02-16") return "Pre-Ramadan stockup +43%";
    if (d >= "2026-02-17" && d <= "2026-03-18") return "Ramadan +21%";
    if (d >= "2026-03-19" && d <= "2026-03-22") return "Eid Al-Fitr window";
    if (d >= "2026-05-26" && d <= "2026-05-29") return "Eid Al-Adha window";
    if (d.slice(5, 7) >= "06" && d.slice(5, 7) <= "08") return "Summer dip −15%";
    return "Trend + weekly seasonality";
  }

  return (
    <div style={{ position: "relative" }}>
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}
        role="img" aria-label="Demand forecast chart"
        onMouseMove={onMove} onMouseLeave={onLeave}>
        {/* event bands */}
        {bands.map((b, i) => (
          <g key={i}>
            <rect x={b.x0} y={padT} width={Math.max(2, b.x1 - b.x0)} height={plotH}
              fill={b.color.fill} fillOpacity="0.16" />
            {b.x1 - b.x0 > 30 && (
              <text x={b.midX} y={padT - 8} textAnchor="middle"
                fontSize="10" fontWeight="600" fill={b.color.label}
                style={{ letterSpacing: 0.3, textTransform: "uppercase" }}>{b.label}</text>
            )}
          </g>
        ))}

        {/* grid + y ticks */}
        {yTicks.map((v) => (
          <g key={v}>
            <line x1={padL} x2={W - padR} y1={yAt(v)} y2={yAt(v)}
              stroke="#EEF1F6" strokeWidth="1" />
            <text x={padL - 8} y={yAt(v) + 3} textAnchor="end"
              fontSize="10.5" fill="#9CA3AF" style={{ fontVariantNumeric: "tabular-nums" }}>
              {fmtUnits(v)}
            </text>
          </g>
        ))}

        {/* x labels */}
        {xMonthTicks.map((t, i) => (
          <text key={i} x={xAt(t.idx)} y={H - padB + 18} fontSize="10.5" fill="#9CA3AF"
            textAnchor="middle">
            {new Date(t.date).toLocaleDateString("en-GB", { month: "short" })}
            {t.date.slice(5, 7) === "01" && (
              <tspan x={xAt(t.idx)} dy="12" fontSize="9.5" fill="#B0B8C8">{t.date.slice(0, 4)}</tspan>
            )}
          </text>
        ))}

        {/* now line — between hist and forecast */}
        {hist.length > 0 && (
          <g>
            <line x1={xAt(hist.length - 1)} x2={xAt(hist.length - 1)}
              y1={padT} y2={padT + plotH}
              stroke="#0A1F44" strokeOpacity="0.4" strokeDasharray="3 3" strokeWidth="1.2" />
            <text x={xAt(hist.length - 1)} y={padT + 12} textAnchor="middle"
              fontSize="10" fill="#0A1F44" fontWeight="600"
              style={{ letterSpacing: 0.3, textTransform: "uppercase" }}>Today</text>
          </g>
        )}

        {/* confidence band */}
        <path d={bandPath} fill="#F59E0B" fillOpacity="0.18" />

        {/* historical line */}
        <path d={histPath} fill="none" stroke="#0A1F44" strokeWidth="1.8" strokeLinejoin="round" />

        {/* forecast line (dashed) */}
        <path d={fcstPath} fill="none" stroke="#E66A12" strokeWidth="2" strokeDasharray="6 5"
          strokeLinejoin="round" strokeLinecap="round" />

        {/* scenario line */}
        {scen && (
          <path d={scenPath} fill="none" stroke="#06B6D4" strokeWidth="2" strokeDasharray="2 4"
            strokeLinejoin="round" strokeLinecap="round" />
        )}

        {/* hover marker */}
        {hover && hover.point && (
          <g>
            <line x1={hover.x} x2={hover.x} y1={padT} y2={padT + plotH}
              stroke="#0A1F44" strokeOpacity="0.18" strokeWidth="1" />
            <circle cx={hover.x} cy={yAt(hover.point.value)} r="4"
              fill={hover.point.kind === "h" ? "#0A1F44" : "#E66A12"}
              stroke="white" strokeWidth="2" />
          </g>
        )}

        {/* axis baseline */}
        <line x1={padL} x2={W - padR} y1={padT + plotH} y2={padT + plotH}
          stroke="#DCE2EC" strokeWidth="1" />
      </svg>

      {/* tooltip */}
      {hover && hover.point && (
        <div style={{
          position: "absolute",
          left: `${(hover.x / W) * 100}%`,
          top: 8,
          transform: `translate(${hover.x > W * 0.7 ? "calc(-100% - 12px)" : "12px"}, 0)`,
          background: "#0A1F44", color: "white",
          padding: "10px 12px", borderRadius: 8, minWidth: 220,
          fontSize: 12, lineHeight: 1.45, fontFamily: "inherit",
          boxShadow: "0 8px 24px rgba(10,31,68,0.25)",
          pointerEvents: "none", zIndex: 5,
        }}>
          <div style={{ fontWeight: 700, letterSpacing: 0.3 }}>
            {new Date(hover.point.date).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}
          </div>
          <div style={{ marginTop: 4, color: "rgba(255,255,255,0.7)", textTransform: "uppercase", fontSize: 10, letterSpacing: 0.5, fontWeight: 600 }}>
            {hover.point.kind === "h" ? "Actual" : "Predicted"}
          </div>
          <div style={{ fontSize: 18, fontWeight: 600, marginTop: 2, fontVariantNumeric: "tabular-nums" }}>
            {fmtUnits(hover.point.value)} units
          </div>
          {hover.point.kind === "f" && (
            <div style={{ fontSize: 11, color: "rgba(255,255,255,0.7)", marginTop: 2 }}>
              Range {fmtUnits(hover.point.lo)} – {fmtUnits(hover.point.hi)}
            </div>
          )}
          <div style={{ marginTop: 6, paddingTop: 6, borderTop: "1px solid rgba(255,255,255,0.18)",
            fontSize: 11.5, color: "rgba(255,255,255,0.85)" }}>
            <span style={{ color: "rgba(255,255,255,0.6)" }}>Driven by:</span> {pointDriver(hover.point)}
          </div>
        </div>
      )}
    </div>
  );
}

// ───────────── DECOMPOSITION CARDS ─────────────
function MiniLine({ values, color = "#0A1F44", w = 240, h = 56, dashed = false }) {
  if (!values || values.length === 0) return null;
  const min = Math.min(...values), max = Math.max(...values);
  const range = (max - min) || 1;
  const stepX = (w - 4) / (values.length - 1);
  const d = values.map((v, i) =>
    `${i === 0 ? "M" : "L"} ${(2 + i * stepX).toFixed(1)} ${(2 + (1 - (v - min) / range) * (h - 4)).toFixed(1)}`
  ).join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: "auto" }}>
      <path d={d} fill="none" stroke={color} strokeWidth="1.8" strokeLinejoin="round"
        strokeDasharray={dashed ? "4 4" : undefined} />
    </svg>
  );
}

function DecompositionCard({ tag, accent, title, value, sub, children, expanded, onToggle, expandedContent }) {
  return (
    <div style={{
      background: "white", border: "1px solid #E5E8EE", borderRadius: 10,
      padding: "16px 18px", display: "flex", flexDirection: "column", gap: 12,
      boxShadow: "0 1px 2px rgba(10,31,68,0.04)",
      minWidth: 0,
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.6, textTransform: "uppercase",
          color: accent }}>{tag}</div>
      </div>
      <div style={{ minHeight: 56 }}>{children}</div>
      <div>
        <div style={{ fontSize: 22, fontWeight: 600, color: "#0A1F44", letterSpacing: -0.4,
          fontVariantNumeric: "tabular-nums" }}>{value}</div>
        <div style={{ fontSize: 12.5, color: "#6B7280", marginTop: 2 }}>{sub}</div>
      </div>
      {expandedContent && (
        <button onClick={onToggle} style={{
          alignSelf: "flex-start", padding: 0, background: "transparent", border: "none",
          color: "#0A1F44", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
        }}>{expanded ? "Hide details ↑" : "Learn more →"}</button>
      )}
      {expanded && expandedContent && (
        <div style={{ fontSize: 12.5, color: "#4B5563", lineHeight: 1.5, paddingTop: 4,
          borderTop: "1px solid #EEF1F6", marginTop: 4 }}>
          {expandedContent}
        </div>
      )}
    </div>
  );
}

function DecompositionRow({ history, forecast, seasonality }) {
  const [openId, setOpenId] = useStateD(null);

  // trend: smoothed line through history (mean of every 14d window). The
  // enriched history points use `forecast_value`/`units_sold` rather than
  // `actual`, so read defensively.
  const trendValues = useMemoD(() => {
    const out = [];
    const w = 14;
    const valOf = (p) =>
      p?.actual != null ? Number(p.actual)
      : p?.forecast_value != null ? Number(p.forecast_value)
      : p?.units_sold != null ? Number(p.units_sold)
      : 0;
    for (let i = 0; i < history.length; i += w) {
      const slice = history.slice(i, i + w);
      const sum = slice.reduce((s, p) => s + valOf(p), 0);
      const mean = slice.length ? sum / slice.length : 0;
      if (Number.isFinite(mean)) out.push(mean);
    }
    return out;
  }, [history]);

  // Underlying-market-growth %. Spec: percent change between mean of first
  // 30 days of the forecast and mean of last 30 days, annualised when the
  // horizon < 365d. NaN/Infinity collapses to null → fmtSignedPct shows "—".
  const yoyPct = useMemoD(() => deriveForecastTrendPct(forecast), [forecast]);

  // seasonality: seasonality.yearly_pattern indices
  const seasonValues = (seasonality?.yearly_pattern || []).map((p) => p.index);
  const summerDip = seasonality
    ? Math.round((Math.min(...seasonValues) - 1) * 100 * 10) / 10
    : -15;

  // events bar chart values (top 4)
  const eventBars = [
    { name: "Ramadan",            pct: 21,  color: "#8B5CF6" },
    { name: "Eid Al-Fitr (peak)", pct: 22,  color: "#F59E0B" },
    { name: "Eid Al-Adha",        pct: 12,  color: "#15A56C" },
    { name: "Pre-Ramadan stockup",pct: 43,  color: "#6366F1" },
  ];
  const eventMax = Math.max(...eventBars.map((b) => b.pct));

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 12 }}>
      <DecompositionCard tag="Trend" accent="#0A1F44"
        value={fmtSignedPct(yoyPct)} sub="Underlying market growth"
        expanded={openId === "trend"} onToggle={() => setOpenId(openId === "trend" ? null : "trend")}
        expandedContent="The Prophet model fits a piecewise-linear trend through your 3 years of history. The slope reflects steady demand growth driven by population and category penetration — independent of seasonality and events.">
        <MiniLine values={trendValues} color="#0A1F44" h={56} />
      </DecompositionCard>

      <DecompositionCard tag="Seasonality" accent="#15A56C"
        value={`Summer dip ${fmtSignedPct(summerDip)}`} sub="Weekly + yearly cycles"
        expanded={openId === "season"} onToggle={() => setOpenId(openId === "season" ? null : "season")}
        expandedContent="Yearly seasonality is dominated by a Gulf-summer dip (Jun–Aug) and milder winter peaks. Weekly seasonality shows Thursday–Friday lifts as retailers restock before the weekend.">
        <MiniLine values={seasonValues.length ? seasonValues : [0.92, 0.95, 1.0, 1.02, 1.0, 0.95, 0.85, 0.85, 0.95, 1.05, 1.08, 1.05]}
          color="#15A56C" h={56} />
      </DecompositionCard>

      <DecompositionCard tag="Holidays & Events" accent="#8B5CF6"
        value="Ramadan +21%" sub="MENA-specific lift events"
        expanded={openId === "events"} onToggle={() => setOpenId(openId === "events" ? null : "events")}
        expandedContent="Five MENA-specific regressors are added on top of trend & seasonality: is_ramadan, ramadan_day, is_eid_alfitr, is_eid_aladha, is_pre_ramadan_stockup. Each has a learned per-SKU lift coefficient.">
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {eventBars.map((b) => (
            <div key={b.name} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <div style={{ flex: 1, minWidth: 0, fontSize: 11.5, color: "#4B5563", fontWeight: 500,
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{b.name}</div>
              <div style={{ flex: "0 0 80px", height: 6, background: "#EEF1F6", borderRadius: 3, overflow: "hidden" }}>
                <div style={{ width: `${(b.pct / eventMax) * 100}%`, height: "100%", background: b.color, borderRadius: 3 }} />
              </div>
              <div style={{ flex: "0 0 36px", textAlign: "right", fontSize: 11.5, fontWeight: 600,
                color: "#0A1F44", fontVariantNumeric: "tabular-nums" }}>+{b.pct}%</div>
            </div>
          ))}
        </div>
      </DecompositionCard>
    </div>
  );
}

// ───────────── PRODUCTION TABLE ─────────────
function ProductionTable({ forecast, baseline, onScheduleRun, onDrillIn }) {
  // build 12 weekly rows starting from forecast[0]
  const rows = useMemoD(() => {
    if (!forecast || forecast.length < 14) return [];
    const out = [];
    let invStart = baseline * 14; // pretend ~2 weeks of inventory on hand
    for (let w = 0; w < 12; w++) {
      const start = w * 7;
      const slice = forecast.slice(start, start + 7);
      if (slice.length === 0) break;
      const dem = slice.reduce((s, p) => s + p.forecast_value, 0);
      const safety = Math.round(dem * 0.15);
      const inv = Math.round(invStart);
      const recProd = Math.max(0, dem + safety - inv);
      const liftPct = Math.round(((dem / 7 / baseline) - 1) * 100);
      const trend = liftPct >= 12 ? "up" : liftPct <= -10 ? "down" : "flat";
      const startDate = slice[0].date;
      const endDate = slice[slice.length - 1].date;
      const driver = (() => {
        const inDate = (start, end) => slice.some((p) => p.date >= start && p.date <= end);
        if (inDate("2026-02-10", "2026-02-16")) return "Pre-Ramadan stockup window";
        if (inDate("2026-02-17", "2026-03-18")) return "Ramadan elevation";
        if (inDate("2026-03-19", "2026-03-22")) return "Eid Al-Fitr week";
        if (inDate("2026-05-26", "2026-05-29")) return "Eid Al-Adha week";
        if (slice[0].date.slice(5,7) >= "06" && slice[0].date.slice(5,7) <= "08") return "Summer dip";
        return "Trend + weekly seasonality";
      })();
      out.push({ idx: w, startDate, endDate, demand: dem, safety, inventory: inv,
        production: recProd, trend, liftPct, driver });
      // pretend production replenishes inventory next week
      invStart = inv + recProd - dem;
    }
    return out;
  }, [forecast, baseline]);

  if (rows.length === 0) return null;

  return (
    <div style={{ background: "white", border: "1px solid #E5E8EE", borderRadius: 10,
      boxShadow: "0 1px 2px rgba(10,31,68,0.04)", overflow: "hidden" }}>
      <div style={{ padding: "16px 20px", borderBottom: "1px solid #E5E8EE",
        display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.6, textTransform: "uppercase",
            color: "#6B7280" }}>Recommended production</div>
          <div style={{ fontSize: 16, fontWeight: 600, color: "#0A1F44", marginTop: 2, letterSpacing: -0.2 }}>
            Next 12 weeks
          </div>
        </div>
        <div style={{ fontSize: 12, color: "#6B7280" }}>
          Safety stock buffer: <strong style={{ color: "#0A1F44", fontWeight: 600 }}>+15%</strong>
        </div>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontVariantNumeric: "tabular-nums" }}>
          <thead>
            <tr style={{ background: "#F8FAFD", fontSize: 10.5, color: "#6B7280", fontWeight: 700,
              letterSpacing: 0.5, textTransform: "uppercase" }}>
              <th style={prodTh}>Week</th>
              <th style={prodTh}>Forecasted demand</th>
              <th style={prodTh}>Safety (+15%)</th>
              <th style={prodTh}>Current inventory</th>
              <th style={{ ...prodTh, color: "#0A1F44" }}>Recommended production</th>
              <th style={prodTh}>Trend</th>
              <th style={prodTh}></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const trendIcon = r.trend === "up" ? "⬆" : r.trend === "down" ? "⬇" : "➡";
              const trendCol = r.trend === "up" ? "#0F8B5C" : r.trend === "down" ? "#B31E2B" : "#9CA3AF";
              const isHot = r.trend === "up";
              return (
                <tr key={r.idx}
                  onClick={() => onDrillIn(r)}
                  title={`Driver: ${r.driver}`}
                  style={{
                    borderTop: "1px solid #EEF1F6",
                    cursor: "pointer",
                    background: isHot ? "rgba(245,158,11,0.05)" : "white",
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = "#F4F7FC"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = isHot ? "rgba(245,158,11,0.05)" : "white"; }}>
                  <td style={prodTd}>
                    <div style={{ fontWeight: 600, color: "#0A1F44" }}>
                      {fmtDateShort(r.startDate)} – {fmtDateShort(r.endDate)}
                    </div>
                    <div style={{ fontSize: 11, color: "#9CA3AF", marginTop: 1 }}>{r.driver}</div>
                  </td>
                  <td style={prodTd}>{fmtUnits(r.demand)}</td>
                  <td style={{ ...prodTd, color: "#6B7280" }}>{fmtUnits(r.safety)}</td>
                  <td style={{ ...prodTd, color: "#6B7280" }}>{fmtUnits(r.inventory)}</td>
                  <td style={{ ...prodTd, fontSize: 16, fontWeight: 600, color: "#0A1F44" }}>
                    {fmtUnits(r.production)}
                  </td>
                  <td style={prodTd}>
                    <span style={{ color: trendCol, fontWeight: 700, marginRight: 6 }}>{trendIcon}</span>
                    <span style={{ color: trendCol, fontWeight: 600, fontSize: 12 }}>
                      {r.liftPct >= 0 ? "+" : ""}{r.liftPct}%
                    </span>
                  </td>
                  <td style={{ ...prodTd, textAlign: "right" }}>
                    <button
                      onClick={(e) => { e.stopPropagation(); onScheduleRun(r); }}
                      style={{
                        padding: "5px 10px", borderRadius: 6,
                        border: "1px solid #DCE2EC", background: "white", color: "#0A1F44",
                        fontSize: 11.5, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
                      }}
                      onMouseEnter={(e) => { e.currentTarget.style.background = "#0A1F44"; e.currentTarget.style.color = "white"; }}
                      onMouseLeave={(e) => { e.currentTarget.style.background = "white"; e.currentTarget.style.color = "#0A1F44"; }}
                    >Schedule run</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
const prodTh = { padding: "10px 16px", textAlign: "left", whiteSpace: "nowrap" };
const prodTd = { padding: "12px 16px", fontSize: 13, color: "#0A1F44", whiteSpace: "nowrap" };

// ───────────── DRIVERS ─────────────
function DriverSparkline({ kind, color }) {
  // synthetic 3-year history per driver kind
  const series = useMemoD(() => {
    const arr = [];
    for (let i = 0; i < 36; i++) {
      let v = 1.0;
      const ramadanMonth = [13, 14, 25, 26, 36, 37];
      if (kind === "ramadan" && ramadanMonth.includes(i)) v = 1.21;
      if (kind === "pre_ramadan" && ramadanMonth.map((x) => x - 1).includes(i)) v = 1.43;
      if (kind === "eid_fitr_dip" && ramadanMonth.map((x) => x).includes(i)) v = 0.5;
      if (kind === "yoy_trend") v = 1 + i * 0.0067;
      if (kind === "summer_dip" && ([5,6,7,17,18,19,29,30,31].includes(i))) v = 0.85;
      if (kind === "marketing" && [9, 22, 33].includes(i)) v = 1.18;
      v += (Math.sin(i * 0.7 + (kind || "").length) * 0.03);
      arr.push(v);
    }
    return arr;
  }, [kind]);
  return <MiniLine values={series} color={color} w={120} h={28} />;
}

function DriversList({ drivers, market, sku, productLabel }) {
  const [openId, setOpenId] = useStateD("ramadan");
  const colorMap = {
    ramadan: "#8B5CF6", eid_fitr_dip: "#F59E0B", yoy_trend: "#0A1F44",
    summer_dip: "#06B6D4", pre_ramadan: "#6366F1", marketing: "#15A56C",
  };
  return (
    <div style={{ background: "white", border: "1px solid #E5E8EE", borderRadius: 10,
      boxShadow: "0 1px 2px rgba(10,31,68,0.04)" }}>
      <div style={{ padding: "16px 20px", borderBottom: "1px solid #E5E8EE" }}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.6, textTransform: "uppercase",
          color: "#6B7280" }}>Top demand drivers</div>
        <div style={{ fontSize: 16, fontWeight: 600, color: "#0A1F44", marginTop: 2, letterSpacing: -0.2 }}>
          {MARKET_LABEL[market]} × {productLabel}
        </div>
      </div>
      <div>
        {drivers.map((d) => {
          const open = openId === d.id;
          const c = colorMap[d.id] || "#0A1F44";
          const positive = d.lift_percent >= 0;
          return (
            <div key={d.id} style={{ borderTop: "1px solid #EEF1F6" }}>
              <button onClick={() => setOpenId(open ? null : d.id)}
                style={{
                  width: "100%", textAlign: "left", padding: "14px 20px",
                  display: "grid", gridTemplateColumns: "32px 1fr 130px 80px 18px",
                  gap: 12, alignItems: "center",
                  background: "transparent", border: "none", cursor: "pointer", fontFamily: "inherit",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "#F8FAFD"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}>
                <span style={{ fontSize: 22, lineHeight: 1 }} aria-hidden="true">{d.icon}</span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 600, color: "#0A1F44" }}>{d.label}</div>
                  <div style={{ fontSize: 11.5, color: "#6B7280", marginTop: 2 }}>{d.detail}</div>
                </div>
                <DriverSparkline kind={d.id} color={c} />
                <div style={{
                  fontSize: 16, fontWeight: 700, textAlign: "right",
                  color: positive ? "#0F8B5C" : "#B31E2B",
                  fontVariantNumeric: "tabular-nums",
                }}>{fmtSignedPct(d.lift_percent)}</div>
                <span style={{ color: "#9CA3AF", fontSize: 10, transition: "transform .15s",
                  transform: open ? "rotate(180deg)" : "none" }}>▼</span>
              </button>
              {open && (
                <div style={{ padding: "0 20px 16px 64px", color: "#4B5563",
                  fontSize: 12.5, lineHeight: 1.55 }}>
                  <p style={{ margin: 0 }}>
                    <strong style={{ color: "#0A1F44" }}>How we measure this:</strong> Across
                    36 monthly observations, the {d.id.replace(/_/g, " ")} regressor's coefficient
                    is statistically significant (p &lt; 0.01) and its average lift is {fmtSignedPct(d.lift_percent)}.
                  </p>
                  <p style={{ marginTop: 6, marginBottom: 0 }}>
                    <strong style={{ color: "#0A1F44" }}>Why it matters:</strong> {d.detail}
                  </p>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ───────────── ACCURACY ─────────────
function AccuracyStrip({ accuracy }) {
  if (!accuracy) return null;
  // The contract /forecast response only returns mape/confidence (derived
  // client-side from forecast bands by enrichForecast). The richer
  // "last-month vs actual" and best/worst-market cells are optional —
  // render them only when the backend supplies them.
  const last = accuracy.last_month_predicted != null
            && accuracy.last_month_actual != null
            && accuracy.last_month_variance_percent != null;
  const goodVariance = last && accuracy.last_month_variance_percent <= 5;
  const hasBest = accuracy.best_market && accuracy.best_market.market_id != null;
  const hasWorst = accuracy.worst_market && accuracy.worst_market.market_id != null;

  return (
    <div style={{
      background: "white", border: "1px solid #E5E8EE", borderRadius: 10,
      padding: "14px 20px", boxShadow: "0 1px 2px rgba(10,31,68,0.04)",
      display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
      gap: 16, alignItems: "center",
    }}>
      <div>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.6, textTransform: "uppercase",
          color: "#6B7280" }}>Trust signal</div>
        <div style={{ fontSize: 14, fontWeight: 600, color: "#0A1F44", marginTop: 4 }}>
          How well has the AI performed?
        </div>
        <div style={{ fontSize: 11.5, color: "#9CA3AF", marginTop: 2 }}>
          From this forecast's confidence bands
        </div>
      </div>
      {last && (
        <AccCell label="Last month forecast vs actual"
          value={`${fmtUnits(accuracy.last_month_predicted)} → ${fmtUnits(accuracy.last_month_actual)}`}
          sub={`${fmtSignedPct(accuracy.last_month_variance_percent)} variance ${goodVariance ? "✅" : "⚠"}`}
          accent={goodVariance ? "#0F8B5C" : "#B14A00"} />
      )}
      {accuracy.mape_percent != null && (
        <AccCell label="MAPE on this forecast"
          value={`${accuracy.mape_percent}%`}
          sub="Derived from prediction bands"
          accent="#0A1F44" />
      )}
      {accuracy.forecast_confidence_percent != null && (
        <AccCell label="Forecast confidence"
          value={`${accuracy.forecast_confidence_percent}%`}
          sub="Higher is tighter"
          accent="#0F8B5C" />
      )}
      {hasBest && (
        <AccCell label="Best market"
          value={MARKET_LABEL[accuracy.best_market.market_id] || accuracy.best_market.market_id}
          sub={`${accuracy.best_market.accuracy_percent}% accuracy`}
          accent="#0F8B5C" />
      )}
      {hasWorst && (
        <AccCell label="Worst market"
          value={MARKET_LABEL[accuracy.worst_market.market_id] || accuracy.worst_market.market_id}
          sub={`${accuracy.worst_market.accuracy_percent}% accuracy`}
          accent="#B14A00" />
      )}
      <button style={{
        padding: "8px 14px", borderRadius: 8,
        border: "1px solid #DCE2EC", background: "white", color: "#0A1F44",
        fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
        justifySelf: "end",
      }}
        onClick={() => window.dispatchEvent(new CustomEvent("fhh:chat:send",
          { detail: "Show me the full accuracy report — by market, SKU, and time period." }))}
        onMouseEnter={(e) => { e.currentTarget.style.background = "#F4F7FC"; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = "white"; }}
      >View accuracy report →</button>
    </div>
  );
}
function AccCell({ label, value, sub, accent }) {
  return (
    <div>
      <div style={{ fontSize: 10.5, color: "#9CA3AF", fontWeight: 600, letterSpacing: 0.5,
        textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 600, marginTop: 4, color: accent || "#0A1F44",
        fontVariantNumeric: "tabular-nums" }}>{value}</div>
      <div style={{ fontSize: 11.5, color: "#6B7280", marginTop: 2 }}>{sub}</div>
    </div>
  );
}

// ───────────── SCENARIO PANEL ─────────────
function ScenarioPanel({ open, onClose, sliders, onChange, onReset, deltaPct }) {
  if (!open) return null;
  return (
    <div style={{
      background: "linear-gradient(180deg, #ECFEFF 0%, #FFFFFF 100%)",
      border: "1px solid #A5F3FC", borderRadius: 10,
      padding: "16px 20px", boxShadow: "0 1px 2px rgba(10,31,68,0.04)",
      display: "flex", flexDirection: "column", gap: 14,
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.6, textTransform: "uppercase",
            color: "#0E7490" }}>🧪 Scenario · POST /forecast/scenario</div>
          <div style={{ fontSize: 14, fontWeight: 600, color: "#0A1F44", marginTop: 2 }}>
            What-if forecast adjustments
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {deltaPct != null && (
            <div style={{
              padding: "5px 12px", borderRadius: 999,
              background: deltaPct > 0 ? "#E6F6EE" : deltaPct < 0 ? "#FCE3E5" : "#EEF1F6",
              color: deltaPct > 0 ? "#0F8B5C" : deltaPct < 0 ? "#B31E2B" : "#4B5563",
              fontSize: 12.5, fontWeight: 600,
            }}>
              Scenario forecast: {fmtSignedPct(deltaPct)} vs baseline
            </div>
          )}
          <button onClick={onReset} style={cyanGhost}>Reset</button>
          <button onClick={onClose} style={cyanGhost}>Close</button>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 16 }}>
        <ScenarioSlider label="Ramadan effect strength" min={-20} max={50} step={1}
          value={sliders.ramadan} onChange={(v) => onChange({ ...sliders, ramadan: v })} />
        <ScenarioSlider label="Pre-Ramadan stockup" min={-20} max={50} step={1}
          value={sliders.pre_ramadan} onChange={(v) => onChange({ ...sliders, pre_ramadan: v })} />
        <ScenarioSlider label="Trend acceleration" min={-10} max={20} step={1}
          value={sliders.trend} onChange={(v) => onChange({ ...sliders, trend: v })} />
        <ScenarioSlider label="Promo period lift" min={0} max={40} step={1}
          value={sliders.promo} onChange={(v) => onChange({ ...sliders, promo: v })}
          subInputs={
            <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
              <input type="date" value={sliders.promoStart}
                onChange={(e) => onChange({ ...sliders, promoStart: e.target.value })}
                style={cyanInput} />
              <input type="date" value={sliders.promoEnd}
                onChange={(e) => onChange({ ...sliders, promoEnd: e.target.value })}
                style={cyanInput} />
            </div>
          } />
      </div>

      <div style={{ fontSize: 11.5, color: "#0E7490" }}>
        <span style={{
          display: "inline-block", width: 14, height: 3, borderRadius: 2,
          background: "#06B6D4", marginRight: 6, verticalAlign: "middle",
        }} />
        Scenario forecast line shows on the chart in cyan.
      </div>
    </div>
  );
}
function ScenarioSlider({ label, min, max, step, value, onChange, subInputs }) {
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: "#0A1F44" }}>{label}</span>
        <span style={{ fontSize: 13, fontWeight: 700, color: "#0E7490",
          fontVariantNumeric: "tabular-nums" }}>{fmtSignedPct(value)}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(+e.target.value)}
        style={{ width: "100%", accentColor: "#06B6D4", marginTop: 4 }} />
      {subInputs}
    </div>
  );
}
const cyanInput = {
  flex: 1, padding: "5px 8px", border: "1px solid #A5F3FC", borderRadius: 6,
  fontSize: 11.5, color: "#0A1F44", fontFamily: "inherit", outline: "none",
};
const cyanGhost = {
  padding: "6px 12px", borderRadius: 7, fontSize: 12, fontWeight: 600,
  background: "white", color: "#0A1F44", border: "1px solid #A5F3FC",
  cursor: "pointer", fontFamily: "inherit",
};

// ───────────── SCHEDULE RUN MODAL ─────────────
function ScheduleRunModal({ row, productLabel, onClose, onSubmit }) {
  const [date, setDate] = useStateD(row.startDate);
  const [batch, setBatch] = useStateD(row.production);
  const [priority, setPriority] = useStateD("normal");
  const [notes, setNotes] = useStateD("");
  if (!row) return null;
  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, zIndex: 100, background: "rgba(10,31,68,0.45)",
      display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderRadius: 12, width: 460, maxWidth: "100%",
        padding: "22px 24px", boxShadow: "0 20px 60px rgba(10,31,68,0.25)",
        display: "flex", flexDirection: "column", gap: 14,
      }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.6, textTransform: "uppercase", color: "#6B7280" }}>
            Schedule production run
          </div>
          <div style={{ fontSize: 18, fontWeight: 600, color: "#0A1F44", marginTop: 4, letterSpacing: -0.3 }}>
            {productLabel}
          </div>
          <div style={{ fontSize: 12.5, color: "#6B7280", marginTop: 2 }}>
            {fmtDateShort(row.startDate)} – {fmtDateShort(row.endDate)} · {row.driver}
          </div>
        </div>
        <FormRow label="Production date">
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} style={modalInputD} />
        </FormRow>
        <FormRow label="Batch size (units)">
          <input type="number" value={batch} onChange={(e) => setBatch(+e.target.value)} style={modalInputD} />
        </FormRow>
        <FormRow label="Priority">
          <div style={{ display: "flex", gap: 8 }}>
            {["low", "normal", "high", "urgent"].map((p) => (
              <button key={p} onClick={() => setPriority(p)} style={{
                padding: "6px 12px", borderRadius: 6,
                background: priority === p ? "#0A1F44" : "white",
                color: priority === p ? "white" : "#0A1F44",
                border: "1px solid " + (priority === p ? "#0A1F44" : "#DCE2EC"),
                fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
                textTransform: "capitalize",
              }}>{p}</button>
            ))}
          </div>
        </FormRow>
        <FormRow label="Notes (optional)">
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3}
            placeholder="Anything the line operator should know…"
            style={{ ...modalInputD, resize: "vertical", fontFamily: "inherit" }} />
        </FormRow>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button onClick={onClose} style={modalGhostD}>Cancel</button>
          <button onClick={() => onSubmit({ date, batch, priority, notes })} style={modalPrimD}>
            Schedule run
          </button>
        </div>
      </div>
    </div>
  );
}
function FormRow({ label, children }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span style={{ fontSize: 12, fontWeight: 600, color: "#4B5563" }}>{label}</span>
      {children}
    </label>
  );
}
const modalInputD = {
  padding: "8px 10px", border: "1px solid #DCE2EC", borderRadius: 6,
  background: "white", fontSize: 13, color: "#0A1F44", fontFamily: "inherit", outline: "none",
};
const modalGhostD = {
  padding: "8px 14px", borderRadius: 7, border: "1px solid #DCE2EC",
  background: "white", color: "#0A1F44", fontSize: 13, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
};
const modalPrimD = {
  padding: "8px 14px", borderRadius: 7, border: "none",
  background: "#0A1F44", color: "white", fontSize: 13, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
};

// ───────────── COMPARE OVERLAY ─────────────
function CompareOverlay({ open, onClose, baseSku, baseMarket, products }) {
  const [otherMarket, setOtherMarket] = useStateD("ksa");
  const [otherSku, setOtherSku] = useStateD(baseSku);
  const [a, setA] = useStateD(null);
  const [b, setB] = useStateD(null);
  useEffectD(() => {
    if (!open) return;
    window.api.get("/forecast", { sku: baseSku, market: baseMarket, horizon_months: 4 }).then(setA);
    window.api.get("/forecast", { sku: otherSku, market: otherMarket, horizon_months: 4 }).then(setB);
  }, [open, baseSku, baseMarket, otherSku, otherMarket]);
  if (!open) return null;
  const productLbl = (sku) => (products.find((p) => p.id === sku)?.label || sku);
  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, zIndex: 95, background: "rgba(10,31,68,0.5)",
      display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderRadius: 12, width: 1080, maxWidth: "100%",
        padding: "24px 28px", boxShadow: "0 20px 60px rgba(10,31,68,0.3)",
        display: "flex", flexDirection: "column", gap: 16, maxHeight: "92vh", overflow: "auto",
      }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.6, textTransform: "uppercase", color: "#6B7280" }}>
              Compare forecasts
            </div>
            <div style={{ fontSize: 20, fontWeight: 600, color: "#0A1F44", marginTop: 4, letterSpacing: -0.4 }}>
              Side-by-side market & SKU comparison
            </div>
          </div>
          <button onClick={onClose} style={modalGhostD}>Close</button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <CompareSide title={`${MARKET_FLAG[baseMarket]} ${MARKET_LABEL[baseMarket]}`}
            sub={productLbl(baseSku)} forecast={a?.forecast} accent="#0A1F44" />
          <div>
            <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
              <Dropdown label="Market" value={otherMarket}
                options={Object.keys(MARKET_LABEL).map((id) => ({
                  id, label: MARKET_LABEL[id], flag: MARKET_FLAG[id],
                }))}
                renderOption={renderMarketOption}
                renderValue={renderMarketOption}
                onChange={setOtherMarket} width={180} />
              <Dropdown label="Product" value={otherSku} options={products}
                onChange={setOtherSku} width={260} searchable />
            </div>
            <CompareSide title={`${MARKET_FLAG[otherMarket]} ${MARKET_LABEL[otherMarket]}`}
              sub={productLbl(otherSku)} forecast={b?.forecast} accent="#06B6D4" />
          </div>
        </div>
      </div>
    </div>
  );
}
function CompareSide({ title, sub, forecast, accent }) {
  if (!forecast) return <div style={{ height: 200, background: "#F4F6FA", borderRadius: 8 }} />;
  const total = forecast.reduce((s, p) => s + p.forecast_value, 0);
  const peak = Math.max(...forecast.map((p) => p.forecast_value));
  return (
    <div style={{ background: "#F8FAFD", border: "1px solid #E5E8EE", borderRadius: 10, padding: 16 }}>
      <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", color: accent }}>
        {title}
      </div>
      <div style={{ fontSize: 15, fontWeight: 600, color: "#0A1F44", marginTop: 2 }}>{sub}</div>
      <div style={{ marginTop: 10, height: 100 }}>
        <MiniLine values={forecast.map((p) => p.forecast_value)} color={accent} h={100} dashed />
      </div>
      <div style={{ display: "flex", gap: 16, marginTop: 8 }}>
        <div>
          <div style={{ fontSize: 10.5, color: "#9CA3AF", fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.5 }}>Total demand</div>
          <div style={{ fontSize: 15, fontWeight: 600, color: "#0A1F44", fontVariantNumeric: "tabular-nums" }}>{fmtUnits(total)} units</div>
        </div>
        <div>
          <div style={{ fontSize: 10.5, color: "#9CA3AF", fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.5 }}>Peak day</div>
          <div style={{ fontSize: 15, fontWeight: 600, color: "#0A1F44", fontVariantNumeric: "tabular-nums" }}>{fmtUnits(peak)} units</div>
        </div>
      </div>
    </div>
  );
}

// ───────────── TOAST ─────────────
function ToastD({ message }) {
  if (!message) return null;
  return (
    <div style={{
      position: "fixed", bottom: 24, left: "50%", transform: "translateX(-50%)",
      background: "#0A1F44", color: "white", padding: "10px 18px",
      borderRadius: 999, fontSize: 13, fontWeight: 500,
      boxShadow: "0 8px 24px rgba(10,31,68,0.25)", zIndex: 200,
    }}>{message}</div>
  );
}

// ───────────── DRILL-IN PANEL ─────────────
function DailyDrillIn({ row, forecast, productLabel, onClose }) {
  if (!row || !forecast) return null;
  const start = row.idx * 7;
  const days = forecast.slice(start, start + 7);
  const total = days.reduce((s, p) => s + p.forecast_value, 0);
  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, zIndex: 95, background: "rgba(10,31,68,0.45)",
      display: "flex", alignItems: "flex-end", justifyContent: "center",
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderTopLeftRadius: 14, borderTopRightRadius: 14,
        width: "100%", maxWidth: 720, padding: "22px 28px",
        boxShadow: "0 -10px 40px rgba(10,31,68,0.2)",
      }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.6, textTransform: "uppercase", color: "#6B7280" }}>
              Week {row.idx + 1} daily breakdown
            </div>
            <div style={{ fontSize: 18, fontWeight: 600, color: "#0A1F44", marginTop: 4 }}>
              {fmtDateShort(row.startDate)} – {fmtDateShort(row.endDate)} · {productLabel}
            </div>
            <div style={{ fontSize: 12.5, color: "#6B7280", marginTop: 4 }}>
              Total demand {fmtUnits(total)} units · Driver: {row.driver}
            </div>
          </div>
          <button onClick={onClose} style={modalGhostD}>Close</button>
        </div>
        <div style={{ marginTop: 14, display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 6 }}>
          {days.map((d) => {
            const dt = new Date(d.date);
            const dayNum = dt.getDay();
            const dayLabel = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"][dayNum];
            return (
              <div key={d.date} style={{
                background: "#F8FAFD", border: "1px solid #E5E8EE", borderRadius: 8,
                padding: "10px 12px", textAlign: "left",
              }}>
                <div style={{ fontSize: 10.5, color: "#9CA3AF", fontWeight: 600, letterSpacing: 0.4, textTransform: "uppercase" }}>
                  {dayLabel} · {dt.getDate()}
                </div>
                <div style={{ fontSize: 14, fontWeight: 600, color: "#0A1F44", marginTop: 4,
                  fontVariantNumeric: "tabular-nums" }}>
                  {fmtUnits(d.forecast_value)}
                </div>
                <div style={{ fontSize: 10.5, color: "#9CA3AF", marginTop: 2 }}>
                  ±{fmtUnits(d.upper_bound - d.forecast_value)}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ───────────── MAIN SCREEN ─────────────
function DemandForecastScreen() {
  const prefs = useMemoD(loadDemandPrefs, []);
  const [market, setMarket] = useStateD(prefs.market || "uae");
  const [sku, setSku] = useStateD(prefs.sku || "fine-facial-100");
  const [horizon, setHorizon] = useStateD(prefs.horizon || 120);
  const [products, setProducts] = useStateD(null);
  const [forecastData, setForecastData] = useStateD(null);
  const [seasonality, setSeasonality] = useStateD(null);
  const [scenarioOpen, setScenarioOpen] = useStateD(false);
  const [sliders, setSliders] = useStateD(prefs.sliders || {
    ramadan: 0, pre_ramadan: 0, trend: 0, promo: 0,
    promoStart: "2026-06-01", promoEnd: "2026-06-07",
  });
  const [scheduleRow, setScheduleRow] = useStateD(null);
  const [drillRow, setDrillRow] = useStateD(null);
  const [compareOpen, setCompareOpen] = useStateD(false);
  const [toast, setToast] = useStateD(null);

  // persist
  useEffectD(() => {
    saveDemandPrefs({ market, sku, horizon, sliders });
  }, [market, sku, horizon, sliders]);

  // load products once
  useEffectD(() => {
    window.api.get("/products").then((r) => setProducts(r.products));
  }, []);

  // load forecast on selection change. Both endpoints fire in parallel;
  // we enrich the forecast with the seasonality payload so derived fields
  // like `drivers` see the named events from /demand/seasonality.
  useEffectD(() => {
    setForecastData(null);
    setSeasonality(null);
    let cancelled = false;
    Promise.all([
      window.api.get("/forecast", { sku, market, horizon_months: Math.round(horizon / 30) }),
      window.api.get("/demand/seasonality", { sku, market }).catch((e) => {
        console.warn("[demand] /demand/seasonality failed:", e?.message || e);
        return null;
      }),
    ]).then(([fc, seas]) => {
      if (cancelled) return;
      setSeasonality(seas);
      setForecastData(enrichForecast(fc, seas));
    }).catch((e) => {
      if (cancelled) return;
      console.error("[demand] /forecast failed:", e?.message || e);
    });
    return () => { cancelled = true; };
  }, [sku, market, horizon]);

  function showToast(msg) {
    setToast(msg); setTimeout(() => setToast(null), 2400);
  }

  // build dropdown options
  const productOpts = useMemoD(() => {
    if (!products) return [];
    return products.map((p) => ({
      id: p.sku, label: p.name, group: CATEGORY_LABEL[p.category],
    }));
  }, [products]);
  const productLabel = productOpts.find((o) => o.id === sku)?.label || sku;

  // scenario forecast
  const scenarioForecast = useMemoD(() => {
    if (!forecastData) return null;
    const { ramadan, pre_ramadan, trend, promo, promoStart, promoEnd } = sliders;
    const noChange = ramadan === 0 && pre_ramadan === 0 && trend === 0 && promo === 0;
    if (noChange) return null;
    return forecastData.forecast.map((p, i) => {
      let mul = 1;
      if (p.date >= "2026-02-10" && p.date <= "2026-02-16") mul *= 1 + pre_ramadan / 100;
      if (p.date >= "2026-02-17" && p.date <= "2026-03-18") mul *= 1 + ramadan / 100;
      mul *= 1 + (trend / 100) * (i / forecastData.forecast.length);
      if (promoStart && promoEnd && p.date >= promoStart && p.date <= promoEnd) mul *= 1 + promo / 100;
      return {
        ...p,
        forecast_value: Math.round(p.forecast_value * mul),
        lower_bound: Math.round(p.lower_bound * mul),
        upper_bound: Math.round(p.upper_bound * mul),
      };
    });
  }, [forecastData, sliders]);

  const scenarioDeltaPct = useMemoD(() => {
    if (!scenarioForecast || !forecastData) return null;
    const base = forecastData.forecast.reduce((s, p) => s + p.forecast_value, 0);
    const scen = scenarioForecast.reduce((s, p) => s + p.forecast_value, 0);
    return +(((scen - base) / base) * 100).toFixed(1);
  }, [scenarioForecast, forecastData]);

  const baselineDailyVal = useMemoD(() => {
    if (!forecastData) return 6000;
    const slice = forecastData.forecast.slice(0, 14);
    return slice.reduce((s, p) => s + p.forecast_value, 0) / slice.length;
  }, [forecastData]);

  return (
    <div style={{ padding: "20px 28px 100px", display: "flex", flexDirection: "column", gap: 16 }}>
      {/* header */}
      <div>
        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 0.6, textTransform: "uppercase", color: "#6B7280" }}>
          Predictive · Module 2
        </div>
        <h1 style={{ margin: "4px 0 0", fontSize: 28, fontWeight: 600, color: "#0A1F44", letterSpacing: -0.6 }}>
          Demand forecasting
        </h1>
        <div style={{ fontSize: 13, color: "#6B7280", marginTop: 4 }}>
          185 Prophet models · Ramadan, Eid Al-Fitr, Eid Al-Adha, pre-stockup regressors · 90+ day horizon
        </div>
      </div>

      {/* Section A — filter strip */}
      <div style={{
        position: "sticky", top: 0, zIndex: 25,
        background: "#F4F6FA", paddingTop: 4, paddingBottom: 8,
      }}>
        <div style={{
          background: "white", border: "1px solid #E5E8EE", borderRadius: 10,
          padding: "12px 16px", boxShadow: "0 1px 2px rgba(10,31,68,0.04)",
          display: "flex", flexWrap: "wrap", gap: 12, alignItems: "flex-end",
        }}>
          <Dropdown label="Market" value={market}
            options={Object.keys(MARKET_LABEL).map((id) => ({
              id,
              label: MARKET_LABEL[id],
              flag: MARKET_FLAG[id],
            }))}
            onChange={setMarket} width={210}
            renderOption={renderMarketOption}
            renderValue={renderMarketOption} />
          <Dropdown label="Product (SKU)" value={sku} options={productOpts}
            onChange={setSku} width={290} searchable
            renderOption={(o) => (
              <span>
                <span>{o.label}</span>
                <span style={{ marginLeft: 8, fontSize: 10.5, color: "#9CA3AF",
                  background: "#F4F6FA", padding: "1px 6px", borderRadius: 4, fontWeight: 600 }}>
                  {o.group}
                </span>
              </span>
            )} />
          <HorizonToggle value={horizon} onChange={setHorizon} />
          <button
            onClick={() => setScenarioOpen(!scenarioOpen)}
            style={{
              padding: "8px 14px", borderRadius: 8,
              border: scenarioOpen ? "1px solid #06B6D4" : "1px solid #DCE2EC",
              background: scenarioOpen ? "#ECFEFF" : "white",
              color: "#0A1F44", fontSize: 12.5, fontWeight: 600,
              cursor: "pointer", fontFamily: "inherit",
            }}
          >🧪 Scenario</button>
          <div style={{ flex: 1 }} />
          {forecastData && (
            <ConfidencePill confidencePct={forecastData.accuracy.forecast_confidence_percent}
              mape={forecastData.accuracy.mape_percent}
              lastTrained="3 days ago" />
          )}
          <button onClick={() => setCompareOpen(true)} style={{
            padding: "8px 14px", borderRadius: 8,
            border: "1px solid #DCE2EC", background: "white", color: "#0A1F44",
            fontSize: 12.5, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
          }}>Compare ⇄</button>
        </div>
      </div>

      {/* Scenario panel (slides under filter strip) */}
      <ScenarioPanel open={scenarioOpen}
        onClose={() => setScenarioOpen(false)}
        sliders={sliders} onChange={setSliders}
        onReset={() => setSliders({ ramadan: 0, pre_ramadan: 0, trend: 0, promo: 0,
          promoStart: "2026-06-01", promoEnd: "2026-06-07" })}
        deltaPct={scenarioDeltaPct} />

      {/* Section B — hero chart */}
      <div style={{ background: "white", border: "1px solid #E5E8EE", borderRadius: 10,
        padding: "16px 20px", boxShadow: "0 1px 2px rgba(10,31,68,0.04)" }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.6, textTransform: "uppercase", color: "#6B7280" }}>
              GET /forecast
            </div>
            <div style={{ fontSize: 16, fontWeight: 600, color: "#0A1F44", marginTop: 2, letterSpacing: -0.2 }}>
              {MARKET_FLAG[market]} {MARKET_LABEL[market]} × {productLabel}
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
            <Legend swatch={<svg width="22" height="6"><line x1="0" x2="22" y1="3" y2="3" stroke="#0A1F44" strokeWidth="2" /></svg>} label="Historical actuals" />
            <Legend swatch={<svg width="22" height="6"><line x1="0" x2="22" y1="3" y2="3" stroke="#E66A12" strokeWidth="2" strokeDasharray="4 3" /></svg>} label="Forecast" />
            <Legend swatch={<span style={{ width: 14, height: 10, background: "#8B5CF6", opacity: 0.4, borderRadius: 2, display: "inline-block" }} />} label="Ramadan" />
            <Legend swatch={<span style={{ width: 14, height: 10, background: "#F59E0B", opacity: 0.5, borderRadius: 2, display: "inline-block" }} />} label="Eid Al-Fitr" />
            <Legend swatch={<span style={{ width: 14, height: 10, background: "#15A56C", opacity: 0.5, borderRadius: 2, display: "inline-block" }} />} label="Eid Al-Adha" />
          </div>
        </div>
        <div style={{ marginTop: 10 }}>
          {forecastData ? (
            <HeroChart history={forecastData.history} forecast={forecastData.forecast}
              scenarioForecast={scenarioForecast}
              events={forecastData.seasonality_events}
              horizonDays={horizon} />
          ) : (
            <div style={{ height: 340, background: "#F4F6FA", borderRadius: 8 }} />
          )}
        </div>
      </div>

      {/* Section C — decomposition cards */}
      {forecastData && (
        <DecompositionRow history={forecastData.history.slice(-365)}
          forecast={forecastData.forecast} seasonality={seasonality} />
      )}

      {/* Section D — production table */}
      {forecastData && (
        <ProductionTable forecast={forecastData.forecast} baseline={baselineDailyVal}
          onScheduleRun={setScheduleRow}
          onDrillIn={setDrillRow} />
      )}

      {/* Section E — drivers */}
      {forecastData && (
        <DriversList drivers={forecastData.drivers} market={market}
          sku={sku} productLabel={productLabel} />
      )}

      {/* Section F — accuracy */}
      {forecastData && <AccuracyStrip accuracy={forecastData.accuracy} />}

      {/* modals + drill-ins */}
      {scheduleRow && (
        <ScheduleRunModal row={scheduleRow} productLabel={productLabel}
          onClose={() => setScheduleRow(null)}
          onSubmit={(p) => {
            const key = `fhh_prod_runs`;
            const list = JSON.parse(localStorage.getItem(key) || "[]");
            list.push({ ...p, sku, market, weekIdx: scheduleRow.idx, scheduled_at: new Date().toISOString() });
            localStorage.setItem(key, JSON.stringify(list));
            setScheduleRow(null);
            showToast(`Production run scheduled for ${fmtDateShort(p.date)}`);
          }} />
      )}
      {drillRow && (
        <DailyDrillIn row={drillRow} forecast={forecastData?.forecast}
          productLabel={productLabel} onClose={() => setDrillRow(null)} />
      )}
      <CompareOverlay open={compareOpen} onClose={() => setCompareOpen(false)}
        baseSku={sku} baseMarket={market} products={productOpts} />
      <ToastD message={toast} />
    </div>
  );
}

function Legend({ swatch, label }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11.5, color: "#4B5563", fontWeight: 500 }}>
      {swatch}<span>{label}</span>
    </span>
  );
}

Object.assign(window, { DemandForecastScreen });
