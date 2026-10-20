"""Payout calculation (README 9.2-9.3). Plain code; no LLM ever does arithmetic.

Order: benchmark validation -> source-repair / coverage exclusion -> depreciation -> sublimits ->
sum insured -> deductible. Every step yields a `RuleEvaluation` (rule id, source, inputs, output)
that the graph writes as a `rule.evaluated` event, so the number is fully reconstructable.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.models.common import Warning
from app.models.domain import EstimateLine, Policy, PolicyBook, PriceBook
from app.models.report import PayoutLine, PayoutRecommendation

CENT = Decimal("0.01")


def money(x: float | Decimal) -> Decimal:
    return Decimal(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)


class RuleEvaluation(BaseModel):
    rule_id: str
    rule_source: str
    inputs: dict[str, Any]
    output: dict[str, Any]
    line_code: str | None = None


class PayoutResult(BaseModel):
    recommendation: PayoutRecommendation
    evaluations: list[RuleEvaluation]
    warnings: list[Warning] = Field(default_factory=list)


def calculate_payout(
    lines: list[EstimateLine],
    *,
    policy: Policy,
    book: PolicyBook,
    prices: PriceBook,
    tolerance: float,
    excluded_codes: dict[str, str] | None = None,
) -> PayoutResult:
    """`excluded_codes` maps a line code to the clause that excludes it (from coverage resolution)."""
    excluded_codes = excluded_codes or {}
    product = book.products[policy.product]
    evals: list[RuleEvaluation] = []
    warnings: list[Warning] = []
    out_lines: list[PayoutLine] = []

    for line in lines:
        item = prices.items[line.code]
        claimed = money(line.total)
        cap_unit = money(Decimal(str(item.p75)) * (1 + Decimal(str(tolerance))))
        unit = min(money(line.unit_price), cap_unit)
        validated = money(unit * Decimal(str(line.qty)))
        evals.append(RuleEvaluation(
            rule_id="PAY-BENCH-01", rule_source=f"table:price_benchmark#{line.code}", line_code=line.code,
            inputs={"claimed_unit": line.unit_price, "qty": line.qty, "p75": item.p75, "tolerance": tolerance},
            output={"validated": float(validated), "trimmed": line.unit_price > float(cap_unit)},
        ))
        rule_ids = ["PAY-BENCH-01"]

        exclusion = "C-2.3" if item.source_repair else excluded_codes.get(line.code)
        if exclusion:
            evals.append(RuleEvaluation(
                rule_id="COV-LINE-EXCL-01", rule_source=f"policy:{policy.policy_id}#{exclusion}",
                line_code=line.code, inputs={"code": line.code}, output={"covered": 0.0, "clause": exclusion},
            ))
            out_lines.append(PayoutLine(code=line.code, description=line.description, claimed=float(claimed),
                                        validated=float(validated), depreciation=0.0, covered=0.0,
                                        rule_ids=rule_ids + ["COV-LINE-EXCL-01"], reason=f"{exclusion} excluded"))
            continue

        depreciation = Decimal(0)
        dep_row = book.depreciation_row(item.category)
        reason = "unit price trimmed to benchmark" if line.unit_price > float(cap_unit) else None
        if dep_row and dep_row.depreciable:
            if line.age_years is None:
                warnings.append(Warning(code="ITEM_AGE_UNKNOWN", severity="critical",
                                        message=f"Age unknown for depreciable item {line.code}"))
            else:
                years = max(0.0, line.age_years - dep_row.new_value_years)
                pct = min(dep_row.max_depreciation, dep_row.annual_rate * years)
                depreciation = money(validated * Decimal(str(pct)))
                reason = f"{dep_row.row_id}: {pct:.0%} depreciation"
                evals.append(RuleEvaluation(
                    rule_id="PAY-DEPR-01", rule_source=f"policy:{book.depreciation_clause_id}#{dep_row.row_id}",
                    line_code=line.code,
                    inputs={"validated": float(validated), "age_years": line.age_years,
                            "annual_rate": dep_row.annual_rate, "new_value_years": dep_row.new_value_years,
                            "max_depreciation": dep_row.max_depreciation},
                    output={"depreciation_pct": pct, "depreciation": float(depreciation)},
                ))
                rule_ids.append("PAY-DEPR-01")
        covered = validated - depreciation
        out_lines.append(PayoutLine(code=line.code, description=line.description, claimed=float(claimed),
                                    validated=float(validated), depreciation=float(depreciation),
                                    covered=float(covered), rule_ids=rule_ids, reason=reason))

    caps: list[str] = []
    for row in book.sublimits:
        if row.products and policy.product not in row.products:
            continue
        subtotal = sum((Decimal(str(l.covered)) for l in out_lines if l.code in row.codes()), Decimal(0))
        if subtotal > Decimal(str(row.max_per_event)):
            caps.append(row.row_id)
            excess = subtotal - Decimal(str(row.max_per_event))
            evals.append(RuleEvaluation(rule_id="PAY-SUBLIMIT-01", rule_source=f"policy:{row.clause_id}#{row.row_id}",
                                        inputs={"subtotal": float(subtotal), "max": row.max_per_event},
                                        output={"reduced_by": float(excess)}))
            for l in reversed(out_lines):  # take the excess off the matching lines, last first
                if l.code in row.codes() and excess > 0:
                    take = min(excess, Decimal(str(l.covered)))
                    l.covered = float(Decimal(str(l.covered)) - take)
                    excess -= take

    eligible = sum((Decimal(str(l.covered)) for l in out_lines), Decimal(0))
    objects = {prices.items[l.code].object for l in out_lines if l.covered > 0} or set(product.covers)
    sum_insured = sum((Decimal(str(policy.sum_insured.get(o, 0))) for o in objects), Decimal(0))
    if eligible > sum_insured:
        caps.append("SUM_INSURED")
        eligible = sum_insured
    evals.append(RuleEvaluation(rule_id="PAY-CAP-01", rule_source="policy:C-9.2",
                                inputs={"sum_of_covered_lines": float(eligible), "sum_insured": float(sum_insured)},
                                output={"eligible": float(eligible)}))

    paid_lines = [l for l in out_lines if l.covered > 0]
    glass_only = bool(paid_lines) and all(prices.items[l.code].category == "glass" for l in paid_lines)
    ded_key = "glass" if glass_only and "glass" in policy.deductible else "default"
    deductible = money(policy.deductible[ded_key])
    payout = max(Decimal(0), eligible - deductible)
    evals.append(RuleEvaluation(rule_id="PAY-DEDUCT-01", rule_source=f"policy:{policy.policy_id}#deductible.{ded_key}",
                                inputs={"eligible": float(eligible), "deductible": float(deductible)},
                                output={"payout": float(payout)}))

    return PayoutResult(
        recommendation=PayoutRecommendation(lines=out_lines, eligible=float(money(eligible)), caps_applied=caps,
                                            deductible=float(deductible), payout=float(money(payout))),
        evaluations=evals,
        warnings=warnings,
    )
