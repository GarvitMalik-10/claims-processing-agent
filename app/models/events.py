"""Claim file event envelope (README section 6.2) and event types (section 6.3)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EventType(StrEnum):
    CLAIM_NOTIFIED = "claim.notified"
    CLAIM_REGISTERED = "claim.registered"
    CLAIM_RECORDED_AS_INCIDENT = "claim.recorded_as_incident"
    EVIDENCE_RECEIVED = "evidence.received"
    EVIDENCE_NORMALIZED = "evidence.normalized"
    FNOL_FIELD_EXTRACTED = "fnol.field_extracted"
    FNOL_COMPLETENESS_EVALUATED = "fnol.completeness_evaluated"
    FNOL_INFO_REQUESTED = "fnol.info_requested"
    FNOL_INFO_RECEIVED = "fnol.info_received"
    MESSAGE_SENT = "message.sent"
    POLICY_MATCHED = "policy.matched"
    VISION_EXTRACTED = "vision.extracted"
    JEV_ANSWERED = "jev.answered"
    FINDING_CREATED = "finding.created"
    RULE_EVALUATED = "rule.evaluated"
    COVERAGE_RESOLVED = "coverage.resolved"
    RISK_SCORED = "risk.scored"
    DEPRECIATION_CALCULATED = "depreciation.calculated"
    PAYOUT_CALCULATED = "payout.calculated"
    ROUTING_DECIDED = "routing.decided"
    HUMAN_REVIEW_REQUESTED = "human.review_requested"
    HUMAN_DECISION = "human.decision"
    REPORT_GENERATED = "report.generated"
    LETTER_GENERATED = "letter.generated"
    PAYMENT_INSTRUCTED = "payment.instructed"
    CLAIM_CLOSED = "claim.closed"
    SYSTEM_ERROR = "system.error"


ActorKind = Literal["agent", "rule", "human", "system", "customer"]


class Actor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ActorKind
    id: str
    role: str | None = None


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str | None = None
    prompt_or_question_set_version: str | None = None
    rule_id: str | None = None
    rule_source: str | None = None
    config_versions: dict[str, str] = Field(default_factory=dict)
    raw_request_blob: str | None = None
    raw_response_blob: str | None = None


class NewEvent(BaseModel):
    """What a node submits; the store assigns seq, ids, timestamp and the hash chain."""

    model_config = ConfigDict(extra="forbid")

    type: EventType
    actor: Actor
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)


class Event(NewEvent):
    claim_id: str
    seq: int
    event_id: str
    timestamp: datetime
    prev_hash: str
    hash: str

    def hash_material(self) -> dict[str, Any]:
        """Everything except `hash` itself, in JSON-native form, for canonical hashing."""
        return self.model_dump(mode="json", exclude={"hash"})


GENESIS_HASH = "0" * 64
