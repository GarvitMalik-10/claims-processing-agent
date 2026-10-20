"""Decision gate (README 9.4). Plain code over findings + config; reasons are reason codes.

Order: SIU -> ask the customer (missing evidence) -> human review (any reason) -> STP.
Only `rule` and `measured` confidences reach this function; self-reported model confidence never does.
"""

from __future__ import annotations

from typing import Any

from app.models.assessment import ConsistencyCheck
from app.models.report import RoutingDecision

RULE_ID = "ROUTE-GATE-01"


def approver_for(payout: float, authority: dict[str, Any]) -> str:
    for band in authority["bands"]:
        if band["max_payout"] is None or payout <= band["max_payout"]:
            return band["approver"]
    raise ValueError("authority matrix has no open-ended band")


def decide(
    *,
    coverage_status: str,
    coverage_reasons: list[str],
    consistency: str | None,
    checks: list[ConsistencyCheck],
    risk_score: float | None,
    hard_flags: list[str],
    payout: float | None,
    critical_warnings: list[str],
    failed_agents: list[str],
    info_rounds_used: int,
    thresholds: dict[str, Any],
    authority: dict[str, Any],
) -> RoutingDecision:
    th = thresholds
    amount = payout or 0.0
    approver = approver_for(amount, authority)

    if hard_flags or (risk_score is not None and risk_score >= th["risk"]["siu_from"]):
        reasons = [f"HARD_FLAG:{f}" for f in hard_flags] or [f"RISK_GE_{th['risk']['siu_from']}"]
        return RoutingDecision(route="siu", reasons=reasons, approver="special_investigations")

    # Missing evidence we can ask the customer for (bounded by the shared info-round budget)
    rounds_left = info_rounds_used < th["missing_info"]["max_rounds"]
    info: list[str] = []
    if consistency == "cannot_assess":
        info.append("damage_photo")
    info += [f"photo_of:{c.check.split(':', 1)[1]}" for c in checks
             if c.check.startswith("item_visible:") and c.result == "fail"]
    if info and rounds_left and not failed_agents:
        return RoutingDecision(route="info_request", reasons=["EVIDENCE_MISSING"], approver=approver, info_needed=info)

    reasons: list[str] = [f"ASSESSMENT_FAILED:{a}" for a in failed_agents]
    if coverage_status == "not_covered":
        reasons.append("ADVERSE_DECISION_NOT_COVERED")
    elif coverage_status == "partially_covered":
        reasons.append("ADVERSE_DECISION_PARTIAL")
    elif coverage_status == "unresolved":
        reasons.append("COVERAGE_UNRESOLVED")
    reasons += [r for r in coverage_reasons if r.startswith(("EXCLUDED", "UNRESOLVED", "PERIL"))]

    if consistency in ("inconsistent", "cannot_assess"):
        reasons.append("IMAGE_CLAIM_INCONSISTENT" if consistency == "inconsistent" else "IMAGE_EVIDENCE_INSUFFICIENT")
    elif consistency == "partially_consistent":
        blocking = [c for c in checks if c.result in ("fail", "unresolved")
                    and not (c.check.startswith("item_visible:") and c.result == "unresolved"
                             and not th.get("visibility_unresolved_blocks_stp", True))]
        if blocking:
            reasons.append("IMAGE_CLAIM_PARTIAL")
            reasons += [f"CHECK:{c.check}={c.result}" for c in blocking if c.severity == "critical"]
            reasons += [f"JEV_UNCERTAIN:{c.check}" for c in blocking if c.source == "jev" and c.result == "unresolved"]

    if risk_score is not None and risk_score >= th["risk"]["human_from"]:
        reasons.append(f"RISK_MEDIUM_{risk_score:.2f}")
    reasons += [f"WARNING:{w}" for w in critical_warnings]
    if amount > th["stp_payout_limit"]:
        reasons.append("PAYOUT_ABOVE_STP_LIMIT")
        reasons.append(f"AUTHORITY_{approver.upper()}")

    if reasons:
        return RoutingDecision(route="human_review", reasons=list(dict.fromkeys(reasons)),
                               approver=approver if approver != "auto_stp" else "claims_handler")
    return RoutingDecision(route="stp", reasons=["ALL_STP_CONDITIONS_MET"], approver="auto_stp")
