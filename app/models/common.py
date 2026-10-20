"""Shared building blocks: evidence references, warnings, confidence, and the agent output envelope.

Every agent returns an `AgentOutput[T]`. `reasoning` and `summary` are for humans and the audit
trail only - context views strip them so no agent ever reads another agent's prose (README principle 7).
"""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

PROSE_FIELDS = frozenset({"reasoning", "summary"})


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


EvidenceKind = Literal[
    "text", "image", "keyframe", "transcript", "document", "policy_clause", "price_row", "rule_config", "event"
]


class EvidenceRef(Strict):
    evidence_id: str = Field(description="Evidence or source id, e.g. EV-0003, C-2.4, DEP-ROOFING")
    kind: EvidenceKind
    locator: str | None = Field(default=None, description="Quote, image region, timestamp, clause id or table row")


class Warning(Strict):
    code: str
    severity: Literal["info", "warning", "critical"]
    message: str


ConfidenceSource = Literal["rule", "measured", "self_reported"]


class Confidence(Strict):
    value: float = Field(ge=0, le=1)
    source: ConfidenceSource
    basis: str = Field(description='What produced it, e.g. "jev noul photo_supports_story" or "rule PAY-CAP-01"')

    @property
    def routable(self) -> bool:
        """Routing may only use rule outcomes and measured probabilities (README principle 9)."""
        return self.source != "self_reported"


T = TypeVar("T", bound=BaseModel)


class AgentOutput(Strict, Generic[T]):
    agent: str
    agent_version: str
    claim_id: str
    finding: T
    confidence: Confidence
    evidence: list[EvidenceRef] = Field(min_length=1)
    reasoning: str
    summary: str
    warnings: list[Warning] = Field(default_factory=list)
