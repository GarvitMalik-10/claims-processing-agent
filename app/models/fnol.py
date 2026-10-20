"""FNOL structured outputs (README 7.2). Every extracted value carries the exact source quote."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SourcedText(BaseModel):
    value: str = Field(description="Normalized value in English (dates as YYYY-MM-DD, times as HH:MM)")
    quote: str = Field(description="Exact words copied from the customer's message that support the value")
    evidence_id: str = Field(description="Id of the message the quote comes from, e.g. EV-0001")


class SourcedBool(BaseModel):
    value: bool
    quote: str = Field(description="Exact words copied from the customer's message that support the value")
    evidence_id: str


class ItemAge(BaseModel):
    line_code: str = Field(description="Estimate line code the age belongs to")
    age_years: float
    quote: str = Field(description="Exact words copied from the customer's message stating the age or purchase year")
    evidence_id: str


class AffectedItem(BaseModel):
    label: str
    quote: str
    evidence_id: str


class FnolExtraction(BaseModel):
    """Structured output of the FNOL extractor (Sonnet). Unknown fields must be null - never guessed."""

    language: Literal["nl", "en"]
    loss_date: SourcedText | None = Field(description="Date of the loss, resolved against the message timestamp")
    loss_time: SourcedText | None
    what_happened: SourcedText | None = Field(description="Short description of the cause in the customer's words")
    source: SourcedText | None = Field(description="Where water/fire/etc. came from, e.g. 'washing machine hose'")
    location: SourcedText | None = Field(description="Room or part of the home where the damage is")
    loss_address_differs: SourcedText | None = Field(description="Only if the customer names an address other than home")
    source_stopped: SourcedBool | None = Field(description="Has the cause been stopped (tap closed, leak repaired, fire out)?")
    emergency_measures: SourcedText | None
    third_party_involved: SourcedText | None
    police_report_ref: SourcedText | None
    fire_brigade_report_ref: SourcedText | None
    theft_reported: SourcedBool | None = Field(description="Were items stolen?")
    affected_items: list[AffectedItem]
    item_ages: list[ItemAge] = Field(description="Ages the customer gave for estimate lines")
    extraction_confidence: float = Field(ge=0, le=1, description="Your own confidence in this extraction")
    reasoning: str = Field(description="Brief note on ambiguities; for the audit trail only")
    summary: str = Field(description="One-sentence English summary of the notification")


class QuoteCheck(BaseModel):
    field: str
    evidence_id: str
    found: bool


class CompletenessResult(BaseModel):
    complete: bool
    peril: str | None
    missing: list[str]
    satisfied: dict[str, str] = Field(default_factory=dict, description="field -> where it was satisfied")
    rule_set_version: str


class InfoRequestMessage(BaseModel):
    text: str = Field(description="The WhatsApp message to send to the customer")
