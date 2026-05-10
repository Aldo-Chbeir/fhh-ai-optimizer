// FHH AI Optimizer — "Log Maintenance Work" modal.
//
// Used from two entry points:
//   1. MachineDetailScreen — "+ Log Maintenance" button on the
//      Maintenance History panel. Opens with `machineId` pre-filled and
//      a component dropdown populated from the machine's components.
//   2. CalendarScreen      — same modal, but `machineId` empty so the
//      user picks the machine first.
//
// Posts to:
//   POST /machines/{machine_id}/maintenance-entries
//
// Styling matches ScheduleOrderModal (frontend/src/demand_forecast.jsx) —
// same backdrop, card width, button styles. No external CSS.

const { useState: useStateMaint, useEffect: useEffectMaint } = React;

const MAINT_TYPES = [
  { id: "preventive", label: "Preventive" },
  { id: "corrective", label: "Corrective" },
  { id: "predictive", label: "Predictive" },
  { id: "inspection", label: "Inspection" },
];

// Default to "now" formatted for an <input type="datetime-local">. The
// browser displays in local time but submits a string with no offset, so
// we slice to YYYY-MM-DDTHH:mm. Backend coerces to TIMESTAMPTZ.
function nowForInput() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
         `T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const MAINT_MACHINE_OPTIONS = [
  { id: "al-nakheel", label: "Al Nakheel · Abu Dhabi, UAE" },
  { id: "al-bardi",   label: "Al Bardi · Egypt" },
  { id: "al-sindian", label: "Al Sindian · Egypt" },
  { id: "al-snobar",  label: "Al Snobar · Jordan" },
];

const MAINT_COMPONENT_ORDER = [
  "headbox", "visconip", "yankee", "aircap", "softreel", "rewinder",
];

function MaintenanceEntryModal({
  machineId: initialMachineId,        // optional — pre-fills + locks if set
  machineLabel,                        // optional — shown in subtitle
  components,                          // optional — list of {component_id, name}
  onClose,
  onSubmitted,                         // called with the saved entry on 201
}) {
  const lockedMachine = !!initialMachineId;
  const [machineId, setMachineId]       = useStateMaint(initialMachineId || "");
  const [maintType, setMaintType]       = useStateMaint("preventive");
  const [componentId, setComponentId]   = useStateMaint("");
  const [technician, setTechnician]     = useStateMaint("");
  const [description, setDescription]   = useStateMaint("");
  const [costUsd, setCostUsd]           = useStateMaint("");
  const [duration, setDuration]         = useStateMaint("");
  const [performedAt, setPerformedAt]   = useStateMaint(nowForInput());
  const [error, setError]               = useStateMaint(null);
  const [submitting, setSubmitting]     = useStateMaint(false);

  // If the parent didn't pass `components`, fetch them when machineId is
  // chosen so the component dropdown still populates from the live API.
  const [fetchedComponents, setFetchedComponents] = useStateMaint(null);
  useEffectMaint(() => {
    if (components || !machineId) { setFetchedComponents(null); return; }
    let cancelled = false;
    window.api.get(`/machines/${machineId}/components`)
      .then((r) => { if (!cancelled) setFetchedComponents(r.components || []); })
      .catch(() => { /* leave dropdown empty */ });
    return () => { cancelled = true; };
  }, [machineId, components]);

  const compOptions = (components || fetchedComponents || []).slice().sort((a, b) => {
    const ai = MAINT_COMPONENT_ORDER.indexOf(a.component_id);
    const bi = MAINT_COMPONENT_ORDER.indexOf(b.component_id);
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  });

  const inputStyle = {
    padding: "8px 10px", border: "1px solid #DCE2EC", borderRadius: 6,
    background: "white", fontSize: 13, color: "#0A1F44", fontFamily: "inherit",
    outline: "none", width: "100%",
  };

  function handleSubmit() {
    if (submitting) return;
    if (!machineId) { setError("Please pick a machine."); return; }
    if (!description.trim()) { setError("Work description is required."); return; }
    if (!technician.trim())  { setError("Technician name is required."); return; }
    setError(null);
    setSubmitting(true);
    const body = {
      maintenance_type: maintType,
      work_description: description.trim(),
      technician_name:  technician.trim(),
    };
    if (componentId) body.component_id = componentId;
    if (costUsd !== "")  body.cost_usd       = Number(costUsd);
    if (duration !== "") body.duration_hours = Number(duration);
    if (performedAt) {
      // datetime-local has no timezone; backend interprets as UTC. Append
      // ":00Z" so we ship a valid ISO 8601 with explicit zulu suffix.
      body.performed_at = performedAt.length === 16
        ? performedAt + ":00Z"
        : performedAt;
    }

    window.api.post(`/machines/${machineId}/maintenance-entries`, body)
      .then((entry) => {
        setSubmitting(false);
        if (onSubmitted) onSubmitted(entry);
        if (onClose) onClose();
      })
      .catch((e) => {
        setSubmitting(false);
        setError(e?.body?.error?.message || e?.message || "Failed to log entry.");
      });
  }

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, zIndex: 100,
      background: "rgba(10,31,68,0.45)",
      display: "flex", alignItems: "center", justifyContent: "center",
      padding: 24,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderRadius: 12, width: 520, maxWidth: "100%",
        padding: "22px 24px", boxShadow: "0 20px 60px rgba(10,31,68,0.25)",
        display: "flex", flexDirection: "column", gap: 14,
        maxHeight: "92vh", overflowY: "auto",
      }}>
        {/* Header */}
        <div>
          <span style={{
            display: "inline-block",
            background: "#0E7490", color: "white",
            fontSize: 11, fontWeight: 700, letterSpacing: 0.4,
            textTransform: "uppercase",
            padding: "3px 10px", borderRadius: 999, marginBottom: 8,
          }}>Log maintenance work</span>
          <div style={{ fontSize: 18, fontWeight: 600, color: "#0A1F44",
            letterSpacing: -0.3 }}>Record a completed job</div>
          {(machineLabel || lockedMachine) && (
            <div style={{ fontSize: 12.5, color: "#6B7280", marginTop: 2 }}>
              {machineLabel || machineId}
            </div>
          )}
        </div>

        {/* Machine picker — only when not locked */}
        {!lockedMachine && (
          <Field label="Machine">
            <select value={machineId} onChange={(e) => setMachineId(e.target.value)}
              style={inputStyle}>
              <option value="">— select a machine —</option>
              {MAINT_MACHINE_OPTIONS.map((m) => (
                <option key={m.id} value={m.id}>{m.label}</option>
              ))}
            </select>
          </Field>
        )}

        {/* Type radio buttons */}
        <Field label="Type">
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {MAINT_TYPES.map((t) => (
              <button key={t.id} type="button"
                onClick={() => setMaintType(t.id)}
                style={{
                  padding: "6px 12px", borderRadius: 6,
                  border: "1px solid " + (maintType === t.id ? "#0A1F44" : "#DCE2EC"),
                  background: maintType === t.id ? "#0A1F44" : "white",
                  color: maintType === t.id ? "white" : "#0A1F44",
                  fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit",
                }}
              >{t.label}</button>
            ))}
          </div>
        </Field>

        {/* Component (optional) */}
        <Field label="Component (optional)">
          <select value={componentId} onChange={(e) => setComponentId(e.target.value)}
            style={inputStyle} disabled={!machineId && !lockedMachine}>
            <option value="">— machine-wide / no specific component —</option>
            {compOptions.map((c) => (
              <option key={c.component_id} value={c.component_id}>
                {c.name || c.component_id}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Technician name">
          <input type="text" value={technician}
            onChange={(e) => setTechnician(e.target.value)}
            placeholder="e.g. M. Khalil"
            style={inputStyle} />
        </Field>

        <Field label="Work description">
          <textarea value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            placeholder="What was inspected, replaced, or repaired?"
            style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit", lineHeight: 1.4 }} />
        </Field>

        <div style={{ display: "flex", gap: 12 }}>
          <Field label="Cost (USD, optional)" style={{ flex: 1 }}>
            <input type="number" min="0" step="0.01" value={costUsd}
              onChange={(e) => setCostUsd(e.target.value)}
              placeholder="0.00"
              style={inputStyle} />
          </Field>
          <Field label="Duration (hours, optional)" style={{ flex: 1 }}>
            <input type="number" min="0" step="0.25" value={duration}
              onChange={(e) => setDuration(e.target.value)}
              placeholder="0.0"
              style={inputStyle} />
          </Field>
        </div>

        <Field label="Performed at">
          <input type="datetime-local" value={performedAt}
            onChange={(e) => setPerformedAt(e.target.value)}
            style={inputStyle} />
        </Field>

        {error && (
          <div style={{
            padding: "8px 12px", background: "#FEF2F2", border: "1px solid #FCA5A5",
            borderRadius: 6, fontSize: 12.5, color: "#991B1B",
          }}>{error}</div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 4 }}>
          <button onClick={onClose} disabled={submitting} style={{
            padding: "8px 14px", borderRadius: 7,
            border: "1px solid #DCE2EC", background: "white", color: "#0A1F44",
            fontSize: 13, fontWeight: 600,
            cursor: submitting ? "not-allowed" : "pointer", fontFamily: "inherit",
            opacity: submitting ? 0.5 : 1,
          }}>Cancel</button>
          <button onClick={handleSubmit} disabled={submitting} style={{
            padding: "8px 14px", borderRadius: 7,
            border: "none", background: submitting ? "#1B3568" : "#0A1F44", color: "white",
            fontSize: 13, fontWeight: 600,
            cursor: submitting ? "wait" : "pointer", fontFamily: "inherit",
          }}>{submitting ? "Logging…" : "Log Entry"}</button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children, style }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4, ...(style || {}) }}>
      <span style={{ fontSize: 12, fontWeight: 600, color: "#4B5563" }}>{label}</span>
      {children}
    </label>
  );
}

Object.assign(window, { MaintenanceEntryModal });
