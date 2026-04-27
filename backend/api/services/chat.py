"""Chat service.

This module is intentionally minimal — the real Claude wiring lands in a
later prompt. For now it:
  - Holds an in-memory store of conversations
  - Returns a deterministic placeholder reply that uses page/component
    context if provided
  - Returns suggested prompts that vary with current page

The endpoint shapes match API_CONTRACT.md v1.1 exactly so the frontend
can integrate against the contract today; replacing the reply generator
with an Anthropic call later is a single-function swap.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from threading import Lock
from typing import Optional


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

    def append(self, cid: str, role: str, content: str,
               data_sources_used: Optional[list[str]] = None) -> None:
        with self._lock:
            conv = self._convs.get(cid)
            if conv is None:
                conv = {
                    "conversation_id": cid,
                    "created_at": _now_iso(),
                    "messages": [],
                }
                self._convs[cid] = conv
            entry = {
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


store = ConversationStore()


def generate_reply(message: str, context: Optional[dict]) -> dict:
    """Placeholder reply generator. Returns reply + data_sources_used + suggested_followups.

    A future prompt swaps this for an Anthropic Claude tool-use loop where
    each REST endpoint in this contract is exposed as a tool.
    """
    ctx = context or {}
    machine_id = ctx.get("current_machine_id")
    component_id = ctx.get("current_component_id")
    page = ctx.get("current_page")

    sources: list[str] = []
    if machine_id and component_id:
        sources.append(f"machines/{machine_id}/components/{component_id}/risk-score")
        if component_id == "yankee":
            sources.append(f"machines/{machine_id}/sensors/yankee_vibration_bearing_3/history")
    elif machine_id:
        sources.append(f"machines/{machine_id}")
        sources.append(f"machines/{machine_id}/components")

    # Demo anchor reply for the contract's example prompt.
    if (machine_id == "al-nakheel" and component_id == "yankee") or \
       "yankee" in message.lower() and "al nakheel" in message.lower():
        reply = (
            "Yankee on Al Nakheel is at 87% risk because Bearing 3 vibration has "
            "been climbing 0.4 mm/s/day for 11 days. Current reading is 5.8 mm/s; "
            "normal range is 2-4 mm/s. The model predicts failure within the next "
            "48 hours. Recommended action: schedule bearing replacement during the "
            "next downtime window. Estimated cost if ignored: $480,000."
        )
        followups = [
            "Compare Bearing 3 to the same bearing on Al Snobar",
            "What if I delay the replacement by 3 days?",
            "Show me the maintenance history for this component",
        ]
    else:
        # Generic placeholder until the Anthropic wiring lands.
        if machine_id:
            reply = (
                f"I'm the FHH AI Optimizer assistant. You're on the "
                f"{page or 'dashboard'} page for {machine_id}. Ask me about "
                "specific components, sensor trends, or risk scores."
            )
        else:
            reply = (
                "I'm the FHH AI Optimizer assistant. Ask me about machine "
                "health, components, alerts, or demand forecasts. The full "
                "Claude integration is wired in a later prompt — for now I "
                "echo context and surface relevant data sources."
            )
        followups = [
            "What's wrong with Al Nakheel right now?",
            "Compare risk across all 4 machines",
            "When should I schedule the next maintenance window?",
        ]

    return {
        "reply": reply,
        "data_sources_used": sources,
        "suggested_followups": followups,
    }


def suggested_prompts(
    current_page: Optional[str] = None,
    current_machine_id: Optional[str] = None,
    current_sku: Optional[str] = None,
) -> list[str]:
    if current_page == "machine_detail" and current_machine_id:
        return [
            f"What's the highest-risk component on {current_machine_id}?",
            f"Show me the alerts for {current_machine_id}",
            f"When was {current_machine_id} last serviced?",
            "Compare this machine to the rest of the fleet",
        ]
    if current_page == "alerts":
        return [
            "Which alert is the most urgent?",
            "Group critical alerts by machine",
            "Show me the predicted cost impact of all open alerts",
            "Which machines have the most warnings this week?",
        ]
    if current_page == "demand_forecast":
        return [
            "How will Ramadan affect production capacity?",
            "Forecast Fine Facial Tissue demand in UAE for the next 6 months",
            "What if competitor entry drops baby-care demand by 15%?",
            "Which SKU has the strongest seasonality?",
        ]
    # overview / default
    return [
        "What's wrong with Al Nakheel right now?",
        "Compare risk across all 4 machines",
        "When should I schedule the next maintenance window?",
        "How will Ramadan affect production capacity?",
    ]
