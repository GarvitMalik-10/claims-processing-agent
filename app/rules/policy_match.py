"""Match policy & register claim (README 7.2 step 5). Clause C-1.1: active policy, loss at insured address."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from app.models.domain import Customer, Policy

RULE_ID = "POL-ACTIVE-01"
CLAUSE = "C-1.1"


class PolicyMatch(BaseModel):
    matched: bool
    policy_id: str | None
    product: str | None
    reasons: list[str]
    days_since_policy_start: int | None = None


def match_policy(customer: Customer, policy: Policy | None, loss_date: date | None,
                 loss_address_differs: str | None) -> PolicyMatch:
    if policy is None:
        return PolicyMatch(matched=False, policy_id=None, product=None, reasons=["NO_POLICY_FOR_CUSTOMER"])
    reasons: list[str] = []
    if policy.status != "active":
        reasons.append("POLICY_NOT_ACTIVE")
    if loss_date is not None and loss_date < policy.start_date:
        reasons.append("LOSS_BEFORE_POLICY_START")
    if loss_address_differs:
        reasons.append("LOSS_ADDRESS_NOT_INSURED_ADDRESS")
    days = (loss_date - policy.start_date).days if loss_date else None
    return PolicyMatch(matched=not reasons, policy_id=policy.policy_id, product=policy.product, reasons=reasons,
                       days_since_policy_start=days)
