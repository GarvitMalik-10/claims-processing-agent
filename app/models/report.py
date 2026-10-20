"""ClaimDecisionReport - the single system output (README section 5.3), built by code from events."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.common import EvidenceRef, Warning

Route = Literal["stp", "human_review", "siu", "info_request", "incident_only"]
CoverageStatus = Literal["covered", "partially_covered", "not_covered", "unresolved", "not_applicable"]
ConsistencyResult = Literal["consistent", "partially_consistent", "inconsistent", "cannot_assess"]
ApprovalStatus = Literal["not_required", "pending", "approved", "overridden", "info_requested", "escalated_siu"]


class ClaimSummary(BaseModel):
    claim_id: str
    customer_id: str
    policy_id: str | None
    peril: str | None
    loss_date: date | None
    location: str | None
    channels: list[str] = Field(default_factory=list)
    language: Literal["nl", "en"] = "nl"
    text: dict[str, str] = Field(default_factory=dict, description="Bilingual summary {nl, en} from structured data")


class ImageAssessment(BaseModel):
    evidence_id: str
    room_type: str
    damage_types: list[str]
    severity: str | None
    severity_probabilities: dict[str, float] = Field(default_factory=dict)
    visible_items: list[str] = Field(default_factory=list)
    warnings: list[Warning] = Field(default_factory=list)


class ConsistencyCheck(BaseModel):
    check: str
    passed: bool | None
    source: Literal["rule", "jev"]
    detail: str
    evidence: list[EvidenceRef] = Field(default_factory=list)


class ImageClaimConsistency(BaseModel):
    result: ConsistencyResult
    checks: list[ConsistencyCheck]


class ClauseResolution(BaseModel):
    clause_id: str
    status: Literal["covered", "excluded", "conditional", "unresolved", "not_applicable"]
    condition: str | None = None
    facts_used: dict[str, str | float | bool | None] = Field(default_factory=dict)


class CoverageDecision(BaseModel):
    status: CoverageStatus
    clauses: list[ClauseResolution]


class RiskSignal(BaseModel):
    signal: str
    strength: float
    weight: float
    contribution: float
    source: Literal["rule", "jev"]


class RiskScore(BaseModel):
    score: float
    signals: list[RiskSignal]
    hard_flags: list[str] = Field(default_factory=list)


class PayoutLine(BaseModel):
    code: str
    description: str
    claimed: float
    validated: float
    depreciation: float
    covered: float
    rule_ids: list[str]
    reason: str | None = None


class PayoutRecommendation(BaseModel):
    lines: list[PayoutLine]
    eligible: float
    caps_applied: list[str] = Field(default_factory=list)
    deductible: float
    payout: float


class HumanApproval(BaseModel):
    status: ApprovalStatus
    reviewer_id: str | None = None
    reviewer_role: str | None = None
    reason: str | None = None
    decided_at: datetime | None = None


class AuditTrailSummary(BaseModel):
    event_count: int
    chain_intact: bool
    first_broken_seq: int | None = None
    config_versions: dict[str, str] = Field(default_factory=dict)


class ClaimDecisionReport(BaseModel):
    claim_summary: ClaimSummary
    image_assessment: list[ImageAssessment] = Field(default_factory=list)
    image_claim_consistency: ImageClaimConsistency | None = None
    coverage_decision: CoverageDecision | None = None
    risk_score: RiskScore | None = None
    payout_recommendation: PayoutRecommendation | None = None
    route: Route | None = None
    route_reasons: list[str] = Field(default_factory=list)
    human_approval: HumanApproval = Field(default_factory=lambda: HumanApproval(status="pending"))
    audit_trail: AuditTrailSummary | None = None
