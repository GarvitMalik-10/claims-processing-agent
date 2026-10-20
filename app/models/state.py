"""LangGraph execution state. Deliberately thin: facts live in the event store, not here (README 5.2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Stage = Literal["fnol", "assessment", "join", "payout", "routing", "review", "closed", "incident_only"]
InterruptReason = Literal["awaiting_customer_info", "awaiting_human_review"]


class ClaimGraphState(BaseModel):
    claim_id: str
    stage: Stage = "fnol"
    info_request_rounds: int = 0
    last_event_seq: int = 0
    pending_interrupt: InterruptReason | None = None
