"""LangGraph execution state. Deliberately thin: facts live in the event store, not here (README 5.2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Stage = Literal["fnol", "awaiting_customer", "assessment", "join", "payout", "routing", "review", "closed",
                "incident_only"]
InterruptReason = Literal["awaiting_customer_info", "awaiting_human_review"]


class ClaimGraphState(BaseModel):
    claim_id: str
    stage: Stage = "fnol"
    info_request_rounds: int = 0
    pending_interrupt: InterruptReason | None = None
    route_reasons: list[str] = Field(default_factory=list)
    # Items to ask the customer for when the request comes from routing or a reviewer (not completeness)
    pending_missing: list[str] = Field(default_factory=list)
