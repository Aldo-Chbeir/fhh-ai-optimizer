// Always-on chat sidebar. Wired to:
//   GET  /chat/suggested-prompts?current_page=overview   (empty state chips)
//   GET  /chat/conversations                              (recent list, last 10)
//   GET  /chat/conversations/{id}                         (reopen + load history)
//   POST /chat                                           (send a turn — backend
//                                                         persists user+assistant
//                                                         and feeds full history
//                                                         back to Claude as memory)
//   DELETE /chat/conversations/{id}                      (delete from list)
// Renders messages, data_sources_used pills, suggested_followups chips,
// and the per-user Recent Chats list.

const { useEffect: useEffectChat, useState: useStateChat, useRef } = React;

// ─── helpers ────────────────────────────────────────────────────────────
function formatRelativeTime(isoOrDate) {
  if (!isoOrDate) return "";
  const t = typeof isoOrDate === "string" ? Date.parse(isoOrDate) : new Date(isoOrDate).getTime();
  if (!Number.isFinite(t)) return "";
  const diffSec = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (diffSec < 60) return "just now";
  const m = Math.round(diffSec / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(diffSec / 3600);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(diffSec / 86400);
  if (d < 30) return `${d}d ago`;
  const mo = Math.round(d / 30);
  if (mo < 12) return `${mo}mo ago`;
  return `${Math.round(d / 365)}y ago`;
}

function truncateText(s, n) {
  if (!s) return "";
  if (s.length <= n) return s;
  return s.slice(0, n - 1).trimEnd() + "…";
}

function SourcePill({ endpoint }) {
  // Compress noisy paths for display while keeping the full path as a tooltip:
  // "machines/al-nakheel/components/yankee/risk-score" → "yankee/risk-score"
  const short = (() => {
    const parts = endpoint.split("/").filter(Boolean);
    if (parts.length <= 2) return endpoint;
    return parts.slice(-2).join("/");
  })();
  return (
    <span title={endpoint} style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      padding: "3px 8px", borderRadius: 6,
      background: "#EEF2F8", color: "#0A1F44",
      fontSize: 11, fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
      fontWeight: 500, cursor: "help",
      border: "1px solid #DCE2EC",
    }}>
      <svg width="9" height="9" viewBox="0 0 12 12" fill="none">
        <circle cx="6" cy="6" r="2" fill="#0A1F44" />
      </svg>
      {short}
    </span>
  );
}

function FollowupChip({ text, onClick }) {
  return (
    <button
      onClick={() => onClick(text)}
      style={{
        textAlign: "left",
        padding: "8px 12px",
        borderRadius: 8,
        background: "white",
        border: "1px solid #DCE2EC",
        color: "#0A1F44",
        fontSize: 12.5, fontWeight: 500,
        cursor: "pointer", fontFamily: "inherit",
        lineHeight: 1.35,
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = "#F4F7FC"; e.currentTarget.style.borderColor = "#0A1F44"; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = "white"; e.currentTarget.style.borderColor = "#DCE2EC"; }}
    >
      {text}
    </button>
  );
}

function UserBubble({ text }) {
  return (
    <div style={{ display: "flex", justifyContent: "flex-end" }}>
      <div style={{
        maxWidth: "85%",
        background: "#0A1F44",
        color: "white",
        padding: "10px 14px",
        borderRadius: "14px 14px 4px 14px",
        fontSize: 13.5, lineHeight: 1.5,
        whiteSpace: "pre-wrap", wordBreak: "break-word",
      }}>{text}</div>
    </div>
  );
}

function AssistantBubble({ msg, onFollowup }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-start" }}>
      <div style={{
        maxWidth: "92%",
        background: "#F4F6FA",
        color: "#1A2438",
        padding: "10px 14px",
        borderRadius: "14px 14px 14px 4px",
        fontSize: 13.5, lineHeight: 1.55,
        whiteSpace: "pre-wrap", wordBreak: "break-word",
      }}>
        {msg.content || <em style={{ color: "#6B7280" }}>thinking…</em>}
      </div>

      {msg.data_sources_used && msg.data_sources_used.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, paddingLeft: 4 }}>
          {msg.data_sources_used.map((s) => <SourcePill key={s} endpoint={s} />)}
        </div>
      )}

      {msg.suggested_followups && msg.suggested_followups.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 4, alignSelf: "stretch" }}>
          <div style={{
            fontSize: 10, color: "#6B7280", fontWeight: 600,
            letterSpacing: 0.5, textTransform: "uppercase", paddingLeft: 4,
          }}>Suggested follow-ups</div>
          {msg.suggested_followups.map((f, i) => (
            <FollowupChip key={i} text={f} onClick={onFollowup} />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Recent Chats list ──────────────────────────────────────────────────
function RecentChatItem({ conv, isActive, onOpen, onDelete }) {
  const [hover, setHover] = useStateChat(false);
  const [trashHover, setTrashHover] = useStateChat(false);

  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => { setHover(false); setTrashHover(false); }}
      onClick={() => onOpen(conv.id)}
      style={{
        position: "relative",
        padding: "8px 10px 8px 12px",
        borderLeft: isActive ? "3px solid #1B3568" : "3px solid transparent",
        background: isActive ? "#F4F7FC" : (hover ? "#F8FAFD" : "transparent"),
        cursor: "pointer",
        display: "flex", flexDirection: "column", gap: 2,
        borderRadius: 0,
      }}
    >
      <div style={{
        fontSize: 12.5, fontWeight: isActive ? 600 : 500, color: "#0A1F44",
        lineHeight: 1.3,
        paddingRight: 22,    // leave room for the trash icon
        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
      }}>{conv.title || "Untitled"}</div>
      <div style={{ fontSize: 10.5, color: "#6B7280", lineHeight: 1.3 }}>
        {conv.message_count} {conv.message_count === 1 ? "msg" : "msgs"} · {formatRelativeTime(conv.updated_at)}
      </div>

      {hover && (
        <button
          aria-label="Delete conversation"
          title="Delete conversation"
          onClick={(e) => { e.stopPropagation(); onDelete(conv); }}
          onMouseEnter={(e) => { e.stopPropagation(); setTrashHover(true); }}
          onMouseLeave={(e) => { e.stopPropagation(); setTrashHover(false); }}
          style={{
            position: "absolute", top: 8, right: 6,
            width: 22, height: 22, borderRadius: 5,
            background: trashHover ? "#FCE3E5" : "transparent",
            border: "none", cursor: "pointer", padding: 0,
            display: "flex", alignItems: "center", justifyContent: "center",
            color: trashHover ? "#B31E2B" : "#9CA3AF",
            transition: "color .12s, background .12s",
          }}
        >
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
            <path d="M3 4 H13 M6 4 V3 a1 1 0 0 1 1-1 h2 a1 1 0 0 1 1 1 V4 M5 4 v9 a1 1 0 0 0 1 1 h4 a1 1 0 0 0 1-1 V4"
              stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>
      )}
    </div>
  );
}

function RecentChatsList({ conversations, loading, error, activeId, onOpen, onDelete, onRetry }) {
  const [open, setOpen] = useStateChat(true);
  const count = conversations?.length || 0;

  return (
    <div style={{
      borderBottom: "1px solid #E5E8EE",
      flexShrink: 0,
      display: "flex", flexDirection: "column",
    }}>
      {/* Section header */}
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        style={{
          padding: "8px 14px",
          background: "transparent", border: "none", cursor: "pointer",
          display: "flex", alignItems: "center", justifyContent: "space-between",
          fontFamily: "inherit",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{
            fontSize: 10, fontWeight: 700, letterSpacing: 0.6,
            textTransform: "uppercase", color: "#6B7280",
          }}>Recent Chats</span>
          {count > 0 && (
            <span style={{
              fontSize: 9.5, fontWeight: 700,
              padding: "1px 6px", borderRadius: 999,
              background: "#EEF1F6", color: "#4B5563", letterSpacing: 0.3,
            }}>{count}</span>
          )}
        </div>
        <svg width="10" height="10" viewBox="0 0 16 16" fill="none"
          style={{ transform: open ? "rotate(90deg)" : "rotate(0deg)", transition: "transform .15s", color: "#9CA3AF" }}>
          <path d="M6 4 L10 8 L6 12" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </button>

      {open && (
        <div style={{
          maxHeight: 220, overflowY: "auto",
          paddingBottom: count > 0 ? 4 : 0,
        }}>
          {loading && (
            <div style={{ fontSize: 11.5, color: "#9CA3AF", padding: "8px 14px" }}>Loading…</div>
          )}
          {error && !loading && (
            <div style={{
              fontSize: 11.5, color: "#7A0F1B",
              padding: "8px 14px",
              display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8,
            }}>
              <span>Couldn't load.</span>
              <button onClick={onRetry} style={{
                fontSize: 11, fontWeight: 600, padding: "3px 8px",
                background: "white", color: "#0A1F44",
                border: "1px solid #DCE2EC", borderRadius: 5, cursor: "pointer",
                fontFamily: "inherit",
              }}>Retry</button>
            </div>
          )}
          {!loading && !error && count === 0 && (
            <div style={{
              fontSize: 11.5, color: "#9CA3AF", padding: "8px 14px",
              fontStyle: "italic",
            }}>No conversations yet. Start a chat below.</div>
          )}
          {!loading && !error && count > 0 && conversations.map((c) => (
            <RecentChatItem
              key={c.id}
              conv={c}
              isActive={c.id === activeId}
              onOpen={onOpen}
              onDelete={onDelete}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ChatSidebar({ context, collapsed, onToggleCollapse }) {
  const [convId, setConvId] = useStateChat(null);
  const [messages, setMessages] = useStateChat([]); // {role, content, data_sources_used?, suggested_followups?, timestamp}
  const [prompts, setPrompts] = useStateChat([]);
  const [draft, setDraft] = useStateChat("");
  const [pending, setPending] = useStateChat(false);
  // Recent Chats list state. Loaded on mount, refreshed after each turn.
  const [conversations, setConversations] = useStateChat([]);
  const [convsLoading, setConvsLoading] = useStateChat(true);
  const [convsError, setConvsError] = useStateChat(null);
  const [historyLoading, setHistoryLoading] = useStateChat(false);
  const scrollRef = useRef(null);

  async function loadConversations() {
    setConvsLoading(true);
    setConvsError(null);
    try {
      const r = await window.api.get("/chat/conversations");
      setConversations(r.conversations || []);
    } catch (e) {
      // 401 will already have triggered fhh:auth:expired via api_client; we
      // just surface a quiet error in the list section so the rest of the
      // sidebar (composer) keeps working.
      setConvsError(e?.message || "Request failed");
      setConversations([]);
    } finally {
      setConvsLoading(false);
    }
  }

  // Hydrate the Recent Chats list once on mount.
  useEffectChat(() => { loadConversations(); }, []);

  // Defensive: if the global auth-expired event ever fires while ChatSidebar
  // is still mounted, blank our state. In normal flow app.jsx unmounts the
  // dashboard on logout so this never runs.
  useEffectChat(() => {
    function reset() {
      setConvId(null);
      setMessages([]);
      setConversations([]);
      setDraft("");
    }
    window.addEventListener("fhh:auth:expired", reset);
    return () => window.removeEventListener("fhh:auth:expired", reset);
  }, []);

  // Load suggested prompts when convo is empty + page context changes
  useEffectChat(() => {
    if (messages.length > 0) return;
    const params = { current_page: context?.current_page };
    if (context?.current_machine_id) params.current_machine_id = context.current_machine_id;
    if (context?.current_component_id) params.current_component_id = context.current_component_id;
    if (context?.current_sku) params.current_sku = context.current_sku;
    window.api
      .get("/chat/suggested-prompts", params)
      .then((r) => setPrompts(r.prompts || []))
      .catch(() => { /* prompts are optional */ });
  }, [context?.current_page, context?.current_machine_id, context?.current_component_id, messages.length]);

  // Listen for fhh:chat:send events fired by buttons elsewhere in the app
  // (e.g. "View all →", "Schedule Maintenance"). Auto-expand if collapsed.
  useEffectChat(() => {
    function handler(e) {
      const txt = (e?.detail || "").trim();
      if (!txt) return;
      if (collapsed) onToggleCollapse && onToggleCollapse();
      send(txt);
    }
    window.addEventListener("fhh:chat:send", handler);
    return () => window.removeEventListener("fhh:chat:send", handler);
  }, [collapsed, convId, pending]);

  // Collapsed view: a 50px vertical strip with an expand button + brand mark
  if (collapsed) {
    return (
      <aside style={{
        width: "100%", height: "100%",
        display: "flex", flexDirection: "column", alignItems: "center",
        background: "white", borderRight: "1px solid #E5E8EE",
        padding: "12px 0",
      }}>
        <button
          onClick={onToggleCollapse}
          aria-label="Expand chat"
          title="Expand chat"
          style={{
            width: 32, height: 32, borderRadius: 8,
            border: "1px solid #DCE2EC", background: "white",
            color: "#0A1F44", cursor: "pointer", fontFamily: "inherit",
            display: "flex", alignItems: "center", justifyContent: "center",
            transition: "background .15s, border-color .15s",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = "#F4F7FC"; e.currentTarget.style.borderColor = "#0A1F44"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "white"; e.currentTarget.style.borderColor = "#DCE2EC"; }}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
            <path d="M6 4 L10 8 L6 12" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>
        <div style={{
          marginTop: 14,
          width: 30, height: 30, borderRadius: 8,
          background: "linear-gradient(135deg, #0A1F44 0%, #1B3568 100%)",
          color: "white",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 12, fontWeight: 700, letterSpacing: 0.5,
        }}>FH</div>
        <div style={{
          marginTop: 12, fontSize: 11, color: "#6B7280", fontWeight: 600,
          letterSpacing: 1, textTransform: "uppercase",
          writingMode: "vertical-rl", transform: "rotate(180deg)",
          whiteSpace: "nowrap",
        }}>Ask FHH AI</div>
        {messages.length > 0 && (
          <div style={{
            marginTop: 10,
            width: 8, height: 8, borderRadius: "50%",
            background: "#15A56C",
            boxShadow: "0 0 0 3px #15A56C33",
          }} title={`${messages.length} messages`} />
        )}
      </aside>
    );
  }

  async function send(text) {
    const trimmed = (text ?? draft).trim();
    if (!trimmed || pending) return;
    setDraft("");
    const userMsg = { role: "user", content: trimmed, timestamp: new Date().toISOString() };
    setMessages((m) => [...m, userMsg]);
    setPending(true);
    try {
      const r = await window.api.post("/chat", {
        message: trimmed,
        conversation_id: convId,
        context: context || { current_page: "overview" },
      });
      if (!convId) setConvId(r.conversation_id);
      setMessages((m) => [...m, {
        role: "assistant",
        content: r.reply,
        data_sources_used: r.data_sources_used,
        suggested_followups: r.suggested_followups,
        timestamp: r.timestamp,
      }]);
      // Refresh the Recent Chats list so titles/counts/order reflect this
      // turn. Fire-and-forget — failure here doesn't change the chat output.
      loadConversations();
    } catch (e) {
      let content;
      if (e.networkError && (e.message || "").includes("timed out")) {
        content = "The assistant is taking longer than expected. Please try again.";
      } else if (e.status >= 500) {
        content = "The server hit an error. Please try again.";
      } else {
        content = "Sorry — chat is temporarily unavailable. Please try again.";
      }
      setMessages((m) => [...m, {
        role: "assistant",
        content,
        data_sources_used: [],
        suggested_followups: [],
        timestamp: new Date().toISOString(),
      }]);
    } finally {
      setPending(false);
    }
  }

  // "+ New chat" — start a fresh conversation. Does NOT delete the
  // previous one; that's now what the trash icon in the Recent Chats
  // list is for. The previous conversation stays in the list with full
  // history available to reopen.
  function newChat() {
    setConvId(null);
    setMessages([]);
  }

  async function openConversation(id) {
    if (id === convId || pending) return;
    setHistoryLoading(true);
    try {
      const r = await window.api.get(`/chat/conversations/${id}`);
      setConvId(r.id);
      // Map backend message rows → the local bubble shape. The DB stores
      // user + assistant rows in chronological order; data_sources_used
      // is JSONB on the assistant rows.
      const mapped = (r.messages || []).map((m) => ({
        role: m.role,
        content: m.content,
        data_sources_used: m.data_sources_used || [],
        suggested_followups: [],
        timestamp: m.created_at,
      }));
      setMessages(mapped);
    } catch (e) {
      // 404 means the conv was deleted server-side (or by another tab) —
      // re-sync the list and reset to a new chat.
      console.warn("[chat] openConversation failed:", e?.message || e);
      loadConversations();
      newChat();
    } finally {
      setHistoryLoading(false);
    }
  }

  async function deleteConversation(conv) {
    const ok = window.confirm(
      `Delete this conversation? This cannot be undone.\n\n"${conv.title || "Untitled"}"`
    );
    if (!ok) return;
    try {
      await window.api.del(`/chat/conversations/${conv.id}`);
    } catch (e) {
      console.warn("[chat] delete failed:", e?.message || e);
      // Fall through — refresh the list anyway in case the row is gone
      // server-side and we just hit a transient network blip.
    }
    setConversations((prev) => prev.filter((c) => c.id !== conv.id));
    if (conv.id === convId) {
      // Active conversation was deleted — drop the user back to a fresh
      // chat composer.
      newChat();
    }
  }

  return (
    <aside style={{
      width: "100%", height: "100%",
      display: "flex", flexDirection: "column",
      background: "white",
      borderRight: "1px solid #E5E8EE",
    }}>
      {/* Header */}
      <header style={{
        padding: "16px 20px",
        borderBottom: "1px solid #E5E8EE",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 30, height: 30, borderRadius: 8,
            background: "linear-gradient(135deg, #0A1F44 0%, #1B3568 100%)",
            color: "white",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 13, fontWeight: 700, letterSpacing: 0.5,
          }}>FH</div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, color: "#0A1F44", lineHeight: 1.2 }}>Ask FHH AI</div>
            <div style={{ fontSize: 11, color: "#6B7280", lineHeight: 1.2 }}>
              {convId ? "conversation active" : "ready"}
            </div>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button
            onClick={onToggleCollapse}
            aria-label="Collapse chat"
            title="Collapse chat"
            style={{
              width: 28, height: 28, borderRadius: 6,
              border: "1px solid #DCE2EC", background: "white",
              color: "#0A1F44", cursor: "pointer", fontFamily: "inherit",
              display: "flex", alignItems: "center", justifyContent: "center",
              transition: "background .15s, border-color .15s",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "#F4F7FC"; e.currentTarget.style.borderColor = "#0A1F44"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "white"; e.currentTarget.style.borderColor = "#DCE2EC"; }}
          >
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
              <path d="M10 4 L6 8 L10 12" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </button>
          <button
            onClick={newChat}
            style={{
              padding: "6px 12px",
              borderRadius: 6,
              border: "1px solid #DCE2EC",
              background: "white",
              color: "#0A1F44",
              fontSize: 12, fontWeight: 600,
              cursor: "pointer", fontFamily: "inherit",
              transition: "background .15s",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "#F4F7FC"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "white"; }}
          >+ New chat</button>
        </div>
      </header>

      {/* Recent Chats — collapsible per-user list. Empty when the user
          has never sent anything. Loads on mount + after every reply. */}
      <RecentChatsList
        conversations={conversations}
        loading={convsLoading}
        error={convsError}
        activeId={convId}
        onOpen={openConversation}
        onDelete={deleteConversation}
        onRetry={loadConversations}
      />

      {/* Messages / empty state */}
      <div ref={scrollRef} style={{
        flex: 1, overflowY: "auto",
        padding: "18px 18px 12px",
        display: "flex", flexDirection: "column", gap: 14,
      }}>
        {messages.length === 0 ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 8 }}>
            <div style={{
              padding: "16px 16px",
              background: "linear-gradient(180deg, #F4F7FC 0%, #FFFFFF 100%)",
              border: "1px solid #E5E8EE",
              borderRadius: 10,
            }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: "#0A1F44", marginBottom: 4 }}>
                Hi — I'm your FHH AI assistant.
              </div>
              <div style={{ fontSize: 12.5, color: "#4B5563", lineHeight: 1.5 }}>
                Ask me anything about your machines, alerts, or demand forecasts. I read live data — I don't make numbers up.
              </div>
            </div>
            {prompts.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <div style={{
                  fontSize: 10, color: "#6B7280", fontWeight: 600,
                  letterSpacing: 0.5, textTransform: "uppercase", marginBottom: 2,
                }}>Try one of these</div>
                {prompts.map((p, i) => (
                  <FollowupChip key={i} text={p} onClick={(t) => send(t)} />
                ))}
              </div>
            )}
          </div>
        ) : (
          <>
            {messages.map((m, i) => m.role === "user"
              ? <UserBubble key={i} text={m.content} />
              : <AssistantBubble key={i} msg={m} onFollowup={(t) => send(t)} />
            )}
            {pending && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, color: "#6B7280" }}>
                <div className="fhh-dots"><span></span><span></span><span></span></div>
                <span style={{ fontSize: 12 }}>FHH AI is reading live data…</span>
              </div>
            )}
          </>
        )}
      </div>

      {/* Input */}
      <div style={{
        padding: "12px 14px 14px",
        borderTop: "1px solid #E5E8EE",
        background: "#FBFCFE",
        flexShrink: 0,
      }}>
        <div style={{
          display: "flex", alignItems: "flex-end", gap: 8,
          background: "white",
          border: "1px solid #DCE2EC",
          borderRadius: 10,
          padding: "6px 6px 6px 12px",
        }}>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="Ask FHH AI..."
            rows={1}
            style={{
              flex: 1, resize: "none",
              border: "none", outline: "none",
              fontFamily: "inherit", fontSize: 13.5, lineHeight: 1.5,
              padding: "8px 0", background: "transparent",
              color: "#0A1F44",
              maxHeight: 120,
            }}
          />
          <button
            onClick={() => send()}
            disabled={!draft.trim() || pending}
            style={{
              width: 34, height: 34, borderRadius: 8,
              border: "none", flexShrink: 0,
              background: draft.trim() && !pending ? "#0A1F44" : "#CBD2DC",
              color: "white", cursor: draft.trim() && !pending ? "pointer" : "default",
              display: "flex", alignItems: "center", justifyContent: "center",
              transition: "background .15s",
            }}
            aria-label="Send"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <path d="M2 8L14 2L8 14L7 9L2 8Z" stroke="white" strokeWidth="1.5" strokeLinejoin="round" fill="none"/>
            </svg>
          </button>
        </div>
        <div style={{ fontSize: 10.5, color: "#9CA3AF", marginTop: 6, textAlign: "center" }}>
          Powered by Claude · Reads live data via the FHH API
        </div>
      </div>
    </aside>
  );
}

Object.assign(window, { ChatSidebar });
