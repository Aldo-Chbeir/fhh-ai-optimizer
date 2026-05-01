"""Chat service — Anthropic-backed assistant.

Architecture
------------
The contract's POST /chat carries a single user `message` per turn plus a
`conversation_id`. We keep a server-side `ConversationStore` so we can
rebuild the multi-turn `messages` array Anthropic expects, then call
`Anthropic.messages.create()` with a system prompt selected by
`context.current_page`.

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
from typing import Optional

from dotenv import load_dotenv

# `load_dotenv()` does NOT override variables that are already in
# `os.environ`. On Windows the spawning shell sometimes exports an EMPTY
# `ANTHROPIC_API_KEY` (e.g. when a previous shell set it without a value),
# which would beat the .env file. Drop empty/whitespace existing values
# first so the .env entry wins.
for _name in ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"):
    _existing = os.environ.get(_name)
    if _existing is not None and not _existing.strip():
        os.environ.pop(_name, None)

load_dotenv()  # idempotent; now .env values fill in missing keys

log = logging.getLogger("fhh.api.chat")

# ----------------------------------------------------------------------
# API key loading — strip whitespace defensively
# ----------------------------------------------------------------------
_RAW_KEY = os.getenv("ANTHROPIC_API_KEY") or ""
ANTHROPIC_API_KEY: str = _RAW_KEY.strip()
ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929").strip()
ANTHROPIC_MAX_TOKENS: int = int(os.getenv("ANTHROPIC_MAX_TOKENS", "1024"))

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
        (excluding the assistant's previous data_sources/followups metadata)."""
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
# System prompts — base + per-screen append
# ----------------------------------------------------------------------

SYSTEM_PROMPT_BASE = (
    "You are the FHH AI Optimizer assistant. FHH operates four "
    "Valmet Advantage DCT 200TS tissue machines: Al-Nakheel (Abu Dhabi), "
    "Al-Bardi (Egypt), Al-Sindian (Egypt), Al-Snobar (Jordan). The "
    "maintenance AI uses XGBoost + Isolation Forest, tuned for high "
    "recall on the critical tier (threshold ≥70). Demand forecasting "
    "uses Prophet across five MENA markets with Ramadan/Eid seasonality. "
    "Be concise, factual, and grounded in the screen the user is viewing. "
    "Never invent numbers — if you don't have data, say so."
)

SCREEN_APPENDS: dict[str, str] = {
    "overview": (
        "User is on the fleet Overview screen. They see 4 machine cards, "
        "the KPI strip, and the critical alert banner. Help them interpret "
        "fleet health and decide where to drill in."
    ),
    "machine_detail": (
        "User is viewing a specific machine. The screen_payload may "
        "include machine_id and selected component. Help interpret risk "
        "scores, sensor traces, and recommended actions."
    ),
    "alerts": (
        "User is on the Alerts triage screen. Help them prioritise, "
        "decide what to acknowledge vs snooze, and explain why an alert "
        "fired."
    ),
    "demand_forecast": (
        "User is on the Demand Forecast screen. Help interpret forecasts, "
        "Ramadan/Eid effects, and SKU/market comparisons. Forecast "
        "accuracy is reported as MAPE."
    ),
}

OUTPUT_FORMAT_INSTRUCTION = (
    "\n\nRespond in 2-4 sentences, conversational plain English. "
    "End your reply with a JSON metadata block on its own line in this "
    "exact shape:\n"
    '<<META>>{"data_sources_used":["..."],"suggested_followups":["...","...","..."]}<<END>>\n'
    "data_sources_used should list any contract endpoints whose data you "
    "leaned on; suggested_followups should be 2-3 short next-question "
    "options the user might ask. If you have no useful follow-ups, "
    "use an empty array."
)


def build_system_prompt(screen_context: Optional[str], screen_payload: Optional[dict]) -> str:
    parts = [SYSTEM_PROMPT_BASE]
    if screen_context and screen_context in SCREEN_APPENDS:
        parts.append(SCREEN_APPENDS[screen_context])
    if screen_payload:
        # Filter to safe scalars only so we never echo back something
        # unexpected to the model. Keys we know about per the contract:
        keep = {
            k: v for k, v in screen_payload.items()
            if k in (
                "current_page", "current_machine_id", "current_component_id",
                "current_sku", "current_market",
            ) and v is not None
        }
        if keep:
            parts.append(f"Current screen state: {keep}")
    parts.append(OUTPUT_FORMAT_INSTRUCTION)
    return "\n\n".join(parts)


# ----------------------------------------------------------------------
# Cold-start suggested prompts (before the first message lands)
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
# Reply generation — calls Anthropic
# ----------------------------------------------------------------------

class ChatUnavailable(Exception):
    """Raised when the Anthropic call fails for any reason. The router
    converts this into a 502 + {"error": "chat_unavailable", ...}."""

    def __init__(self, safe_message: str) -> None:
        super().__init__(safe_message)
        self.safe_message = safe_message


def _parse_meta(reply_text: str) -> tuple[str, list[str], list[str]]:
    """Extract <<META>>{json}<<END>> block from the assistant reply, if present."""
    import re, json
    m = re.search(r"<<META>>(.*?)<<END>>", reply_text, re.DOTALL)
    if not m:
        return reply_text.strip(), [], []
    body = reply_text[: m.start()].strip()
    sources: list[str] = []
    followups: list[str] = []
    try:
        meta = json.loads(m.group(1))
        sources = list(meta.get("data_sources_used") or [])
        followups = list(meta.get("suggested_followups") or [])
    except Exception:  # noqa: BLE001
        pass
    return body, sources, followups


def generate_reply(
    history: list[dict],
    screen_context: Optional[str],
    screen_payload: Optional[dict],
) -> dict:
    """Synchronous Anthropic call. Returns dict with reply + meta lists +
    usage. Raises ChatUnavailable on any failure (key missing, network,
    rate limit, etc.) — the router maps that to HTTP 502.
    """
    if not ANTHROPIC_API_KEY:
        raise ChatUnavailable(
            "ANTHROPIC_API_KEY is not configured on the server."
        )

    try:
        from anthropic import Anthropic  # imported lazily so app startup doesn't fail
    except Exception as exc:  # noqa: BLE001
        log.error("anthropic SDK import failed: %s", type(exc).__name__)
        raise ChatUnavailable("AI client unavailable.") from exc

    if not history:
        raise ChatUnavailable("conversation history is empty.")

    system_prompt = build_system_prompt(screen_context, screen_payload)

    try:
        client = Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            system=system_prompt,
            messages=history,
        )
    except Exception as exc:  # noqa: BLE001
        # Defensive: never echo the API key. anthropic.AuthenticationError
        # gives a generic message but we sanitise further.
        kind = type(exc).__name__
        log.error("Anthropic call failed (%s)", kind)
        raise ChatUnavailable(f"AI request failed: {kind}") from exc

    # Stitch text blocks back together
    raw_text = "".join(
        getattr(b, "text", "")
        for b in resp.content
        if getattr(b, "type", "text") == "text"
    ).strip()

    body, sources, followups = _parse_meta(raw_text)
    usage = {
        "input_tokens": int(getattr(resp.usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(resp.usage, "output_tokens", 0) or 0),
    }
    return {
        "reply": body,
        "data_sources_used": sources,
        "suggested_followups": followups,
        "usage": usage,
    }
