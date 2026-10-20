"""Join / resolve (README 9.1): evaluate the Policy agent's clause conditions against the Damage agent's
fact keys. Plain code. Produces the claim-level coverage status and per-line exclusions for the payout."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.models.assessment import ClauseCondition, FactCondition, PolicyFinding
from app.models.report import ClauseResolution, CoverageDecision

RULE_ID = "COV-RESOLVE-01"


def _holds(c: FactCondition, facts: dict[str, Any]) -> bool | None:
    """True/False, or None when the fact is not available (-> unresolved)."""
    v = facts.get(c.fact_key)
    if v is None:
        return None
    match c.op:
        case "==":
            return v == c.value
        case "!=":
            return v != c.value
        case ">=":
            return float(v) >= float(c.value)
        case "<":
            return float(v) < float(c.value)
        case "in_band":
            lo, hi = c.value  # type: ignore[misc]
            return lo < float(v) < hi
    raise ValueError(c.op)


def resolve_clause(c: ClauseCondition, facts: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    used = {f.fact_key: facts.get(f.fact_key) for f in c.exclude_if + c.unresolved_if}
    if c.status != "conditional":
        return c.status, used
    excl = [_holds(f, facts) for f in c.exclude_if]
    if any(h is True for h in excl):
        return "excluded", used
    unres = [_holds(f, facts) for f in c.unresolved_if]
    if any(h is True for h in unres) or any(h is None for h in excl):
        return "unresolved", used
    return ("not_applicable" if c.kind == "exclusion" else "covered"), used


class CoverageResult(BaseModel):
    decision: CoverageDecision
    excluded_lines: dict[str, str] = Field(default_factory=dict, description="line code -> excluding clause")
    adverse: bool
    reasons: list[str] = Field(default_factory=list)


def resolve(policy: PolicyFinding, facts: dict[str, Any], line_codes: list[str], *,
            non_adverse_line_clauses: set[str]) -> CoverageResult:
    resolutions: list[ClauseResolution] = []
    excluded_lines: dict[str, str] = {}
    reasons: list[str] = []
    claim_excluded = claim_unresolved = False

    for c in policy.clauses:
        status, used = resolve_clause(c, facts)
        cond = "; ".join(f"{f.fact_key} {f.op} {f.value}" for f in c.exclude_if) or None
        resolutions.append(ClauseResolution(clause_id=c.clause_id, status=status, condition=cond, facts_used=used))
        if c.scope == "lines":
            if status == "excluded":
                for code in c.line_codes:
                    excluded_lines.setdefault(code, c.clause_id)
            elif status == "unresolved":
                claim_unresolved = True
                reasons.append(f"UNRESOLVED:{c.clause_id}")
        else:
            if status == "excluded":
                claim_excluded = True
                reasons.append(f"EXCLUDED:{c.clause_id}")
            elif status == "unresolved":
                claim_unresolved = True
                reasons.append(f"UNRESOLVED:{c.clause_id}")

    if policy.peril_covered is False:
        claim_excluded = True
        reasons.append("PERIL_NOT_INSURED")

    adverse_lines = {code: cl for code, cl in excluded_lines.items() if cl not in non_adverse_line_clauses}
    paid_lines = [c for c in line_codes if c not in excluded_lines]
    if claim_excluded or (line_codes and not paid_lines):
        status = "not_covered"
    elif claim_unresolved:
        status = "unresolved"
    elif adverse_lines:
        status = "partially_covered"
        reasons += [f"LINE_EXCLUDED:{code}:{cl}" for code, cl in adverse_lines.items()]
    else:
        status = "covered"
    return CoverageResult(
        decision=CoverageDecision(status=status, clauses=resolutions),
        excluded_lines=excluded_lines,
        adverse=status in ("not_covered", "partially_covered"),
        reasons=reasons,
    )
