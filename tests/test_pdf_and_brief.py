"""PDF exports and the reviewer brief."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.data.loader import load_synthetic
from app.graph.deps import Deps
from app.models.domain import Estimate, EstimateLine
from app.models.events import EventType
from app.report.pdf import audit_pdf, letter_pdf
from app.service import ClaimService
from app.settings import load_config
from tests.conftest import jpeg_bytes
from tests.stubs import WATER_TEXT, StubClaude, StubJev, extraction

DATA = load_synthetic()
ESTIMATE = Estimate(contractor="Stukadoor", date=None, total=380.0, lines=[
    EstimateLine(code="CEIL-PAINT", description="Plafond sausen", qty=20, unit_price=19, total=380)])


@pytest.fixture
def svc(store, blobs):
    claude = StubClaude(blobs)
    deps = Deps(store=store, blobs=blobs, claude=claude, jev=StubJev(blobs), data=DATA,
                thresholds=load_config("thresholds"), completeness=load_config("completeness"))
    return ClaimService(deps, InMemorySaver()), claude


def run(svc, claude, customer):
    cid = svc.open_claim(customer)
    svc.add_text(cid, WATER_TEXT)
    svc.add_image(cid, jpeg_bytes())
    svc.add_estimate(cid, ESTIMATE)
    claude.push(extraction())
    svc.process(cid)
    return cid


def test_audit_pdf_for_a_paid_claim(svc, store):
    s, claude = svc
    cid = run(s, claude, "CUST-04")
    pdf = audit_pdf(store, DATA, cid)
    assert pdf.startswith(b"%PDF") and len(pdf) > 5000


def test_audit_pdf_still_renders_when_chain_is_broken(svc, store):
    from app.store.event_store import tamper_for_demo

    s, claude = svc
    cid = run(s, claude, "CUST-04")
    tamper_for_demo(store, cid, 3, {"tampered": True})
    assert audit_pdf(store, DATA, cid).startswith(b"%PDF")


def test_letter_pdf_renders_markdown_tables_and_euro_signs():
    md = "# Besluit\n\nHoi **Sanne**,\n\n| Onderdeel | Vergoed |\n|---|---|\n| Dakpannen | € 364,08 |\n\n- eigen risico € 100,00\n"
    assert letter_pdf(md, claim_id="CLM-1").startswith(b"%PDF")


def test_reviewer_brief_is_written_for_human_review(svc, store):
    s, claude = svc
    cid = run(s, claude, "CUST-02")  # tenant -> not covered -> human review
    briefs = store.events(cid, {EventType.REVIEW_BRIEF})
    assert len(briefs) == 1 and briefs[0].payload["queue"] == "claims"
    record = [c for c in claude.calls if c["prompt_version"] == "reviewer_brief_v1"][0]["content"][0]["text"]
    assert "ADVERSE_DECISION_NOT_COVERED" in record and "C-1.3" in record
    assert "reasoning" not in record  # no agent prose reaches the brief writer


def test_no_brief_for_straight_through_claims(svc, store):
    s, claude = svc
    cid = run(s, claude, "CUST-04")
    assert not store.events(cid, {EventType.REVIEW_BRIEF})
