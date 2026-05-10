// Operations Calendar — unified view of alerts, maintenance, orders, and
// custom events.
//
// Three rendering modes share a single screen:
//   1. Day / Week    → FullCalendar (FullCalendarSlot)
//   2. Month         → MonthAgendaView (custom React; same /calendar/feed
//                       data as Day/Week, regrouped by week instead of
//                       by day cell)
//   3. Year          → YearView (custom React; 12 mini-month grids)
//
// Drill-down navigation:
//   - Year mini-month header  → Month-agenda for that month
//   - Month week row          → Week view starting on that week's Monday
//   - Week day-of-week header → Day view of that date (FC navLinks)
//
// Read-only first pass: clicking an event logs source data to console.

const {
  useState: useStateCal,
  useEffect: useEffectCal,
  useRef:    useRefCal,
  useMemo:   useMemoCal,
} = React;


// ─── Color palette per source ──────────────────────────────────────────────
// `user_maintenance` (Phase D — operator-logged work) uses teal so it reads
// as distinct from `past_maintenance` (which is the seeded blue history).
const SOURCE_STYLE = {
  alert:                 { bg: "#DC2626", text: "#FFFFFF", label: "Active alerts" },
  scheduled_maintenance: { bg: "#F59E0B", text: "#FFFFFF", label: "Scheduled maintenance" },
  past_maintenance:      { bg: "#3B82F6", text: "#FFFFFF", label: "Past maintenance" },
  user_maintenance:      { bg: "#0E7490", text: "#FFFFFF", label: "User maintenance" },
  material_order:        { bg: "#10B981", text: "#FFFFFF", label: "Material orders" },
  custom:                { bg: "#6B7280", text: "#FFFFFF", label: "Custom events" },
};

// Year-mode density. Day cells are tiny so we dedupe by source-type
// (one dot per unique source per day, max 5 = number of sources).
const YEAR_DENSITY = { dotSize: 3, maxDots: 5, cols: 4 };


// ─── Date helpers ──────────────────────────────────────────────────────────
function dateStr(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function firstOfMonth(d) {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

function addMonths(d, n) {
  // Snaps day to 1; acceptable since this is only used for whole-month
  // navigation. Drill-down navLinks pass exact dates separately.
  return new Date(d.getFullYear(), d.getMonth() + n, 1);
}


// Year mode renders Jan→Dec of focalDate's year.
function yearStartDate(focalDate) {
  return new Date(focalDate.getFullYear(), 0, 1);
}

function computeYearRange(focalDate) {
  const y = focalDate.getFullYear();
  return { start: `${y}-01-01`, end: `${y}-12-31` };
}

function getYearMonths(focalDate) {
  const start = yearStartDate(focalDate);
  const out = [];
  for (let i = 0; i < 12; i++) out.push(addMonths(start, i));
  return out;
}


// Month-agenda weeks: the Mon-Sun weeks whose Monday falls in the target
// month. Partial-week days at the start of the month (when the 1st isn't
// a Monday) are dropped — they belong to the previous month's last week.
// Last week may extend into the next month (e.g. Feb 2026's last week is
// Feb 23 – Mar 1).
function getMonthWeeks(monthStart) {
  const month = monthStart.getMonth();
  const firstDayOfWeek = (monthStart.getDay() + 6) % 7;  // Mon=0
  const firstMonday = new Date(monthStart);
  if (firstDayOfWeek > 0) {
    firstMonday.setDate(firstMonday.getDate() + (7 - firstDayOfWeek));
  }
  const weeks = [];
  const cursor = new Date(firstMonday);
  while (cursor.getMonth() === month) {
    const start = new Date(cursor);
    const end = new Date(cursor);
    end.setDate(end.getDate() + 6);
    weeks.push({ start, end });
    cursor.setDate(cursor.getDate() + 7);
  }
  return weeks;
}

function getMonthAgendaRange(monthStart) {
  const weeks = getMonthWeeks(monthStart);
  if (weeks.length === 0) {
    return {
      start: dateStr(monthStart),
      end: dateStr(new Date(monthStart.getFullYear(), monthStart.getMonth() + 1, 0)),
    };
  }
  return {
    start: dateStr(weeks[0].start),
    end: dateStr(weeks[weeks.length - 1].end),
  };
}

function bucketEventsByWeek(events, weeks) {
  const buckets = weeks.map(() => []);
  const bounds = weeks.map((w) => ({ s: dateStr(w.start), e: dateStr(w.end) }));
  for (const e of events) {
    for (let i = 0; i < weeks.length; i++) {
      if (e.date >= bounds[i].s && e.date <= bounds[i].e) {
        buckets[i].push(e);
        break;
      }
    }
  }
  // Stable per-bucket sort: by date, then by source (maintenance before order).
  for (const b of buckets) {
    b.sort((a, x) => {
      if (a.date !== x.date) return a.date < x.date ? -1 : 1;
      return a.source < x.source ? -1 : 1;
    });
  }
  return buckets;
}


// ─── Map a CalendarFeedItem → FullCalendar event object ────────────────────
function mapEvent(feedItem) {
  const style = SOURCE_STYLE[feedItem.source] || { bg: "#9CA3AF", text: "#FFFFFF" };
  return {
    id: feedItem.source + ":" + feedItem.id,
    title: feedItem.title,
    start: feedItem.date,
    allDay: true,
    backgroundColor: style.bg,
    borderColor:     style.bg,
    textColor:       style.text,
    extendedProps: { source_data: feedItem },
  };
}


// ─── Header ────────────────────────────────────────────────────────────────
function CalendarHeader({ onLogMaintenance }) {
  return (
    <div style={{
      marginBottom: 16,
      display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 12,
    }}>
      <div>
        <div style={{
          fontSize: 11, fontWeight: 700, letterSpacing: 0.6,
          textTransform: "uppercase", color: "#6B7280",
        }}>Operations</div>
        <h1 style={{
          fontSize: 24, fontWeight: 600, color: "#0A1F44",
          margin: "4px 0 6px", letterSpacing: -0.4,
        }}>Operations Calendar</h1>
        <div style={{ fontSize: 13, color: "#6B7280", maxWidth: 720 }}>
          Unified view of alerts, maintenance, orders, and scheduled events
          across the fleet.
        </div>
      </div>
      {onLogMaintenance && (
        <button onClick={onLogMaintenance} style={{
          padding: "8px 14px", borderRadius: 8,
          border: "1px solid #0E7490", background: "white", color: "#0E7490",
          fontSize: 12.5, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
          flexShrink: 0,
        }}
          onMouseEnter={(e) => { e.currentTarget.style.background = "#ECFEFF"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "white"; }}
        >📝 Log Maintenance</button>
      )}
    </div>
  );
}


// NOTE: Renamed from `Legend` to `CalendarLegend` to avoid global-name
// collision with demand_forecast.jsx, which has its own `Legend`. The
// in-browser Babel + classic-script setup means top-level function names
// share window namespace; load order put my Legend last and broke the
// demand chart.
function CalendarLegend() {
  return (
    <div style={{
      display: "flex", flexWrap: "wrap", gap: 14,
      padding: "10px 12px", marginBottom: 12,
      background: "white", border: "1px solid #E5EAF1", borderRadius: 8,
    }}>
      {Object.entries(SOURCE_STYLE).map(([source, style]) => (
        <div key={source} style={{
          display: "flex", alignItems: "center", gap: 6,
          fontSize: 12, color: "#4B5563", fontWeight: 500,
        }}>
          <span style={{
            width: 11, height: 11, borderRadius: 3, background: style.bg,
            border: "1px solid " + style.bg,
          }} />
          {style.label}
        </div>
      ))}
    </div>
  );
}


function ErrorBanner({ error, onRetry }) {
  return (
    <div style={{
      padding: "10px 14px", marginBottom: 12,
      background: "#FEF2F2", border: "1px solid #FCA5A5", borderRadius: 8,
      display: "flex", alignItems: "center", justifyContent: "space-between",
      gap: 12,
    }}>
      <div style={{ fontSize: 13, color: "#991B1B" }}>
        Couldn't load events: {error?.message || "network error"}.
      </div>
      <button onClick={onRetry} style={{
        padding: "5px 12px", borderRadius: 6,
        background: "#991B1B", color: "white", border: "none",
        cursor: "pointer", fontFamily: "inherit", fontWeight: 600, fontSize: 12,
      }}>Retry</button>
    </div>
  );
}


function LoadingBar({ visible }) {
  return (
    <div style={{
      position: "absolute", top: 0, left: 0, right: 0, height: 2,
      background: visible ? "#0A1F44" : "transparent",
      transition: "background 200ms",
      animation: visible ? "fhhCalLoading 1.2s ease-in-out infinite" : "none",
      zIndex: 5,
    }} />
  );
}


function EmptyOverlay() {
  return (
    <div style={{
      position: "absolute", inset: 0,
      display: "flex", alignItems: "center", justifyContent: "center",
      pointerEvents: "none",
    }}>
      <div style={{
        background: "rgba(244,246,250,0.85)",
        padding: "10px 18px", borderRadius: 999,
        fontSize: 13, color: "#6B7280", fontWeight: 500,
      }}>
        No events in this range
      </div>
    </div>
  );
}


// ─── Custom toolbar (replaces FC's headerToolbar) ──────────────────────────
function CustomToolbar({
  fcView, isYearMode, title,
  onPrev, onNext, onToday,
  onSetFCView, onSetYearMode,
}) {
  // 4 view buttons: Day · Week · Month · Year.
  const viewButtons = [
    { id: "day",   label: "Day",   active: !isYearMode && fcView === "timeGridDay",  onClick: () => onSetFCView("timeGridDay")  },
    { id: "week",  label: "Week",  active: !isYearMode && fcView === "timeGridWeek", onClick: () => onSetFCView("timeGridWeek") },
    { id: "month", label: "Month", active: !isYearMode && fcView === "dayGridMonth", onClick: () => onSetFCView("dayGridMonth") },
    { id: "year",  label: "Year",  active: isYearMode,                                onClick: onSetYearMode                     },
  ];

  const navBtn = {
    background: "white", border: "1px solid #DCE2EC", color: "#0A1F44",
    fontFamily: "inherit", fontWeight: 600, fontSize: 12,
    padding: "6px 12px", cursor: "pointer", borderRadius: 6,
  };
  const viewBase = {
    background: "white", border: "1px solid #DCE2EC", color: "#0A1F44",
    fontFamily: "inherit", fontWeight: 600, fontSize: 12,
    padding: "6px 12px", cursor: "pointer",
  };
  const viewActive = {
    ...viewBase, background: "#0A1F44", borderColor: "#0A1F44", color: "white",
  };

  return (
    <div style={{
      display: "flex", alignItems: "center",
      gap: 12, marginBottom: 12, flexWrap: "wrap",
    }}>
      <div style={{ display: "flex" }}>
        <button onClick={onPrev}  style={{ ...navBtn, borderTopRightRadius: 0, borderBottomRightRadius: 0, padding: "6px 10px" }}>‹</button>
        <button onClick={onNext}  style={{ ...navBtn, marginLeft: -1, borderTopLeftRadius: 0, borderBottomLeftRadius: 0, padding: "6px 10px" }}>›</button>
        <button onClick={onToday} style={{ ...navBtn, marginLeft: 6 }}>Today</button>
      </div>
      <div style={{
        flex: 1, textAlign: "center", minWidth: 120,
        fontSize: 17, fontWeight: 600, color: "#0A1F44", letterSpacing: -0.3,
      }}>{title || ""}</div>
      <div style={{ display: "flex" }}>
        {viewButtons.map((b, i) => (
          <button
            key={b.id}
            onClick={b.onClick}
            style={{
              ...(b.active ? viewActive : viewBase),
              marginLeft: i === 0 ? 0 : -1,
              borderTopLeftRadius:    i === 0 ? 6 : 0,
              borderBottomLeftRadius: i === 0 ? 6 : 0,
              borderTopRightRadius:    i === viewButtons.length - 1 ? 6 : 0,
              borderBottomRightRadius: i === viewButtons.length - 1 ? 6 : 0,
              zIndex: b.active ? 1 : 0,
            }}
          >{b.label}</button>
        ))}
      </div>
    </div>
  );
}


// ─── MonthAgendaView ───────────────────────────────────────────────────────
function EventLine({ event, onClick }) {
  const style = SOURCE_STYLE[event.source] || { bg: "#9CA3AF" };
  // event.date is YYYY-MM-DD; appending T00:00:00 forces local-time parse
  // (otherwise Date(YYYY-MM-DD) is treated as UTC, which can shift one day
  // back when rendered in negative-offset timezones).
  const dt = new Date(event.date + "T00:00:00");
  const dateLabel = dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return (
    <div
      onClick={onClick ? (e) => { e.stopPropagation(); onClick(); } : undefined}
      onMouseEnter={onClick ? (e) => { e.currentTarget.style.background = "#F4F6FA"; } : undefined}
      onMouseLeave={onClick ? (e) => { e.currentTarget.style.background = "transparent"; } : undefined}
      style={{
        display: "flex", alignItems: "center", gap: 10,
        fontSize: 13, color: "#374151", lineHeight: 1.4,
        cursor: onClick ? "pointer" : "default",
        padding: "2px 4px", margin: "0 -4px", borderRadius: 4,
        transition: "background 100ms",
      }}>
      <span style={{
        width: 8, height: 8, borderRadius: "50%", background: style.bg,
        flexShrink: 0,
      }} />
      <span style={{
        flex: 1, minWidth: 0,
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
      }}>{event.title}</span>
      <span style={{ color: "#6B7280", fontSize: 12, flexShrink: 0 }}>{dateLabel}</span>
    </div>
  );
}


function WeekRow({ week, weekNum, events, isLast, onClick, onEventClick }) {
  const [hovered, setHovered] = useStateCal(false);
  const startStr = week.start.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const endStr   = week.end.toLocaleDateString("en-US",   { month: "short", day: "numeric" });
  const dateRange = (week.start.getMonth() === week.end.getMonth())
    ? `${startStr} – ${week.end.getDate()}`
    : `${startStr} – ${endStr}`;

  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        padding: "14px 16px",
        cursor: "pointer",
        borderBottom: isLast ? "none" : "1px solid #E5EAF1",
        background: hovered ? "#F4F7FC" : "white",
        transition: "background 100ms",
      }}
    >
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 8,
      }}>
        <div>
          <span style={{
            fontSize: 13, fontWeight: 600, color: "#0A1F44",
            letterSpacing: 0.4,
          }}>WEEK {weekNum}</span>
          <span style={{ fontSize: 12, color: "#6B7280", marginLeft: 8 }}>
            — {dateRange}
          </span>
        </div>
        <span style={{
          color: "#9CA3AF", fontSize: 18, fontWeight: 400,
          marginLeft: 8, lineHeight: 1,
        }}>›</span>
      </div>
      {events.length === 0 ? (
        <div style={{
          fontSize: 13, color: "#9CA3AF", fontStyle: "italic",
        }}>(no scheduled work)</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {events.map((e) => (
            <EventLine
              key={`${e.source}:${e.id}`}
              event={e}
              onClick={onEventClick ? () => onEventClick(e) : undefined}
            />
          ))}
        </div>
      )}
    </div>
  );
}


function MonthAgendaView({ focalDate, events, loading, error, onRetry, onWeekClick, onEventClick }) {
  const monthStart = useMemoCal(() => firstOfMonth(focalDate), [focalDate]);
  const weeks      = useMemoCal(() => getMonthWeeks(monthStart), [monthStart]);
  const buckets    = useMemoCal(() => bucketEventsByWeek(events, weeks), [events, weeks]);

  const monthLabel = monthStart.toLocaleDateString("en-US", { month: "long", year: "numeric" });
  const totalActionable = buckets.reduce((sum, b) => sum + b.length, 0);
  const showEmpty = !loading && !error && totalActionable === 0;

  return (
    <div style={{
      position: "relative",
      height: "100%", overflow: "auto", padding: 4, boxSizing: "border-box",
    }}>
      <LoadingBar visible={loading} />
      {error && (
        <div style={{ marginBottom: 12 }}>
          <ErrorBanner error={error} onRetry={onRetry} />
        </div>
      )}
      <div style={{
        background: "white", border: "1px solid #E5EAF1", borderRadius: 8,
        overflow: "hidden",
      }}>
        {weeks.map((w, i) => (
          <WeekRow
            key={dateStr(w.start)}
            week={w}
            weekNum={i + 1}
            events={buckets[i]}
            isLast={i === weeks.length - 1}
            onClick={() => onWeekClick(w.start)}
            onEventClick={onEventClick}
          />
        ))}
      </div>
      {showEmpty && (
        <div style={{
          padding: "14px 18px", marginTop: 12,
          fontSize: 12, color: "#6B7280", textAlign: "center", lineHeight: 1.6,
        }}>
          Nothing scheduled for {monthLabel}. Schedule maintenance from the
          Alerts tab or orders from the Demand tab.
        </div>
      )}
    </div>
  );
}


// ─── MiniMonth (Year-mode mini-calendar) ──────────────────────────────────
function MiniMonth({ monthDate, eventsByDate, density, todayStr, onMonthClick }) {
  const year  = monthDate.getFullYear();
  const month = monthDate.getMonth();
  const firstDay = new Date(year, month, 1);
  const lastDay  = new Date(year, month + 1, 0);
  const daysInMonth = lastDay.getDate();
  const firstDayOfWeek = (firstDay.getDay() + 6) % 7;  // Mon-first
  const prevMonthLastDay = new Date(year, month, 0).getDate();

  const cells = [];
  for (let i = firstDayOfWeek - 1; i >= 0; i--) {
    cells.push({ day: prevMonthLastDay - i, inMonth: false, dateStr: null });
  }
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push({
      day: d, inMonth: true,
      dateStr: dateStr(new Date(year, month, d)),
    });
  }
  let nd = 1;
  while (cells.length < 42) {
    cells.push({ day: nd++, inMonth: false, dateStr: null });
  }

  const monthLabel = monthDate.toLocaleDateString("en-US", { month: "long", year: "numeric" });

  return (
    <div style={{
      background: "white", border: "1px solid #E5EAF1", borderRadius: 4,
      padding: "10px 10px 8px", display: "flex", flexDirection: "column",
      minWidth: 0,
    }}>
      <div
        style={{
          textAlign: "center", fontSize: 13, fontWeight: 500,
          color: "#0A1F44", marginBottom: 8, letterSpacing: -0.1,
          cursor: onMonthClick ? "pointer" : "default",
          userSelect: "none",
        }}
        onClick={onMonthClick ? () => onMonthClick(monthDate) : undefined}
        title={onMonthClick ? `Open ${monthLabel} in Month view` : undefined}
      >{monthLabel}</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 2 }}>
        {["M","T","W","T","F","S","S"].map((dow, i) => (
          <div key={`dow-${i}`} style={{
            fontSize: 10, fontWeight: 600, color: "#9CA3AF",
            textAlign: "center", padding: "2px 0", letterSpacing: 0.4,
          }}>{dow}</div>
        ))}
        {cells.map((cell, i) => (
          <DayCell
            key={i}
            cell={cell}
            isToday={cell.dateStr === todayStr}
            events={cell.dateStr ? (eventsByDate[cell.dateStr] || []) : []}
            density={density}
          />
        ))}
      </div>
    </div>
  );
}


function DayCell({ cell, isToday, events, density }) {
  const { dotSize, maxDots } = density;

  // Year mode: one dot per unique source-type
  const seen = new Set();
  const dots = [];
  for (const e of events) {
    if (seen.has(e.source)) continue;
    seen.add(e.source);
    dots.push({ source: e.source });
    if (dots.length >= maxDots) break;
  }

  return (
    <div style={{
      position: "relative",
      minHeight: 26, padding: "2px 0", textAlign: "center",
    }}>
      <div style={{
        fontSize: 11, lineHeight: 1.5,
        color: !cell.inMonth ? "#D1D5DB" : isToday ? "white" : "#374151",
        background: isToday ? "#0A1F44" : "transparent",
        borderRadius: isToday ? "50%" : 0,
        width: isToday ? 18 : "auto",
        height: isToday ? 18 : "auto",
        margin: isToday ? "0 auto" : 0,
        display: isToday ? "flex" : "block",
        alignItems: "center", justifyContent: "center",
        fontWeight: isToday ? 700 : 400,
      }}>{cell.day}</div>
      {cell.inMonth && dots.length > 0 && (
        <div style={{
          display: "flex", justifyContent: "center", gap: 2,
          marginTop: 2, alignItems: "center", height: dotSize + 2,
        }}>
          {dots.map((d, i) => (
            <span
              key={i}
              title={SOURCE_STYLE[d.source]?.label || d.source}
              style={{
                display: "inline-block",
                width: dotSize, height: dotSize, borderRadius: "50%",
                background: SOURCE_STYLE[d.source]?.bg || "#9CA3AF",
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}


// ─── YearView: container for 12 mini-months ────────────────────────────────
function YearView({ focalDate, events, loading, error, onRetry, onMonthClick }) {
  const monthList = useMemoCal(() => getYearMonths(focalDate), [focalDate]);

  const eventsByDate = useMemoCal(() => {
    const m = {};
    for (const e of events) {
      if (!m[e.date]) m[e.date] = [];
      m[e.date].push(e);
    }
    return m;
  }, [events]);

  const todayStr = dateStr(new Date());
  const isEmpty = !loading && !error && events.length === 0;

  return (
    <div style={{
      position: "relative",
      height: "100%", overflow: "auto", padding: 4, boxSizing: "border-box",
    }}>
      <LoadingBar visible={loading} />
      {error && (
        <div style={{ marginBottom: 12 }}>
          <ErrorBanner error={error} onRetry={onRetry} />
        </div>
      )}
      <div
        className="fhh-cal-year-grid"
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${YEAR_DENSITY.cols}, minmax(0, 1fr))`,
          gap: 12,
        }}
      >
        {monthList.map((md) => (
          <MiniMonth
            key={md.toISOString()}
            monthDate={md}
            eventsByDate={eventsByDate}
            density={YEAR_DENSITY}
            todayStr={todayStr}
            onMonthClick={onMonthClick}
          />
        ))}
      </div>
      {isEmpty && (
        <div style={{
          position: "absolute", inset: 0, display: "flex",
          alignItems: "center", justifyContent: "center", pointerEvents: "none",
        }}>
          <div style={{
            background: "rgba(244,246,250,0.85)",
            padding: "10px 18px", borderRadius: 999,
            fontSize: 13, color: "#6B7280", fontWeight: 500,
          }}>No events in this range</div>
        </div>
      )}
    </div>
  );
}


// ─── FullCalendarSlot: imperative FC instance behind a React wrapper ──────
// Mounted/unmounted by the parent based on view mode, AND force-remounted
// via `key={fcCurrentView}` whenever the FC view changes. Each mount =
// one fresh FC.Calendar; .destroy() on unmount.
//
// Note: Month view is no longer rendered through FCSlot — see
// MonthAgendaView. FCSlot only handles timeGridDay and timeGridWeek.
function FullCalendarSlot({
  initialView, initialDate,
  onMount,
  onDatesSet, onLoading, onEventsLoaded, onError,
  onEventClick, onNavigateToDay,
}) {
  const containerRef = useRefCal(null);

  useEffectCal(() => {
    if (!window.FullCalendar || !window.FullCalendar.Calendar) return;
    const FC = window.FullCalendar;
    const cal = new FC.Calendar(containerRef.current, {
      initialView,
      initialDate,
      headerToolbar: false,
      height: "100%",
      expandRows: true,
      dayMaxEvents: 2,
      firstDay: 1,
      nowIndicator: true,
      eventDisplay: "block",
      navLinks: true,
      navLinkDayClick: (date) => {
        if (onNavigateToDay) onNavigateToDay(date);
      },
      events: function (fetchInfo, success, failure) {
        const start = fetchInfo.startStr.slice(0, 10);
        const end   = fetchInfo.endStr.slice(0, 10);
        window.api.get("/calendar/feed", { start, end })
          .then((data) => {
            if (onEventsLoaded) onEventsLoaded(data);
            success(data.events.map(mapEvent));
          })
          .catch((err) => {
            if (onError) onError(err);
            failure(err);
          });
      },
      loading: onLoading,
      datesSet: onDatesSet,
      eventClick: onEventClick,
    });
    cal.render();
    if (onMount) onMount(cal);
    return () => {
      cal.destroy();
      if (onMount) onMount(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <div ref={containerRef} style={{ height: "100%" }} />;
}


// ─── FullCalendar overrides + Year-grid responsive rules ──────────────────
function CalendarStyles() {
  return (
    <style dangerouslySetInnerHTML={{ __html: `
      @keyframes fhhCalLoading {
        0% { transform: translateX(-100%); }
        100% { transform: translateX(100%); }
      }
      .fhh-cal .fc {
        font-family: inherit; color: #0A1F44;
        --fc-border-color: #E5EAF1;
        --fc-today-bg-color: #F4F6FA;
        --fc-page-bg-color: white;
      }
      .fhh-cal .fc-event {
        font-size: 10.5px; padding: 0 4px; cursor: pointer;
        border-radius: 3px; line-height: 1.2;
      }
      .fhh-cal .fc-daygrid-event-dot { display: none; }
      .fhh-cal .fc-daygrid-day-number {
        font-size: 11px; color: #4B5563; padding: 3px 6px;
      }
      .fhh-cal .fc-daygrid-more-link {
        font-size: 10.5px; color: #6B7280; font-weight: 600;
        padding: 0 4px; margin-top: 1px;
      }
      .fhh-cal .fc-daygrid-more-link:hover { color: #0A1F44; text-decoration: underline; }
      .fhh-cal .fc-col-header-cell-cushion {
        font-size: 11px; font-weight: 600; color: #6B7280;
        text-transform: uppercase; letter-spacing: 0.5px; padding: 5px 4px;
      }
      .fhh-cal .fc-day-today .fc-daygrid-day-number {
        color: #0A1F44; font-weight: 700;
      }
      .fhh-cal .fc-timegrid-slot { height: 36px; }
      .fhh-cal .fc-scrollgrid { border-radius: 6px; overflow: hidden; }

      .fhh-cal .fc a[data-navlink] { cursor: pointer; }
      .fhh-cal .fc a[data-navlink]:hover { text-decoration: underline; }

      @media (max-width: 1100px) {
        .fhh-cal-year-grid { grid-template-columns: repeat(3, minmax(0, 1fr)) !important; }
      }
      @media (max-width: 700px) {
        .fhh-cal-year-grid { grid-template-columns: 1fr !important; }
      }
    ` }} />
  );
}


// ─── EventDetailModal ─────────────────────────────────────────────────────
// Opens on event click from any view (Day, Week, Month-agenda). Year mode
// stays non-interactive — dots are too small and represent multiple events
// per day after dedup.
function EventDetailModal({ event, onClose }) {
  if (!event) return null;

  // Local map (kept inside the function to avoid module-global names that
  // would compete with other classic-script files in this codebase — same
  // reasoning as the CalendarLegend rename earlier in the file).
  const SINGULAR = {
    alert:                 "Active alert",
    scheduled_maintenance: "Scheduled maintenance",
    past_maintenance:      "Past maintenance",
    user_maintenance:      "Maintenance entry",
    material_order:        "Material order",
    custom:                "Custom event",
  };
  const style       = SOURCE_STYLE[event.source] || { bg: "#9CA3AF", text: "#FFFFFF" };
  const sourceLabel = SINGULAR[event.source] || event.source;

  const dt = new Date(event.date + "T00:00:00");
  const dateLabel = dt.toLocaleDateString("en-US", {
    weekday: "long", month: "long", day: "numeric", year: "numeric",
  });
  const shortDate = (s) => new Date(s + "T00:00:00").toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
  });

  // Source-specific labelled rows
  const fields = [];
  if (event.source === "alert") {
    if (event.severity)   fields.push({ label: "Severity", value: event.severity, capitalize: true });
    if (event.status)     fields.push({ label: "Status",   value: event.status,   capitalize: true });
    if (event.machine_id) fields.push({ label: "Machine",  value: event.machine_id });
    if (event.alert_id)   fields.push({ label: "Alert ID", value: event.alert_id });
  } else if (event.source === "scheduled_maintenance") {
    if (event.machine_id) fields.push({ label: "Machine",    value: event.machine_id });
    if (event.technician) fields.push({ label: "Technician", value: event.technician });
    if (event.priority)   fields.push({ label: "Priority",   value: event.priority, capitalize: true });
  } else if (event.source === "past_maintenance") {
    if (event.machine_id)             fields.push({ label: "Machine",    value: event.machine_id });
    if (event.technician)             fields.push({ label: "Technician", value: event.technician });
    if (event.downtime_hours != null) fields.push({ label: "Downtime",   value: `${event.downtime_hours} h` });
    if (event.cost_usd != null)       fields.push({ label: "Cost",       value: `$${Number(event.cost_usd).toLocaleString()}` });
  } else if (event.source === "user_maintenance") {
    if (event.machine_id)             fields.push({ label: "Machine",    value: event.machine_id });
    if (event.component_id)           fields.push({ label: "Component",  value: event.component_id, capitalize: true });
    if (event.maintenance_type)       fields.push({ label: "Type",       value: event.maintenance_type, capitalize: true });
    if (event.technician)             fields.push({ label: "Technician", value: event.technician });
    if (event.duration_hours != null) fields.push({ label: "Duration",   value: `${event.duration_hours} h` });
    if (event.cost_usd != null)       fields.push({ label: "Cost",       value: `$${Number(event.cost_usd).toLocaleString()}` });
  } else if (event.source === "material_order") {
    // Show BOTH dates regardless of whether user clicked the placed or
    // arrives event — both items carry both dates from the backend.
    if (event.order_date)            fields.push({ label: "Ordered", value: shortDate(event.order_date) });
    if (event.expected_arrival_date) fields.push({ label: "Arrives", value: shortDate(event.expected_arrival_date) });
    if (event.sku)                   fields.push({ label: "SKU",     value: event.sku });
    if (event.market)                fields.push({ label: "Market",  value: String(event.market).toUpperCase() });
    if (event.quantity != null) {
      fields.push({ label: "Quantity",
        value: `${Number(event.quantity).toLocaleString()} ${event.unit || ""}`.trim() });
    }
    if (event.status) fields.push({ label: "Status", value: event.status, capitalize: true });
  } else if (event.source === "custom") {
    if (event.machine_id)               fields.push({ label: "Machine",  value: event.machine_id });
    if (event.event_type)               fields.push({ label: "Type",     value: event.event_type, capitalize: true });
    if (event.event_time)               fields.push({ label: "Time",     value: event.event_time });
    if (event.duration_minutes != null) fields.push({ label: "Duration", value: `${event.duration_minutes} min` });
  }

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, zIndex: 100,
      background: "rgba(10,31,68,0.45)",
      display: "flex", alignItems: "center", justifyContent: "center",
      padding: 24,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderRadius: 12, width: 480, maxWidth: "100%",
        padding: "22px 24px", boxShadow: "0 20px 60px rgba(10,31,68,0.25)",
        display: "flex", flexDirection: "column", gap: 14,
      }}>
        <div>
          <span style={{
            display: "inline-block",
            background: style.bg, color: style.text,
            fontSize: 11, fontWeight: 700, letterSpacing: 0.4,
            textTransform: "uppercase",
            padding: "3px 10px", borderRadius: 999,
            marginBottom: 8,
          }}>{sourceLabel}</span>
          <div style={{
            fontSize: 18, fontWeight: 600, color: "#0A1F44",
            letterSpacing: -0.3, lineHeight: 1.3,
          }}>{event.title}</div>
          <div style={{ fontSize: 12.5, color: "#6B7280", marginTop: 4 }}>
            {dateLabel}
          </div>
        </div>

        {fields.length > 0 && (
          <div style={{
            display: "grid", gridTemplateColumns: "max-content 1fr",
            gap: "8px 16px", fontSize: 13,
          }}>
            {fields.map((f, i) => (
              <React.Fragment key={i}>
                <div style={{ color: "#6B7280", fontWeight: 500 }}>{f.label}</div>
                <div style={{
                  color: "#0A1F44",
                  textTransform: f.capitalize ? "capitalize" : "none",
                  wordBreak: "break-word",
                }}>{f.value}</div>
              </React.Fragment>
            ))}
          </div>
        )}

        {event.notes && (
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: "#4B5563", marginBottom: 4 }}>Notes</div>
            <div style={{
              fontSize: 13, color: "#374151",
              padding: "10px 12px", background: "#F4F6FA",
              borderRadius: 6, whiteSpace: "pre-wrap",
            }}>{event.notes}</div>
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 4 }}>
          <button onClick={onClose} style={{
            padding: "8px 14px", borderRadius: 7,
            border: "none", background: "#0A1F44", color: "white",
            fontSize: 13, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
          }}>Close</button>
        </div>
      </div>
    </div>
  );
}


// ─── Main screen ───────────────────────────────────────────────────────────
function CalendarScreen() {
  const calRef = useRefCal(null);

  // FC mode covers Day/Week (Month is now agenda).
  const [fcCurrentView, setFcCurrentView] = useStateCal("dayGridMonth");
  const [fcTitle,       setFcTitle]       = useStateCal("");
  const [fcLoading,     setFcLoading]     = useStateCal(false);
  const [fcError,       setFcError]       = useStateCal(null);
  const [fcEventCount,  setFcEventCount]  = useStateCal(null);

  // Month-agenda mode (active when !isYearMode && fcCurrentView === "dayGridMonth")
  const [monthEvents,  setMonthEvents]  = useStateCal([]);
  const [monthLoading, setMonthLoading] = useStateCal(false);
  const [monthError,   setMonthError]   = useStateCal(null);

  // Year mode
  const [isYearMode,  setIsYearMode]  = useStateCal(false);
  const [focalDate,   setFocalDate]   = useStateCal(() => firstOfMonth(new Date()));
  const [yearEvents,  setYearEvents]  = useStateCal([]);
  const [yearLoading, setYearLoading] = useStateCal(false);
  const [yearError,   setYearError]   = useStateCal(null);

  const [bundleMissing, setBundleMissing] = useStateCal(false);
  const [detailEvent,   setDetailEvent]   = useStateCal(null);
  const [logMaintOpen,  setLogMaintOpen]  = useStateCal(false);
  // Bumped after a successful log so the active view re-fetches its feed.
  const [feedRevision,  setFeedRevision]  = useStateCal(0);

  useEffectCal(() => {
    if (!window.FullCalendar || !window.FullCalendar.Calendar) {
      setBundleMissing(true);
    }
  }, []);

  const isMonthAgenda = !isYearMode && fcCurrentView === "dayGridMonth";
  const isFCSlot      = !isYearMode && !isMonthAgenda;

  // ─── Year-mode fetch ────────────────────────────────────────────────────
  useEffectCal(() => {
    if (!isYearMode) return;
    let cancelled = false;
    setYearLoading(true);
    setYearError(null);
    const { start, end } = computeYearRange(focalDate);
    window.api.get("/calendar/feed", { start, end })
      .then((data) => {
        if (cancelled) return;
        setYearEvents(data.events);
        setYearLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setYearError(err);
        setYearLoading(false);
      });
    return () => { cancelled = true; };
  }, [isYearMode, focalDate]);

  // ─── Month-agenda fetch ─────────────────────────────────────────────────
  useEffectCal(() => {
    if (!isMonthAgenda) return;
    let cancelled = false;
    setMonthLoading(true);
    setMonthError(null);
    const range = getMonthAgendaRange(firstOfMonth(focalDate));
    window.api.get("/calendar/feed", range)
      .then((data) => {
        if (cancelled) return;
        setMonthEvents(data.events);
        setMonthLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setMonthError(err);
        setMonthLoading(false);
      });
    return () => { cancelled = true; };
  }, [isMonthAgenda, focalDate]);

  // ─── FC callbacks ───────────────────────────────────────────────────────
  function handleDatesSet(info) {
    setFcTitle(info.view.title);
    setFcCurrentView(info.view.type);
    setFocalDate(info.view.currentStart);
  }
  function handleEventsLoaded(data) {
    setFcError(null);
    setFcEventCount(data.events.length);
  }
  function handleEventClick(info) {
    setDetailEvent(info.event.extendedProps.source_data);
  }
  function handleNavigateToDay(date) {
    setIsYearMode(false);
    setFocalDate(date);
    setFcCurrentView("timeGridDay");
  }
  function handleYearMonthClick(monthDate) {
    setIsYearMode(false);
    setFocalDate(monthDate);
    setFcCurrentView("dayGridMonth");
  }
  function handleWeekClick(weekStart) {
    setIsYearMode(false);
    setFocalDate(weekStart);
    setFcCurrentView("timeGridWeek");
  }

  // ─── Toolbar handlers ───────────────────────────────────────────────────
  function handlePrev() {
    if (isYearMode) {
      setFocalDate((d) => addMonths(d, -12));
    } else if (isMonthAgenda) {
      setFocalDate((d) => addMonths(d, -1));
    } else if (calRef.current) {
      calRef.current.prev();
    }
  }
  function handleNext() {
    if (isYearMode) {
      setFocalDate((d) => addMonths(d, 12));
    } else if (isMonthAgenda) {
      setFocalDate((d) => addMonths(d, 1));
    } else if (calRef.current) {
      calRef.current.next();
    }
  }
  function handleToday() {
    const today = new Date();
    setFocalDate(today);
    if (isFCSlot && calRef.current) calRef.current.today();
  }
  function setFCView(viewType) {
    setIsYearMode(false);
    setFcCurrentView(viewType);
  }
  function enterYearMode() {
    setIsYearMode(true);
  }
  function retryFC() {
    if (calRef.current) calRef.current.refetchEvents();
  }
  function retryMonth() {
    setMonthError(null);
    setFocalDate(new Date(focalDate));
  }
  function retryYear() {
    setYearError(null);
    setFocalDate(new Date(focalDate));
  }

  // ─── Title (single source of truth, mode-dependent) ─────────────────────
  let displayTitle;
  if (isYearMode) {
    displayTitle = String(focalDate.getFullYear());
  } else if (isMonthAgenda) {
    displayTitle = focalDate.toLocaleDateString("en-US", { month: "long", year: "numeric" });
  } else {
    displayTitle = fcTitle;
  }

  return (
    <div style={{
      height: "calc(100vh - 56px)",
      display: "flex", flexDirection: "column",
      padding: 24, boxSizing: "border-box",
    }}>
      <CalendarStyles />
      <CalendarHeader onLogMaintenance={() => setLogMaintOpen(true)} />
      <CalendarLegend />
      {isFCSlot && fcError && <ErrorBanner error={fcError} onRetry={retryFC} />}
      {bundleMissing && (
        <div style={{
          padding: 16, marginBottom: 12,
          background: "#FEF2F2", border: "1px solid #FCA5A5", borderRadius: 8,
          fontSize: 13, color: "#991B1B",
        }}>
          FullCalendar bundle failed to load. Check your network connection
          (the bundle is fetched from cdn.jsdelivr.net) and refresh the page.
        </div>
      )}
      <div className="fhh-cal" style={{
        flex: 1, minHeight: 0, position: "relative",
        background: "white", border: "1px solid #E5EAF1", borderRadius: 12,
        padding: 16, boxSizing: "border-box", overflow: "hidden",
        display: "flex", flexDirection: "column",
      }}>
        <CustomToolbar
          fcView={fcCurrentView}
          isYearMode={isYearMode}
          title={displayTitle}
          onPrev={handlePrev}
          onNext={handleNext}
          onToday={handleToday}
          onSetFCView={setFCView}
          onSetYearMode={enterYearMode}
        />
        <div style={{ flex: 1, minHeight: 0, position: "relative" }}>
          {isFCSlot && !bundleMissing && (
            <FullCalendarSlot
              key={fcCurrentView}
              initialView={fcCurrentView}
              initialDate={focalDate}
              onMount={(cal) => { calRef.current = cal; }}
              onDatesSet={handleDatesSet}
              onLoading={setFcLoading}
              onEventsLoaded={handleEventsLoaded}
              onError={setFcError}
              onEventClick={handleEventClick}
              onNavigateToDay={handleNavigateToDay}
            />
          )}
          {isFCSlot && <LoadingBar visible={fcLoading} />}
          {isFCSlot && !fcLoading && fcEventCount === 0 && !fcError && !bundleMissing && <EmptyOverlay />}

          {isMonthAgenda && (
            <MonthAgendaView
              focalDate={focalDate}
              events={monthEvents}
              loading={monthLoading}
              error={monthError}
              onRetry={retryMonth}
              onWeekClick={handleWeekClick}
              onEventClick={setDetailEvent}
            />
          )}

          {isYearMode && (
            <YearView
              focalDate={focalDate}
              events={yearEvents}
              loading={yearLoading}
              error={yearError}
              onRetry={retryYear}
              onMonthClick={handleYearMonthClick}
            />
          )}
        </div>
      </div>
      {detailEvent && (
        <EventDetailModal
          event={detailEvent}
          onClose={() => setDetailEvent(null)}
        />
      )}
      {logMaintOpen && (
        <MaintenanceEntryModal
          onClose={() => setLogMaintOpen(false)}
          onSubmitted={() => {
            setLogMaintOpen(false);
            // Bump the revision so all three view modes re-pull. FC view
            // refetches via its own ref; agenda/year via dependency change.
            setFeedRevision((n) => n + 1);
            if (calRef.current) calRef.current.refetchEvents();
            // Also nudge focalDate so month/year effects re-run.
            setFocalDate((d) => new Date(d.getTime()));
          }}
        />
      )}
    </div>
  );
}
