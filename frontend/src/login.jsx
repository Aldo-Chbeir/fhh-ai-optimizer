// FHH AI Optimizer — login screen.
//
// Standalone full-viewport component rendered by app.jsx whenever there's no
// authenticated user in localStorage. On a successful POST /auth/login the
// JWT + user are persisted via window.api.auth and onLoginSuccess(user) is
// called so the app shell can swap in the dashboard.
//
// Styling matches the rest of the app: navy/teal palette, Inter font,
// inline styles, no external CSS framework. Same modal/card visual language
// as calendar.jsx EventDetailModal.

const { useState: useStateLogin } = React;

function LoginScreen({ onLoginSuccess }) {
  const [email, setEmail] = useStateLogin("");
  const [password, setPassword] = useStateLogin("");
  const [loading, setLoading] = useStateLogin(false);
  const [error, setError] = useStateLogin(null);

  async function handleSubmit(e) {
    e?.preventDefault?.();
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      const resp = await window.api.post("/auth/login", {
        email: email.trim(),
        password,
      });
      window.api.auth.setToken(resp.access_token);
      window.api.auth.setUser(resp.user);
      if (onLoginSuccess) onLoginSuccess(resp.user);
    } catch (err) {
      // network failures don't carry a body; HTTP failures do
      if (err && err.networkError) {
        setError("Couldn't connect. Is the backend running?");
      } else if (err && err.body && err.body.error && err.body.error.message) {
        setError(err.body.error.message);
      } else {
        setError("Sign in failed. Please try again.");
      }
      setLoading(false);
    }
  }

  return (
    <div style={{
      minHeight: "100vh", width: "100vw",
      display: "flex", alignItems: "center", justifyContent: "center",
      padding: 24,
      background: "linear-gradient(135deg, #0A1F44 0%, #1B3568 50%, #E8EEF8 100%)",
    }}>
      <div style={{
        background: "white", borderRadius: 14, width: 420, maxWidth: "100%",
        padding: "36px 36px 28px",
        boxShadow: "0 24px 60px rgba(10,31,68,0.30)",
        display: "flex", flexDirection: "column", gap: 18,
      }}>
        {/* Brand */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 9,
            background: "linear-gradient(135deg, #00A865 0%, #15A56C 100%)",
            color: "white",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 16, fontWeight: 700,
          }}>F</div>
          <div>
            <div style={{ fontSize: 20, fontWeight: 700, color: "#0A1F44", letterSpacing: -0.4 }}>
              FHH AI Optimizer
            </div>
            <div style={{ fontSize: 12, color: "#6B7280", marginTop: 2 }}>
              Sign in to your operations dashboard
            </div>
          </div>
        </div>

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Field label="Email">
            <input
              type="email"
              autoFocus
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="your.name@fhh.test"
              style={inputStyle}
            />
          </Field>
          <Field label="Password">
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              style={inputStyle}
            />
          </Field>

          {error && (
            <div style={{
              background: "#FCE3E5", border: "1px solid #F5B5BB",
              color: "#7A0F1B", padding: "10px 12px", borderRadius: 8,
              fontSize: 13, lineHeight: 1.4,
            }}>{error}</div>
          )}

          <button
            type="submit"
            disabled={loading || !email || !password}
            style={{
              padding: "11px 14px", borderRadius: 8,
              background: loading ? "#1B3568" : "#0A1F44",
              color: "white", border: "none",
              fontSize: 14, fontWeight: 600, cursor: loading ? "wait" : "pointer",
              fontFamily: "inherit",
              opacity: (!email || !password) && !loading ? 0.55 : 1,
              transition: "background 120ms",
              marginTop: 4,
            }}
            onMouseEnter={(e) => { if (!loading) e.currentTarget.style.background = "#1B3568"; }}
            onMouseLeave={(e) => { if (!loading) e.currentTarget.style.background = "#0A1F44"; }}
          >
            {loading ? "Signing in…" : "Sign In"}
          </button>
        </form>

        <div style={{
          fontSize: 11.5, color: "#9CA3AF",
          paddingTop: 10, borderTop: "1px solid #F0F2F6", textAlign: "center",
        }}>
          Demo accounts: <span style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", color: "#6B7280" }}>aldo@fhh.test / demo1234</span>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      <span style={{
        fontSize: 11, fontWeight: 600, color: "#4B5563",
        letterSpacing: 0.4, textTransform: "uppercase",
      }}>{label}</span>
      {children}
    </label>
  );
}

const inputStyle = {
  padding: "10px 12px",
  border: "1px solid #DCE2EC",
  borderRadius: 8,
  fontSize: 14,
  fontFamily: "inherit",
  color: "#0A1F44",
  outline: "none",
  background: "white",
};

Object.assign(window, { LoginScreen });
