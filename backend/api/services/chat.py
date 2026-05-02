"""Chat service — Anthropic-backed assistant with live tool use.

Architecture
------------
Each user turn enters a tool-use loop:

    1. Send {system, tools, conversation history} to Anthropic.
    2. If the response stop_reason is "tool_use", run every requested tool
       (`backend.api.services.chat_tools.execute_tool`), append the
       assistant's tool_use message and a user tool_result message, and
       go to step 1.
    3. Otherwise, return the final text reply.

The conversation store (`ConversationStore`) keeps only the user/assistant
TEXT history across turns — tool calls live within a single turn.

Security
--------
The API key MUST stay server-side. It is loaded via python-dotenv at
module load time, stripped of whitespace, and is **never** included in
log output, response bodies, or error messages.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Optional

import asyncpg
from dotenv import load_dotenv

# `load_dotenv()` does NOT override variables that are already in
# `os.environ`. On Windows the spawning shell sometimes exports an EMPTY
# `ANTHROPIC_API_KEY` — drop empty/whitespace existing values first so
# the .env entry wins.
for _name in ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"):
    _existing = os.environ.get(_name)
    if _existing is not None and not _existing.strip():
        os.environ.pop(_name, None)

load_dotenv()  # idempotent

log = logging.getLogger("fhh.api.chat")

# ----------------------------------------------------------------------
# API key + model
# ----------------------------------------------------------------------
_RAW_KEY = os.getenv("ANTHROPIC_API_KEY") or ""
ANTHROPIC_API_KEY: str = _RAW_KEY.strip()
ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929").strip()
ANTHROPIC_MAX_TOKENS: int = int(os.getenv("ANTHROPIC_MAX_TOKENS", "1024"))
MAX_TOOL_ROUNDS: int = int(os.getenv("CHAT_MAX_TOOL_ROUNDS", "6"))

if not ANTHROPIC_API_KEY:
    log.warning(
        "ANTHROPIC_API_KEY is not set — POST /chat will return 502 "
        "(chat_unavailable). Add the key to .env and restart the API."
    )


# ----------------------------------------------------------------------
# In-memory conversation store
# ----------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ConversationStore:
    """Thread-safe in-memory conversation store. Replace with Redis later."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._convs: dict[str, dict] = {}

    def get(self, cid: str) -> Optional[dict]:
        with self._lock:
            return self._convs.get(cid)

    def create(self) -> str:
        cid = f"conv-{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._convs[cid] = {
                "conversation_id": cid,
                "created_at": _now_iso(),
                "messages": [],
            }
        return cid

    def append(
        self,
        cid: str,
        role: str,
        content: str,
        data_sources_used: Optional[list[str]] = None,
    ) -> None:
        with self._lock:
            conv = self._convs.get(cid)
            if conv is None:
                conv = {
                    "conversation_id": cid,
                    "created_at": _now_iso(),
                    "messages": [],
                }
                self._convs[cid] = conv
            entry: dict = {
                "role": role,
                "content": content,
                "timestamp": _now_iso(),
            }
            if data_sources_used:
                entry["data_sources_used"] = data_sources_used
            conv["messages"].append(entry)

    def delete(self, cid: str) -> bool:
        with self._lock:
            return self._convs.pop(cid, None) is not None

    def history_for_anthropic(self, cid: str) -> list[dict]:
        """Return the conversation history as Anthropic-shaped messages
        (user/assistant text only — tool rounds aren't persisted)."""
        conv = self.get(cid)
        if not conv:
            return []
        return [
            {"role": m["role"], "content": m["content"]}
            for m in conv["messages"]
            if m["role"] in ("user", "assistant")
        ]


store = ConversationStore()


# ----------------------------------------------------------------------
# System prompt
# ----------------------------------------------------------------------

SYSTEM_PROMPT_BASE = """You are FHH AI, the operations assistant for Fine Hygienic Holding (FHH).

Fleet
-----
FHH operates four Valmet Advantage DCT 200TS tissue paper machines:
  • al-nakheel  — Al Nakheel,  Abu Dhabi, UAE
  • al-bardi    — Al Bardi,    Egypt
  • al-sindian  — Al Sindian,  Egypt
  • al-snobar   — Al Snobar,   Jordan

Each machine has six components, in line order:
  headbox · visconip · yankee · aircap · softreel · rewinder

Demand
------
FHH sells 37 SKUs (categories: tissue, baby_care, adult_care, fine_guard,
wellness, cosmetics) across five MENA markets:
  uae · ksa · jordan · egypt · morocco

Risk tier scheme (always lowercase)
  healthy <30,  watch 30-49,  warning 50-69,  critical 70+
The maintenance model is tuned for high recall on the critical tier.

Available tools
---------------
You have direct read access to the live FHH API via these tools:
  • list_machines                  — fleet snapshot with overall risk per machine
  • get_machine_risk(machine,comp) — exact integer score for one (machine, component)
  • get_machine_detail(machine)    — machine + 6 components + state
  • list_alerts(severity?,machine?,limit?) — active unresolved alerts
  • get_alert(alert_id)            — full detail for one alert
  • get_forecast(market,sku,days?) — Prophet forecast with bands
  • get_demand_drivers(market,sku) — Ramadan / Eid / pre-stockup average lifts
  • get_fleet_kpis                 — fleet-wide KPIs (OEE, alert counts, etc.)

CRITICAL RULE — grounded answers only
-------------------------------------
You MUST call the appropriate tool before answering ANY factual question
about machines, components, alerts, sensors, forecasts, or KPIs. Never
invent or estimate numbers. If a tool returns an error or no data, say
explicitly that you couldn't retrieve the data — never guess. If a
question can be answered from the static fleet/market description above
(e.g. "how many machines are there"), you may answer without a tool, but
prefer a tool whenever the user asks for a current or specific value.

Out of scope (refuse politely, one sentence): pricing in any currency,
weather, currency conversions, personal/HR matters, anything outside
FHH operations data accessible through the tools above.

Output style
------------
  • Reply concisely — 2-4 sentences typical, longer only when synthesising
    multiple data points.
  • Risk scores: integer 0-100 (e.g. "88").
  • Money: USD with K/M shorthand for big numbers (e.g. "$480K", "$1.2M").
  • Percentages: one decimal place with sign (e.g. "+8.4%", "-5.2%").
  • Dates: human-readable (e.g. "Mar 19, 2026").
  • Use markdown bold for the key number when it answers the question.

Pronouns
--------
"this machine", "this SKU", "the current alert" — resolve from the
"Current screen state" hint at the bottom of this prompt. If no hint is
provided, ask which one the user means.
"""


SCREEN_APPENDS: dict[str, str] = {
    "overview": (
        "User is on the fleet Overview screen. They see four machine cards, "
        "the KPI strip, and a critical-alert banner. Help them interpret "
        "fleet health and decide where to drill in."
    ),
    "machine_detail": (
        "User is viewing a specific machine. The screen state below "
        "carries machine_id (and possibly a selected component_id). "
        "Use those when the user says 'this machine' or 'this component'."
    ),
    "alerts": (
        "User is on the Alerts triage screen. Help prioritise, decide "
        "what to acknowledge vs snooze, and explain why an alert fired."
    ),
    "demand_forecast": (
        "User is on the Demand Forecast screen. Help interpret the "
        "Prophet forecast, Ramadan / Eid effects, and SKU/market "
        "comparisons. Forecast accuracy is reported as MAPE (lower is "
        "better; the fleet average across 185 models is ≈4 %)."
    ),
}


def build_system_prompt(
    screen_context: Optional[str], screen_payload: Optional[dict]
) -> str:
    parts = [SYSTEM_PROMPT_BASE]
    if screen_context and screen_context in SCREEN_APPENDS:
        parts.append("Screen context: " + SCREEN_APPENDS[screen_context])
    if screen_payload:
        keep = {
            k: v for k, v in screen_payload.items()
            if k in (
                "current_page", "current_machine_id", "current_component_id",
                "current_sku", "current_market",
            ) and v is not None
        }
        if keep:
            parts.append(f"Current screen state: {keep}")
    return "\n\n".join(parts)


# ----------------------------------------------------------------------
# Cold-start suggested prompts
# ----------------------------------------------------------------------

SUGGESTED_PROMPTS = {
    "overview": [
        "Which machine needs attention first?",
        "Summarize fleet health in one sentence",
        "What's driving the critical alerts?",
    ],
    "machine_detail": [
        "Why is this machine at risk?",
        "What's the recommended action?",
        "How urgent is this — hours or days?",
    ],
    "alerts": [
        "Which alerts should I acknowledge first?",
        "Are any of these duplicates?",
        "Explain the most critical alert",
    ],
    "demand_forecast": [
        "What's driving next month's spike?",
        "Compare UAE vs KSA for this SKU",
        "How does Ramadan affect this forecast?",
    ],
}


def suggested_prompts(
    current_page: Optional[str] = None,
    current_machine_id: Optional[str] = None,
    current_sku: Optional[str] = None,
) -> list[str]:
    return SUGGESTED_PROMPTS.get(current_page or "overview",
                                 SUGGESTED_PROMPTS["overview"])


# ----------------------------------------------------------------------
# Tool-use loop
# ----------------------------------------------------------------------

class ChatUnavailable(Exception):
    """Raised when the Anthropic call fails for any reason. The router
    converts this into a 502 + {"error": "chat_unavailable", ...}."""

    def __init__(self, safe_message: str) -> None:
        super().__init__(safe_message)
        self.safe_message = safe_message


def _block_to_dict(block: Any) -> dict:
    """Convert an Anthropic response block (Pydantic model) to JSON-safe
    dict so we can echo it back as part of the next assistant message."""
    if hasattr(block, "model_dump"):
        return block.model_dump()
    if isinstance(block, dict):
        return dict(block)
    # Last-ditch fallback
    return {"type": getattr(block, "type", "text"),
            "text": getattr(block, "text", str(block))}


async def generate_reply(
    history: list[dict],
    screen_context: Optional[str],
    screen_payload: Optional[dict],
    conn: asyncpg.Connection,
) -> dict:
    """Run the tool-use loop for one user turn. Returns:

        {
          "reply":               final assistant text,
          "data_sources_used":   list of tool names called,
          "suggested_followups": [],   # populated by the router separately if needed
          "usage":               aggregated input/output tokens,
        }
    """
    if not ANTHROPIC_API_KEY:
        raise ChatUnavailable("ANTHROPIC_API_KEY is not configured on the server.")

    try:
        from anthropic import AsyncAnthropic
    except Exception as exc:  # noqa: BLE001
        log.error("anthropic SDK import failed: %s", type(exc).__name__)
        raise ChatUnavailable("AI client unavailable.") from exc

    if not history:
        raise ChatUnavailable("conversation history is empty.")

    # Lazy import to avoid circular: chat_tools imports from services
    from . import chat_tools

    system_prompt = build_system_prompt(screen_context, screen_payload)
    client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    messages: list[dict] = list(history)
    tools_called: list[str] = []
    total_in = total_out = 0

    for round_idx in range(MAX_TOOL_ROUNDS):
        try:
            resp = await client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=ANTHROPIC_MAX_TOKENS,
                system=system_prompt,
                tools=chat_tools.TOOL_SCHEMAS,
                messages=messages,
            )
        except Exception as exc:  # noqa: BLE001
            kind = type(exc).__name__
            log.error("Anthropic call failed (%s) on round %d", kind, round_idx)
            raise ChatUnavailable(f"AI request failed: {kind}") from exc

        total_in += int(getattr(resp.usage, "input_tokens", 0) or 0)
        total_out += int(getattr(resp.usage, "output_tokens", 0) or 0)

        tool_uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]

        # Done?
        if resp.stop_reason != "tool_use" or not tool_uses:
            reply_text = "".join(
                getattr(b, "text", "")
                for b in resp.content
                if getattr(b, "type", "text") == "text"
            ).strip()
            return {
                "reply": reply_text,
                "data_sources_used": tools_called,
                "suggested_followups": [],
                "usage": {"input_tokens": total_in, "output_tokens": total_out},
            }

        # Echo the assistant's tool_use turn back into the message log
        messages.append({
            "role": "assistant",
            "content": [_block_to_dict(b) for b in resp.content],
        })

        # Execute every tool call in parallel-friendly serial order, then
        # send all results in a single user message.
        import json
        tool_results: list[dict] = []
        for tu in tool_uses:
            tu_id = getattr(tu, "id", None) or getattr(tu, "tool_use_id", None) or ""
            tu_name = getattr(tu, "name", "") or ""
            tu_input = dict(getattr(tu, "input", {}) or {})
            try:
                result = await chat_tools.execute_tool(tu_name, tu_input, conn)
                tools_called.append(tu_name)
                content_str = json.dumps(result, default=str)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu_id,
                    "content": content_str,
                })
                log.info("chat tool ok: %s args=%s -> %d chars",
                         tu_name, list(tu_input.keys()), len(content_str))
            except Exception as exc:  # noqa: BLE001
                msg = f"{type(exc).__name__}: {exc}"
                log.warning("chat tool %s failed: %s", tu_name, msg)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu_id,
                    "content": json.dumps({"error": msg}),
                    "is_error": True,
                })

        messages.append({"role": "user", "content": tool_results})

    # Hit max rounds — return whatever we have. Defensive.
    log.warning("chat hit MAX_TOOL_ROUNDS=%d; tools=%s", MAX_TOOL_ROUNDS, tools_called)
    return {
        "reply": (
            "I needed more tool calls than my budget allows. Here's what I "
            "gathered so far — try a more specific question."
        ),
        "data_sources_used": tools_called,
        "suggested_followups": [],
        "usage": {"input_tokens": total_in, "output_tokens": total_out},
    }
