// FHH AI Optimizer — live API client.
//
// Drop-in replacement for the previous `mock_data.jsx`. Exposes the same
// `window.api.{get, post, del, patch, chat}` shape so every screen file
// already on disk works without modification.
//
// All requests:
//   - hit `${window.API_BASE_URL || "http://localhost:8000"}` + path
//   - serialise query params via URLSearchParams
//   - parse JSON responses
//   - throw a structured Error on HTTP >= 400 (with .status / .body / .endpoint)
//   - throw a network-flagged Error on connection failure (.networkError = true)
//   - abort after 60 s via AbortController (chat with multi-tool replies
//     can run 20+ s; other endpoints are sub-second so the ceiling is fine)

(function () {
  const DEFAULT_BASE = "http://localhost:8000";
  const TIMEOUT_MS = 60000;

  // localStorage keys for the JWT bearer token + cached user profile.
  // Both are cleared by api.auth.logout() and by the global 401 handler
  // when the backend returns token_expired / invalid_token.
  const TOKEN_KEY = "fhh_jwt";
  const USER_KEY = "fhh_user";

  function baseUrl() {
    return (window.API_BASE_URL || DEFAULT_BASE).replace(/\/$/, "");
  }

  function buildQuery(params) {
    if (!params || Object.keys(params).length === 0) return "";
    const usp = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null) continue;
      usp.append(k, String(v));
    }
    const s = usp.toString();
    return s ? "?" + s : "";
  }

  // ─── auth helpers ────────────────────────────────────────────────────
  // Synchronous wrappers around localStorage so screens can read without
  // awaiting. Failures are silenced (incognito / disabled storage) so the
  // app still renders the login form instead of crashing.
  const auth = {
    getToken() {
      try { return localStorage.getItem(TOKEN_KEY); } catch (_) { return null; }
    },
    setToken(token) {
      try { localStorage.setItem(TOKEN_KEY, token); } catch (_) { /* ignore */ }
    },
    clearToken() {
      try { localStorage.removeItem(TOKEN_KEY); } catch (_) { /* ignore */ }
    },
    getUser() {
      try {
        const raw = localStorage.getItem(USER_KEY);
        return raw ? JSON.parse(raw) : null;
      } catch (_) { return null; }
    },
    setUser(user) {
      try { localStorage.setItem(USER_KEY, JSON.stringify(user)); } catch (_) { /* ignore */ }
    },
    clearUser() {
      try { localStorage.removeItem(USER_KEY); } catch (_) { /* ignore */ }
    },
    logout() {
      auth.clearToken();
      auth.clearUser();
    },
  };

  async function fetchJson(method, path, { params, body, headers } = {}) {
    const url = baseUrl() + path + buildQuery(params);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);

    // Attach Authorization automatically when we have a token. Endpoints
    // that don't require auth (/auth/login, the bootstrap /auth/register,
    // /health) simply ignore the header on the backend, so unconditional
    // attachment is safe and keeps this layer dumb.
    const token = auth.getToken();
    const init = {
      method,
      headers: {
        "Accept": "application/json",
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(token ? { "Authorization": `Bearer ${token}` } : {}),
        ...(headers || {}),
      },
      signal: ctrl.signal,
    };
    if (body !== undefined) init.body = JSON.stringify(body);

    let resp;
    try {
      resp = await fetch(url, init);
    } catch (e) {
      clearTimeout(timer);
      const err = new Error(
        e.name === "AbortError"
          ? `Request timed out after ${TIMEOUT_MS / 1000}s: ${method} ${path}`
          : `Network error contacting ${path}: ${e.message}`
      );
      err.networkError = true;
      err.endpoint = path;
      throw err;
    }
    clearTimeout(timer);

    let parsed = null;
    const text = await resp.text();
    if (text) {
      try { parsed = JSON.parse(text); }
      catch (_) { parsed = text; }
    }

    if (!resp.ok) {
      // Global session-expiry handling: if the backend tells us the token
      // is expired or invalid, blow away local auth state and let the app
      // shell react via the "fhh:auth:expired" event. We deliberately do
      // NOT react to invalid_credentials / auth_required — those are
      // expected on the login form itself and the user is already there.
      const code = parsed && parsed.error && parsed.error.code;
      if (resp.status === 401 && (code === "token_expired" || code === "invalid_token")) {
        auth.logout();
        try { window.dispatchEvent(new CustomEvent("fhh:auth:expired")); } catch (_) { /* ignore */ }
      }

      const err = new Error(
        `${method} ${path} failed (${resp.status}): ${
          (parsed && parsed.error && parsed.error.message) ||
          (typeof parsed === "string" ? parsed : "request failed")
        }`
      );
      err.status = resp.status;
      err.body = parsed;
      err.endpoint = path;
      throw err;
    }
    return parsed;
  }

  window.api = {
    async get(path, params) {
      return fetchJson("GET", path, { params });
    },
    async post(path, body) {
      return fetchJson("POST", path, { body });
    },
    async patch(path, body) {
      return fetchJson("PATCH", path, { body });
    },
    async del(path) {
      return fetchJson("DELETE", path);
    },
    /**
     * Chat helper — convenience wrapper around POST /chat.
     *
     * @param {Array<{role, content}>} messageHistory  Full multi-turn history
     *        (only the LAST user turn is shipped to the backend; backend
     *        rebuilds context from `conversation_id`). Each entry must have
     *        role: "user" | "assistant" and content: string.
     * @param {{current_page, current_machine_id?, current_component_id?, current_sku?, current_market?}} screenContext
     * @param {object|null} screenPayload  Optional extra screen state.
     * @returns {Promise<{conversation_id, reply, data_sources_used, suggested_followups, timestamp}>}
     */
    async chat(messageHistory, screenContext, screenPayload) {
      const last = (messageHistory || []).filter((m) => m.role === "user").slice(-1)[0];
      if (!last) throw new Error("chat() requires at least one user message in history");
      const body = {
        message: last.content,
        conversation_id: screenPayload?.conversation_id || null,
        context: screenContext || { current_page: "overview" },
      };
      return fetchJson("POST", "/chat", { body });
    },
    auth,
  };

  // Light log so it's obvious in DevTools that the live client is wired
  // (helpful when the user toggles between mock and live during dev).
  // eslint-disable-next-line no-console
  console.info(`[fhh] api_client.jsx loaded — base ${baseUrl()}`);
})();
