"""End-to-end decision layer with stubbed models: STP, human review, overrides, SIU, info loops."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.data.loader import load_synthetic
from app.graph.deps import Deps
from app.models.domain import Estimate, EstimateLine
from app.models.events import EventType
from app.service import ClaimService
from app.settings import load_config
from tests.conftest import jpeg_bytes
from tests.stubs import WATER_TEXT, StubClaude, StubJev, extraction

DATA = load_synthetic()

S02_ESTIMATE = Estimate(contractor="Stukadoor", date=None, total=881.0, lines=[
    EstimateLine(code="PLB-HOSE-REPL", description="Toevoerslang", qty=1, unit_price=85, total=85),
    EstimateLine(code="CEIL-PLAST-REPAIR", description="Plafond herstellen", qty=8, unit_price=52, total=416),
    EstimateLine(code="CEIL-PAINT", description="Plafond sausen", qty=20, unit_price=19, total=380),
])


@pytest.fixture
def make(store, blobs):
    def _make(**jev):
        claude, stub_jev = StubClaude(blobs), StubJev(blobs, **jev)
        deps = Deps(store=store, blobs=blobs, claude=claude, jev=stub_jev, data=DATA,
                    thresholds=load_config("thresholds"), completeness=load_config("completeness"))
        return ClaimService(deps, InMemorySaver()), claude
    return _make


def start(svc, claude, customer="CUST-04", estimate=S02_ESTIMATE, image=None):
    cid = svc.open_claim(customer)
    svc.add_text(cid, WATER_TEXT, sent_at="2026-10-17T19:40:00+02:00")
    svc.add_image(cid, image or jpeg_bytes())
    if estimate:
        svc.add_estimate(cid, estimate)
    claude.push(extraction())
    return cid, svc.process(cid)


def one(store, cid, etype):
    events = store.events(cid, {etype})
    return events[-1].payload if events else None


def test_stp_pays_the_golden_amount_and_closes(make, store):
    svc, claude = make()
    cid, status = start(svc, claude)
    assert status["stage"] == "closed"
    assert one(store, cid, EventType.ROUTING_DECIDED)["route"] == "stp"
    assert one(store, cid, EventType.PAYMENT_INSTRUCTED)["amount"] == 296.00  # golden S02
    assert one(store, cid, EventType.LETTER_GENERATED)["record"]["payout"] == 296.00
    report = svc.report(cid)
    assert report.human_approval.status == "not_required"
    assert report.payout_recommendation.payout == 296.00 and report.audit_trail.chain_intact
    assert EventType.CLAIM_CLOSED in [e.type for e in store.events(cid)]


def test_every_payout_step_is_a_rule_event(make, store):
    svc, claude = make()
    cid, _ = start(svc, claude)
    rules = [e.payload["rule_id"] for e in store.events(cid, {EventType.RULE_EVALUATED})]
    for rid in ("PAY-BENCH-01", "COV-LINE-EXCL-01", "PAY-CAP-01", "PAY-DEDUCT-01"):
        assert rid in rules


def test_refusal_waits_for_human_and_approval_closes_without_payment(make, store):
    svc, claude = make()
    cid, status = start(svc, claude, customer="CUST-02", estimate=Estimate(contractor="x", date=None, total=380.0,
                        lines=[EstimateLine(code="CEIL-PAINT", description="plafond", qty=20, unit_price=19, total=380)]))
    assert status["waiting_for"] == "awaiting_human_review"
    assert "ADVERSE_DECISION_NOT_COVERED" in one(store, cid, EventType.ROUTING_DECIDED)["reasons"]
    assert svc.outbound_messages(cid)[-1]["kind"] == "handover"

    svc.add_text(cid, "Any news?")  # customer chatting must NOT resume a claim waiting for a human
    assert svc.process(cid)["waiting_for"] == "awaiting_human_review"

    status = svc.review(cid, {"action": "approve", "reviewer_id": "U-17", "reviewer_role": "claims_handler"})
    assert status["stage"] == "closed"
    assert not store.events(cid, {EventType.PAYMENT_INSTRUCTED})
    decision = store.events(cid, {EventType.HUMAN_DECISION})[-1]
    assert decision.actor.kind == "human" and decision.actor.id == "U-17"
    assert svc.report(cid).human_approval.status == "approved"


def test_override_requires_a_reason_and_pays_the_override(make, store):
    svc, claude = make()
    cid, _ = start(svc, claude, customer="CUST-02", estimate=Estimate(contractor="x", date=None, total=380.0,
                   lines=[EstimateLine(code="CEIL-PAINT", description="plafond", qty=20, unit_price=19, total=380)]))
    with pytest.raises(Exception, match="reason"):
        svc.review(cid, {"action": "override", "reviewer_id": "U-1", "reviewer_role": "senior", "payout_override": 100})
    svc.review(cid, {"action": "override", "reviewer_id": "U-1", "reviewer_role": "senior", "payout_override": 150.0,
                     "reason": "Goodwill: landlord unreachable, tenant paid repaint"})
    assert one(store, cid, EventType.PAYMENT_INSTRUCTED)["amount"] == 150.0
    assert svc.report(cid).human_approval.status == "overridden"


def test_reviewer_can_ask_the_customer_and_claim_is_reassessed(make, store):
    svc, claude = make()
    cid, _ = start(svc, claude, customer="CUST-02", estimate=Estimate(contractor="x", date=None, total=380.0,
                   lines=[EstimateLine(code="CEIL-PAINT", description="plafond", qty=20, unit_price=19, total=380)]))
    status = svc.review(cid, {"action": "request_info", "reviewer_id": "U-2", "reviewer_role": "claims_handler",
                              "info_needed": ["Did you inform your landlord?"]})
    assert status["waiting_for"] == "awaiting_customer_info"
    assert one(store, cid, EventType.FNOL_INFO_REQUESTED)["missing"] == ["ask:Did you inform your landlord?"]
    svc.add_text(cid, "Yes, the landlord knows.")
    claude.push(extraction())
    status = svc.process(cid)
    assert status["waiting_for"] == "awaiting_human_review"  # reassessed, still a refusal -> back to the human
    assert len(store.events(cid, {EventType.CLAIM_REGISTERED})) == 1  # registration is idempotent
    assert len(store.events(cid, {EventType.ROUTING_DECIDED})) == 2


def test_duplicate_photo_goes_to_siu(make, store):
    svc, claude = make()
    cid, status = start(svc, claude, image=DATA.image_path("IMG-13").read_bytes())
    routing = one(store, cid, EventType.ROUTING_DECIDED)
    assert routing["route"] == "siu" and routing["approver"] == "special_investigations"
    assert one(store, cid, EventType.HUMAN_REVIEW_REQUESTED)["queue"] == "siu"
    assert status["waiting_for"] == "awaiting_human_review"


def test_item_not_visible_asks_for_photo_then_hands_over(make, store):
    svc, claude = make(answers={"item_1": 0.05})  # CEIL-PLAST-REPAIR clearly not visible
    cid, status = start(svc, claude)
    assert status["waiting_for"] == "awaiting_customer_info"
    assert one(store, cid, EventType.FNOL_INFO_REQUESTED)["missing"][0].startswith("photo_of:")
    svc.add_image(cid, jpeg_bytes(900, 700))
    claude.push(extraction())
    status = svc.process(cid)
    assert status["waiting_for"] == "awaiting_customer_info"  # second (last) round
    svc.add_image(cid, jpeg_bytes(950, 700))
    claude.push(extraction())
    status = svc.process(cid)
    assert status["waiting_for"] == "awaiting_human_review"
    assert store.verify_chain(cid).intact


def test_missing_damage_evidence_is_not_a_fraud_signal(make, store):  # S20: intact room photo
    from tests.stubs import observation

    svc, claude = make(answers={"photo_supports_story": 0.05})
    claude.push(observation(image_quality="not_a_damage_photo", damage_present=False, damage_types=[]))
    cid, status = start(svc, claude)
    joined = [e.payload for e in store.events(cid, {EventType.RISK_SCORED}) if e.payload.get("stage") == "join"][-1]
    assert joined["added_signals"] == []
    assert one(store, cid, EventType.ROUTING_DECIDED)["route"] == "info_request"


def test_replay_reproduces_logged_outcomes(make, store):
    from app.audit.replay import replay

    svc, claude = make()
    cid, _ = start(svc, claude)  # STP
    r = replay(store, DATA, cid)
    assert r.replayable and r.all_match
    assert {c.item for c in r.checks} == {"coverage", "payout", "route"}

    cid2, _ = start(svc, claude, customer="CUST-02", estimate=Estimate(contractor="x", date=None, total=380.0,
                    lines=[EstimateLine(code="CEIL-PAINT", description="plafond", qty=20, unit_price=19, total=380)]))
    assert replay(store, DATA, cid2).all_match  # refusal waiting for review replays too


def test_image_mismatch_raises_final_risk(make, store):
    svc, claude = make(answers={"photo_supports_story": 0.05})
    cid, _ = start(svc, claude)
    joined = [e.payload for e in store.events(cid, {EventType.RISK_SCORED}) if e.payload.get("stage") == "join"][-1]
    assert joined["added_signals"][0]["signal"] == "image_claim_mismatch"
    assert joined["score"] == pytest.approx(joined["base_score"] + 0.30)
