"""Structured findings of the three parallel assessment agents (README section 8)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RoomType = Literal["kitchen", "bathroom", "living_room", "bedroom", "hallway", "stairwell_or_basement", "attic",
                   "exterior_roof", "exterior_facade", "garden", "non_residential", "unknown"]
ImageQuality = Literal["good", "blurry", "too_dark", "partial_view", "not_a_damage_photo"]
DamageType = Literal[
    "active_leak", "water_staining", "tide_marks", "paint_peeling", "swelling_buckling", "mould", "rot", "rust_corrosion",
    "efflorescence", "burn_charring", "soot", "melting", "roof_tiles_missing_or_broken", "chimney_collapse",
    "structural_collapse", "tree_impact", "broken_glass", "forced_entry_marks", "flood_line", "debris", "cracks",
    "other",
]


# --- Vision (Sonnet) ------------------------------------------------------------------------------

class DamagedPart(BaseModel):
    part: str
    condition: str


class ImageObservation(BaseModel):
    """What one photo shows. Produced without seeing the customer's story."""

    image_quality: ImageQuality
    setting: Literal["interior", "exterior", "close_up_detail"]
    room_type: RoomType
    room_type_cues: list[str] = Field(description="Visible cues behind the room_type, e.g. 'museum display cases'")
    damage_present: bool
    damage_types: list[DamageType]
    damaged_parts: list[DamagedPart]
    materials: list[str]
    visible_items: list[str] = Field(description="Objects or building parts visible, e.g. 'kitchen base cabinet'")
    long_term_signs_visible: bool = Field(description="Mould, rot, rust, layered tide marks, weathering")
    visible_text: list[str] = Field(description="Readable text such as street signs or number plates")
    regional_indicators: list[str] = Field(description="Clues about country/region, e.g. 'UK street sign'")
    confidence: float = Field(ge=0, le=1, description="Your own confidence; never used for decisions")
    summary_en: str = Field(description="Two sentences describing what is visible")


# --- Damage agent finding -------------------------------------------------------------------------

class ConsistencyCheck(BaseModel):
    check: str
    result: Literal["pass", "fail", "unresolved", "not_applicable"]
    severity: Literal["critical", "minor"]
    source: Literal["rule", "jev"]
    detail: str
    evidence_ids: list[str] = Field(default_factory=list)


class LineAssessment(BaseModel):
    code: str
    description: str
    price_status: Literal["within_range", "above_range", "below_range"]
    over_benchmark_pct: float
    visible: Literal["visible", "not_visible", "unresolved", "not_applicable"]
    visible_noul: float | None = None


class DamageFinding(BaseModel):
    peril: str | None
    severity: str | None
    severity_confidence: float | None
    facts: dict[str, str | float | bool | None] = Field(
        description="Fact keys consumed by policy conditions, e.g. sudden_vs_gradual, long_term_moisture_signs")
    consistency: Literal["consistent", "partially_consistent", "inconsistent", "cannot_assess"]
    checks: list[ConsistencyCheck]
    lines: list[LineAssessment]
    images: dict[str, ImageObservation]


# --- Policy agent finding -------------------------------------------------------------------------

class FactCondition(BaseModel):
    fact_key: str
    op: Literal["==", "!=", ">=", "<", "in_band"]
    value: str | float | bool | list[float]


class ClauseCondition(BaseModel):
    clause_id: str
    kind: Literal["cover", "exclusion", "condition"]
    status: Literal["covered", "excluded", "conditional", "unresolved", "not_applicable"]
    scope: Literal["claim", "lines"] = "claim"
    line_codes: list[str] = Field(default_factory=list)
    # For "conditional": excluded/not-covered when `exclude_if` holds, unresolved when `unresolved_if` holds.
    exclude_if: list[FactCondition] = Field(default_factory=list)
    unresolved_if: list[FactCondition] = Field(default_factory=list)
    reason: str
    selected_by: list[Literal["sonnet", "peril_matrix", "rule"]] = Field(default_factory=list)


class PolicyFinding(BaseModel):
    policy_id: str
    product: str
    peril: str | None
    peril_covered: bool | None
    clauses: list[ClauseCondition]
    deductible: dict[str, float]
    sum_insured: dict[str, float]


class ClauseSelection(BaseModel):
    """Sonnet output: which clauses of the wording matter for this loss. Ids only - no decisions."""

    clause_ids: list[str]
    reasoning: str
    summary: str


# --- Risk agent finding ---------------------------------------------------------------------------

class RiskSignalValue(BaseModel):
    signal: str
    strength: float = Field(ge=0, le=1)
    weight: float
    contribution: float
    source: Literal["rule", "jev"]
    detail: str


class RiskFinding(BaseModel):
    score: float
    band: Literal["low", "medium", "high"]
    signals: list[RiskSignalValue]
    hard_flags: list[str]
    duplicate_matches: list[dict] = Field(default_factory=list)
