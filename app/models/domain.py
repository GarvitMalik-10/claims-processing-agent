"""Typed reference data: customers, policies, policy tables, clauses, price benchmark, scenarios."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Data(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class Address(_Data):
    street: str
    postcode: str
    city: str
    geo: dict[str, float]

    @property
    def one_line(self) -> str:
        return f"{self.street}, {self.postcode} {self.city}"


class Customer(_Data):
    customer_id: str
    name: str
    phone: str
    email: str
    language: Literal["nl", "en"]
    address: Address
    policy_id: str
    persona_note: str = ""


class Product(_Data):
    name: dict[str, str]
    covers: list[Literal["building", "contents"]]
    perils: list[str]
    extensions: list[str]
    clauses: list[str]


class Policy(_Data):
    policy_id: str
    customer_id: str
    product: str
    start_date: date
    status: str
    insured_address: str
    sum_insured: dict[str, float]
    deductible: dict[str, float]
    building_facts: dict[str, Any] = Field(default_factory=dict)


class SublimitRow(_Data):
    row_id: str
    applies_to: str | list[str]
    max_per_event: float
    clause_id: str
    products: list[str] | None = None

    def codes(self) -> list[str]:
        return [self.applies_to] if isinstance(self.applies_to, str) else list(self.applies_to)


class DepreciationRow(_Data):
    row_id: str
    category: str | list[str]
    depreciable: bool
    annual_rate: float = 0.0
    max_depreciation: float = 0.0
    new_value_years: int = 0

    def categories(self) -> list[str]:
        return [self.category] if isinstance(self.category, str) else list(self.category)


class Clause(_Data):
    clause_id: str
    type: Literal["cover", "exclusion", "condition"]
    title: dict[str, str]
    text: dict[str, str]
    rule: dict[str, Any] = Field(default_factory=dict)


class PolicyBook(_Data):
    """Everything in policies.json - the only source the Policy agent and payout rules may use."""

    products: dict[str, Product]
    policies: list[Policy]
    sublimits: list[SublimitRow]
    depreciation_clause_id: str
    depreciation: list[DepreciationRow]
    clauses: dict[str, Clause]

    def policy(self, policy_id: str) -> Policy:
        return next(p for p in self.policies if p.policy_id == policy_id)

    def depreciation_row(self, category: str) -> DepreciationRow | None:
        return next((r for r in self.depreciation if category in r.categories()), None)


class PriceItem(_Data):
    code: str
    label: dict[str, str]
    unit: str
    p25: float
    p50: float
    p75: float
    category: str
    object: Literal["building", "contents"]
    source_repair: bool


class PriceBook(_Data):
    region: str
    currency: str
    tolerance: float
    items: dict[str, PriceItem]


class EstimateLine(_Data):
    code: str
    description: str
    qty: float
    unit_price: float
    total: float
    age_years: float | None = None


class Estimate(_Data):
    contractor: str | None
    date: date | None
    lines: list[EstimateLine]
    total: float


class CustomerMessage(_Data):
    lang: Literal["nl", "en"]
    text: str
    translation: str | None = None


class ClaimScenario(_Data):
    scenario_id: str
    title: str
    customer_id: str
    images: list[str]
    loss_date: date
    reported_at: str
    messages: list[dict[str, str]]
    claimed_facts: dict[str, Any]
    estimate: Estimate | None
    exif_override: dict[str, Any] | None = None
    golden: dict[str, Any]


class ImageObservationRef(_Data):
    """Golden observation record (image_observations.json); kept loose - it is reference data."""

    image_id: str
    file: str
    scene: dict[str, Any]
    damage_present: dict[str, Any]
    severity: dict[str, Any]
    sudden_vs_gradual: dict[str, Any]
    summary: dict[str, str]
    warnings: list[dict[str, Any]] = Field(default_factory=list)
