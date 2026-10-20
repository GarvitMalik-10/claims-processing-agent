"""Read models over the claim file: current evidence, extraction, Jev answers, estimate.

Status is always derived from events (README 6.2); nothing here is stored as mutable truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.domain import Estimate
from app.models.events import Event, EventType
from app.store.event_store import EventStore


@dataclass
class EvidenceItem:
    evidence_id: str
    kind: str
    received_at: datetime
    sent_at: str | None
    text: str | None = None
    language: str | None = None
    blob: str | None = None
    normalized_blob: str | None = None
    filename: str | None = None
    exif: dict[str, Any] = field(default_factory=dict)
    phash: str | None = None
    estimate: Estimate | None = None


def evidence(store: EventStore, claim_id: str) -> list[EvidenceItem]:
    items: dict[str, EvidenceItem] = {}
    for e in store.events(claim_id, {EventType.EVIDENCE_RECEIVED, EventType.EVIDENCE_NORMALIZED}):
        p = e.payload
        if e.type == EventType.EVIDENCE_RECEIVED:
            items[p["evidence_id"]] = EvidenceItem(
                evidence_id=p["evidence_id"], kind=p["kind"], received_at=e.timestamp, sent_at=p.get("sent_at"),
                text=p.get("text"), blob=p.get("blob"), filename=p.get("filename"),
                estimate=Estimate.model_validate(p["estimate"]) if p.get("estimate") else None,
            )
        else:
            item = items[p["evidence_id"]]
            item.language = p.get("language", item.language)
            item.normalized_blob = p.get("normalized_blob", item.normalized_blob)
            item.exif = p.get("exif", item.exif)
            item.phash = p.get("phash", item.phash)
    return list(items.values())


def customer_texts(store: EventStore, claim_id: str) -> list[EvidenceItem]:
    return [i for i in evidence(store, claim_id) if i.kind == "text"]


def images(store: EventStore, claim_id: str) -> list[EvidenceItem]:
    return [i for i in evidence(store, claim_id) if i.kind == "image"]


def latest_estimate(store: EventStore, claim_id: str) -> Estimate | None:
    ests = [i.estimate for i in evidence(store, claim_id) if i.estimate is not None]
    return ests[-1] if ests else None


def latest(store: EventStore, claim_id: str, etype: EventType, **match: Any) -> Event | None:
    """Most recent event of a type whose payload matches the given key/values."""
    for e in reversed(store.events(claim_id, {etype})):
        if all(e.payload.get(k) == v for k, v in match.items()):
            return e
    return None


def jev_answers(store: EventStore, claim_id: str, question_set: str) -> dict[str, dict[str, Any]]:
    """Latest answer per question id within a question set."""
    out: dict[str, dict[str, Any]] = {}
    for e in store.events(claim_id, {EventType.JEV_ANSWERED}):
        if e.payload.get("question_set") == question_set:
            out[e.payload["question_id"]] = e.payload
    return out


def notification(store: EventStore, claim_id: str) -> dict[str, Any]:
    first = store.events(claim_id, {EventType.CLAIM_NOTIFIED})
    if not first:
        raise KeyError(f"Unknown claim {claim_id}")
    return first[0].payload
