// Top-level app shell. Two regions:
//   - Left ~70%: routed main content (overview, machine_detail, alerts, demand_forecast)
//   - Right ~30%: always-on ChatSidebar with current_page context
//
// Auth gate: at startup we read window.api.auth.getUser() from localStorage.
// If absent OR the backend ever returns token_expired/invalid_token (which
// fires the "fhh:auth:expired" event), we render <LoginScreen> instead of
// the dashboard. Token + user are persisted across page reloads.

const { useState: useStateApp, useEffect: useEffectApp } = React;

function TopNav({ active, onNavigate, kpiSummary, currentUser, onLogout }) {
  const items = [
    { id: "overview", label: "Overview" },
    { id: "alerts", label: "Alerts" },
    { id: "demand_forecast", label: "Demand" },
    { id: "calendar", label: "Calendar" },
  ];
  return (
    <header style={{
      height: 56,
      background: "#0A1F44",
      color: "white",
      display: "flex", alignItems: "center",
      padding: "0 24px",
      borderBottom: "1px solid #07173A",
      flexShrink: 0,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginRight: 28 }}>
        <div style={{
          width: 28, height: 28, borderRadius: 7,
          background: "linear-gradient(135deg, #00A865 0%, #15A56C 100%)",
          color: "white",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 13, fontWeight: 700,
        }}>F</div>
        <div style={{ fontSize: 14, fontWeight: 600, letterSpacing: 0.2 }}>
          FHH AI Optimizer
        </div>
        <span style={{
          fontSize: 10, padding: "2px 6px", borderRadius: 4,
          background: "#1B3568", color: "#A9B7D6", fontWeight: 600,
          letterSpacing: 0.5, textTransform: "uppercase",
        }}>v1.1</span>
      </div>
      <nav style={{ display: "flex", alignItems: "center", gap: 4 }}>
        {items.map((it) => (
          <button key={it.id}
            onClick={() => onNavigate(it.id)}
            style={{
              padding: "8px 14px", borderRadius: 6,
              background: active === it.id ? "#1B3568" : "transparent",
              color: active === it.id ? "white" : "#A9B7D6",
              border: "none", cursor: "pointer", fontFamily: "inherit",
              fontSize: 13, fontWeight: 500,
            }}
          >{it.label}</button>
        ))}
      </nav>

      <div style={{ flex: 1 }} />

      {kpiSummary && (
        <div style={{ display: "flex", alignItems: "center", gap: 18, fontSize: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#15A56C", boxShadow: "0 0 0 3px #15A56C33" }} />
            <span style={{ color: "#A9B7D6" }}>{kpiSummary.machines_running}/{kpiSummary.machines_total} running</span>
          </div>
          <div style={{ width: 1, height: 18, background: "#1B3568" }} />
          <div style={{ display: "flex", alignItems: "center", gap: 6, color: "#A9B7D6" }}>
            <span style={{ color: "white", fontWeight: 600 }}>OEE {kpiSummary.fleet_avg_oee_percent.toFixed(1)}%</span>
          </div>
        </div>
      )}

      {currentUser && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginLeft: 18 }}>
          <div style={{ width: 1, height: 18, background: "#1B3568" }} />
          <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.15, alignItems: "flex-end" }}>
            <span style={{ fontSize: 12.5, fontWeight: 600, color: "white" }}>
              {currentUser.full_name || currentUser.email}
            </span>
            <span style={{ fontSize: 10, color: "#A9B7D6" }}>{currentUser.email}</span>
          </div>
          <span style={{
            padding: "2px 8px", borderRadius: 999,
            background: currentUser.role === "admin" ? "#1E40AF" : "#374151",
            color: "white", fontSize: 10, fontWeight: 700,
            letterSpacing: 0.5, textTransform: "uppercase",
          }}>{currentUser.role}</span>
          <button onClick={onLogout} title="Sign out" style={{
            padding: "6px 10px", borderRadius: 6,
            background: "transparent", color: "#A9B7D6",
            border: "1px solid #1B3568", cursor: "pointer", fontFamily: "inherit",
            fontSize: 11.5, fontWeight: 600,
          }}
            onMouseEnter={(e) => { e.currentTarget.style.color = "white"; e.currentTarget.style.background = "#1B3568"; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = "#A9B7D6"; e.currentTarget.style.background = "transparent"; }}
          >Logout</button>
        </div>
      )}
    </header>
  );
}

function Placeholder({ title, sub }) {
  return (
    <div style={{ padding: "48px 32px" }}>
      <div style={{
        background: "white", border: "1px dashed #DCE2EC", borderRadius: 12,
        padding: 48, textAlign: "center",
      }}>
        <div style={{ fontSize: 12, color: "#6B7280", fontWeight: 600, letterSpacing: 0.6, textTransform: "uppercase" }}>
          Coming in a later screen
        </div>
        <div style={{ fontSize: 22, color: "#0A1F44", fontWeight: 600, marginTop: 8, letterSpacing: -0.4 }}>{title}</div>
        <div style={{ fontSize: 13, color: "#6B7280", marginTop: 6, maxWidth: 480, margin: "6px auto 0" }}>{sub}</div>
      </div>
    </div>
  );
}

function App() {
  const [page, setPage] = useStateApp("overview");
  const [currentMachine, setCurrentMachine] = useStateApp(null);
  const [currentComponent, setCurrentComponent] = useStateApp(null);
  // Set when a deep-link from Machine Detail ("View all →" on Recent
  // Alarms) needs the Alerts screen to mount pre-filtered to a machine.
  // Cleared whenever TopNav switches pages, so coming back to Alerts via
  // the top nav always opens with no filter.
  const [alertsPrefill, setAlertsPrefill] = useStateApp(null);
  const [kpiSummary, setKpiSummary] = useStateApp(null);
  const [chatCollapsed, setChatCollapsed] = useStateApp(false);
  // Hydrate from localStorage so a refreshed tab stays signed-in. Token
  // validation happens implicitly on the next API call — if the JWT is
  // expired, the global 401 handler clears state + fires fhh:auth:expired.
  const [currentUser, setCurrentUser] = useStateApp(() => window.api.auth.getUser());

  // Listen for backend-driven session expiry. The api_client dispatches
  // this event when any request returns token_expired / invalid_token.
  useEffectApp(() => {
    function onExpired() { setCurrentUser(null); }
    window.addEventListener("fhh:auth:expired", onExpired);
    return () => window.removeEventListener("fhh:auth:expired", onExpired);
  }, []);

  // Only fetch screen data once the user is authenticated. Without this
  // gate, /kpis/overview would fire with no token on first render, the
  // backend would 401, and the response would slot into the dashboard
  // *behind* the login screen.
  useEffectApp(() => {
    if (!currentUser) { setKpiSummary(null); return; }
    window.api.get("/kpis/overview").then(setKpiSummary).catch(() => {});
  }, [currentUser]);

  function handleLogout() {
    window.api.auth.logout();
    setCurrentUser(null);
    setKpiSummary(null);
    setPage("overview");
    setCurrentMachine(null);
    setCurrentComponent(null);
  }

  if (!currentUser) {
    return <LoginScreen onLoginSuccess={(u) => setCurrentUser(u)} />;
  }

  const context = {
    current_page: page,
    current_machine_id: currentMachine,
    current_component_id: currentComponent,
    current_sku: null,
    current_market: null,
  };

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column", background: "#F4F6FA" }}>
      <TopNav
        active={page === "machine_detail" ? "overview" : page}
        onNavigate={(p) => { setPage(p); setCurrentMachine(null); setCurrentComponent(null); setAlertsPrefill(null); }}
        kpiSummary={kpiSummary}
        currentUser={currentUser}
        onLogout={handleLogout}
      />

      <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
        {/* Chat sidebar (~30% expanded / ~50px collapsed, LEFT side) */}
        <div style={{
          width: chatCollapsed ? 50 : 400,
          flexShrink: 0, height: "100%",
          transition: "width 220ms cubic-bezier(.4,0,.2,1)",
          overflow: "hidden",
        }}>
          <ChatSidebar
            context={context}
            collapsed={chatCollapsed}
            onToggleCollapse={() => setChatCollapsed((c) => !c)}
          />
        </div>

        {/* Main region (~70%) */}
        <main style={{ flex: 1, minWidth: 0, overflowY: "auto", background: "#F4F6FA" }}>
          {page === "overview" && (
            <OverviewScreen onOpenMachine={(id) => { setCurrentMachine(id); setPage("machine_detail"); }} />
          )}
          {page === "machine_detail" && (
            <MachineDetailScreen
              machineId={currentMachine || "al-nakheel"}
              onBack={() => { setPage("overview"); setCurrentMachine(null); setCurrentComponent(null); }}
              onSelectComponent={(cid) => setCurrentComponent(cid)}
              onViewAllAlerts={(mid) => { setAlertsPrefill(mid); setPage("alerts"); }}
            />
          )}
          {page === "alerts" && (
            <AlertsScreen
              onOpenMachine={(id) => { setCurrentMachine(id); setPage("machine_detail"); }}
              initialMachineFilter={alertsPrefill ? [alertsPrefill] : null}
            />
          )}
          {page === "demand_forecast" && (
            <DemandForecastScreen
              onNavigate={(p) => { setPage(p); setCurrentMachine(null); setCurrentComponent(null); setAlertsPrefill(null); }}
            />
          )}
          {page === "calendar" && <CalendarScreen />}
        </main>
      </div>
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<App />);
