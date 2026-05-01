// Always-on chat sidebar. Wired to:
//   GET  /chat/suggested-prompts?current_page=overview   (empty state chips)
//   POST /chat                                           (on submit)
//   DELETE /chat/conversations/{id}                      ("+ New chat")
// Reuses conversation_id across turns within a session.
// Renders messages, data_sources_used pills, and suggested_followups chips.

const { useEffect: useEffectChat, useState: useStateChat, useRef } = React;

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

function ChatSidebar({ context, collapsed, onToggleCollapse }) {
  const [convId, setConvId] = useStateChat(null);
  const [messages, setMessages] = useStateChat([]); // {role, content, data_sources_used?, suggested_followups?, timestamp}
  const [prompts, setPrompts] = useStateChat([]);
  const [draft, setDraft] = useStateChat("");
  const [pending, setPending] = useStateChat(false);
  const scrollRef = useRef(null);

  // Load suggested prompts when convo is empty + page context changes
  useEffectChat(() => {
    if (messages.length > 0) return;
    const params = { current_page: context?.current_page };
    if (context?.current_machine_id) params.current_machine_id = context.current_machine_id;
    if (context?.current_component_id) params.current_component_id = context.current_component_id;
    if (context?.current_sku) params.current_sku = context.current_sku;
    window.api
      .get("/chat/suggested-prompts", params)
      .then((r) => setPrompts(r.prompts || []));
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
    } catch (e) {
      setMessages((m) => [...m, {
        role: "assistant",
        content: "Sorry — chat is temporarily unavailable. Please try again.",
        data_sources_used: [],
        suggested_followups: [],
        timestamp: new Date().toISOString(),
      }]);
    } finally {
      setPending(false);
    }
  }

  async function newChat() {
    if (convId) await window.api.del(`/chat/conversations/${convId}`);
    setConvId(null);
    setMessages([]);
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
