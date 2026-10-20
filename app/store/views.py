"""Context views ("slices") built by code from the claim file (README 6.4).

Rule: every agent-facing view strips prose fields (`reasoning`, `summary`) at any depth, so agents
only ever exchange structured findings and evidence references. Only the reviewer view keeps prose.
"""

from __future__ import annotations

from typing import Any

from app.models.common import PROSE_FIELDS
from app.models.events import Event, EventType
from app.store.event_store import EventStore


def strip_prose(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: strip_prose(v) for k, v in obj.items() if k not in PROSE_FIELDS}
    if isinstance(obj, list):
        return [strip_prose(v) for v in obj]
    return obj


def agent_view(store: EventStore, claim_id: str, types: set[EventType]) -> list[dict[str, Any]]:
    """Payloads of the selected event types, prose removed. Base for the per-agent views."""
    return [
        {"seq": e.seq, "type": e.type.value, "evidence_refs": e.evidence_refs, "payload": strip_prose(e.payload)}
        for e in store.events(claim_id, types)
    ]


def reviewer_view(store: EventStore, claim_id: str) -> list[Event]:
    """Everything, prose included, as a timeline."""
    return store.events(claim_id)
