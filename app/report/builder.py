"""Build the ClaimDecisionReport (README 5.3) purely from the claim file - always reconstructable."""

from __future__ import annotations

from datetime import date

from app.data.loader import SyntheticData
from app.jev.question_sets import DAMAGE_V1
from app.models.events import EventType
from app.models.report import (
    AuditTrailSummary,
    ClaimDecisionReport,
    ClaimSummary,
    ConsistencyCheck,
    CoverageDecision,
    HumanApproval,
    ImageAssessment,
    ImageClaimConsistency,
    PayoutRecommendation,
    RiskScore,
    RiskSignal,
)
from app.models.common import Warning
from app.store import projections as proj
from app.store.event_store import EventStore

APPROVAL = {"approve": "approved", "override": "overridden", "request_info": "info_requested",
            "escalate_siu": "escalated_siu"}


def _finding(store: EventStore, cid: str, agent: str) -> dict | None:
    e = proj.latest(store, cid, EventType.FINDING_CREATED, agent=agent)
    return e.payload if e else None


def build_report(store: EventStore, data: SyntheticData, cid: str) -> ClaimDecisionReport:
    note = proj.notification(store, cid)
    reg = proj.latest(store, cid, EventType.CLAIM_REGISTERED)
    comp = proj.latest(store, cid, EventType.FNOL_COMPLETENESS_EVALUATED)
    fnol = _finding(store, cid, "fnol_extractor")
    x = fnol["finding"] if fnol else {}
    peril = comp.payload["peril"] if comp else None
    loss = reg.payload.get("loss_date") if reg else None
    location = (x.get("location") or {}).get("value")
    kinds = sorted({i.kind for i in proj.evidence(store, cid)})
    summary = ClaimSummary(
        claim_id=cid, customer_id=note["customer_id"], policy_id=reg.payload["policy_id"] if reg else None,
        peril=peril, loss_date=date.fromisoformat(loss) if loss else None, location=location, channels=kinds,
        language=x.get("language", note.get("language_preference", "nl")),
        text={"en": fnol["summary"] if fnol else "",
              "nl": f"Melding: {(peril or 'onbekend').replace('_', ' ')}, {loss or 'datum onbekend'}, {location or 'locatie onbekend'}."},
    )

    images: list[ImageAssessment] = []
    consistency = None
    dmg = _finding(store, cid, "damage_agent")
    if dmg:
        f = dmg["finding"]
        sev = proj.jev_answers(store, cid, DAMAGE_V1).get("severity", {}).get("answer", {})
        for ev, o in f["images"].items():
            images.append(ImageAssessment(evidence_id=ev, room_type=o["room_type"], damage_types=o["damage_types"],
                                          severity=f["severity"], severity_probabilities=sev.get("probabilities") or {},
                                          visible_items=o["visible_items"],
                                          warnings=[Warning(**w) for w in dmg["warnings"] if ev in w["message"]]))
        consistency = ImageClaimConsistency(result=f["consistency"], checks=[
            ConsistencyCheck(check=c["check"], passed={"pass": True, "fail": False}.get(c["result"]),
                             source=c["source"], detail=c["detail"]) for c in f["checks"]])

    cov_e = proj.latest(store, cid, EventType.COVERAGE_RESOLVED)
    coverage = CoverageDecision(status=cov_e.payload["status"], clauses=cov_e.payload["clauses"]) if cov_e else None

    risk = None
    rsk = _finding(store, cid, "risk_agent")
    joined = proj.latest(store, cid, EventType.RISK_SCORED, stage="join")
    if rsk:
        rf = rsk["finding"]
        signals = [RiskSignal(signal=s["signal"], strength=s["strength"], weight=s["weight"],
                              contribution=s["contribution"], source=s["source"]) for s in rf["signals"]]
        for a in (joined.payload["added_signals"] if joined else []):
            signals.append(RiskSignal(signal=a["signal"], strength=1.0, weight=a["contribution"],
                                      contribution=a["contribution"], source="rule"))
        risk = RiskScore(score=joined.payload["score"] if joined else rf["score"], signals=signals,
                         hard_flags=rf["hard_flags"])

    pay_e = proj.latest(store, cid, EventType.PAYOUT_CALCULATED)
    payout = (PayoutRecommendation.model_validate(pay_e.payload["recommendation"])
              if pay_e and pay_e.payload.get("recommendation") else None)

    route_e = proj.latest(store, cid, EventType.ROUTING_DECIDED)
    human = proj.latest(store, cid, EventType.HUMAN_DECISION)
    if human:
        approval = HumanApproval(status=APPROVAL[human.payload["action"]], reviewer_id=human.actor.id,
                                 reviewer_role=human.actor.role, reason=human.payload.get("reason"),
                                 decided_at=human.timestamp)
    elif route_e and route_e.payload["route"] == "stp":
        approval = HumanApproval(status="not_required")
    else:
        approval = HumanApproval(status="pending")

    chain = store.verify_chain(cid)
    versions: dict[str, str] = {}
    for e in store.events(cid):
        versions.update(e.provenance.config_versions)
    return ClaimDecisionReport(
        claim_summary=summary, image_assessment=images, image_claim_consistency=consistency,
        coverage_decision=coverage, risk_score=risk, payout_recommendation=payout,
        route=route_e.payload["route"] if route_e else None,
        route_reasons=route_e.payload["reasons"] if route_e else [], human_approval=approval,
        audit_trail=AuditTrailSummary(event_count=chain.event_count, chain_intact=chain.intact,
                                      first_broken_seq=chain.first_broken_seq, config_versions=versions),
    )
