from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.data.loader import load_synthetic
from app.graph.deps import Deps
from app.jev.question_sets import FNOL_V1
from app.models.events import EventType
from app.service import ClaimService
from app.settings import load_config
from tests.conftest import jpeg_bytes
from tests.stubs import WATER_TEXT, StubClaude, StubJev, extraction


@pytest.fixture
def make_service(store, blobs):
    def _make(**jev_kw):
        claude = StubClaude(blobs)
        jev = StubJev(blobs, **jev_kw)
        deps = Deps(store=store, blobs=blobs, claude=claude, jev=jev, data=load_synthetic(),
                    thresholds=load_config("thresholds"), completeness=load_config("completeness"))
        return ClaimService(deps, InMemorySaver(), upto="assessment"), claude, jev
    return _make


def types(store, cid):
    return [e.type for e in store.events(cid)]


def test_complete_water_claim_is_registered(make_service, store):
    svc, claude, _ = make_service()
    cid = svc.open_claim("CUST-04")
    svc.add_text(cid, WATER_TEXT, sent_at="2026-10-17T19:40:00+02:00")
    svc.add_image(cid, jpeg_bytes())
    claude.push(extraction())

    status = svc.process(cid)

    assert status["stage"] == "join" and not status["waiting"]
    t = types(store, cid)
    assert EventType.CLAIM_REGISTERED in t
    assert t.count(EventType.FNOL_FIELD_EXTRACTED) == 5
    assert sum(1 for e in store.events(cid, {EventType.JEV_ANSWERED}) if e.payload["question_set"] == FNOL_V1) == 2
    assert svc.outbound_messages(cid)[-1]["kind"] == "registered"
    assert store.verify_chain(cid).intact


def test_missing_info_loop_waits_then_resumes(make_service, store):
    svc, claude, _ = make_service()
    cid = svc.open_claim("CUST-04")
    svc.add_text(cid, WATER_TEXT.replace(" Slang is al vervangen.", ""))
    svc.add_image(cid, jpeg_bytes())
    claude.push(extraction(source_stopped=None))

    status = svc.process(cid)
    assert status["waiting"] and status["stage"] == "awaiting_customer"
    req = [e for e in store.events(cid, {EventType.FNOL_INFO_REQUESTED})]
    assert req[0].payload["missing"] == ["source_stopped"]
    assert svc.outbound_messages(cid)[-1]["kind"] == "info_request"

    ev = svc.add_text(cid, "Ja, de kraan is dicht en de slang is vervangen.")
    claude.push(extraction(source_stopped={"value": True, "quote": "de kraan is dicht", "evidence_id": ev}))
    status = svc.process(cid)

    assert status["stage"] == "join"
    received = store.events(cid, {EventType.FNOL_INFO_RECEIVED})
    assert received[0].payload["new_evidence"] == [ev]
    assert status["info_request_rounds"] == 1


def test_gives_up_after_max_rounds_and_hands_over(make_service, store):
    svc, claude, _ = make_service()
    cid = svc.open_claim("CUST-04")
    svc.add_text(cid, WATER_TEXT)
    for _ in range(3):
        claude.push(extraction())  # never sends a photo -> damage_photo stays missing
    svc.process(cid)
    svc.add_text(cid, "Hier is meer info.")
    svc.process(cid)
    svc.add_text(cid, "Nog meer.")
    status = svc.process(cid)

    assert status["stage"] == "review"
    assert status["route_reasons"] == ["MISSING_INFO_AFTER_MAX_ROUNDS"]
    assert EventType.HUMAN_REVIEW_REQUESTED in types(store, cid)
    assert len(store.events(cid, {EventType.FNOL_INFO_REQUESTED})) == 2


def test_incident_only_skips_completeness(make_service, store):
    svc, claude, _ = make_service(peril="storm_wind_hail", only_informing=0.95)
    cid = svc.open_claim("CUST-07")
    svc.add_text(cid, "Even ter info: de boom in de tuin is omgevallen, geen schade.")
    claude.push(extraction(source=None, source_stopped=None, location=None, what_happened=None, loss_date=None))

    status = svc.process(cid)

    assert status["stage"] == "incident_only"
    t = types(store, cid)
    assert EventType.CLAIM_RECORDED_AS_INCIDENT in t
    assert EventType.FNOL_COMPLETENESS_EVALUATED not in t
    assert svc.outbound_messages(cid)[-1]["kind"] == "incident_recorded"


def test_estimate_means_claim_even_if_customer_sounds_informative(make_service, store):
    from app.models.domain import Estimate, EstimateLine

    svc, claude, _ = make_service(only_informing=0.9)
    cid = svc.open_claim("CUST-04")
    svc.add_text(cid, WATER_TEXT)
    svc.add_image(cid, jpeg_bytes())
    svc.add_estimate(cid, Estimate(contractor="x", date=None, total=380.0, lines=[
        EstimateLine(code="CEIL-PAINT", description="plafond", qty=20, unit_price=19, total=380)]))
    claude.push(extraction())
    assert svc.process(cid)["stage"] == "join"


def test_low_confidence_peril_is_treated_as_missing(make_service, store):
    svc, claude, _ = make_service(peril_conf=0.4)
    cid = svc.open_claim("CUST-04")
    svc.add_text(cid, WATER_TEXT)
    svc.add_image(cid, jpeg_bytes())
    claude.push(extraction())
    svc.process(cid)
    missing = store.events(cid, {EventType.FNOL_COMPLETENESS_EVALUATED})[-1].payload["missing"]
    assert "peril" in missing


def test_model_failure_is_logged_and_handed_over(make_service, store):
    svc, claude, _ = make_service()
    cid = svc.open_claim("CUST-04")
    svc.add_text(cid, WATER_TEXT)
    claude.fail_next = True
    status = svc.process(cid)
    assert status["stage"] == "review"
    assert EventType.SYSTEM_ERROR in types(store, cid)
    assert svc.outbound_messages(cid)[-1]["kind"] == "handover"


def test_loss_before_policy_start_is_handed_over(make_service, store):
    svc, claude, _ = make_service()
    cid = svc.open_claim("CUST-03")  # policy starts 2026-09-28
    svc.add_text(cid, WATER_TEXT)
    svc.add_image(cid, jpeg_bytes())
    claude.push(extraction(loss_date={"value": "2026-09-01", "quote": "Eergisteren", "evidence_id": "EV-0001"}))
    status = svc.process(cid)
    assert status["stage"] == "review"
    assert "LOSS_BEFORE_POLICY_START" in status["route_reasons"]


def test_hallucinated_quote_is_dropped_and_field_becomes_missing(make_service, store):
    svc, claude, _ = make_service()
    cid = svc.open_claim("CUST-04")
    svc.add_text(cid, WATER_TEXT)
    svc.add_image(cid, jpeg_bytes())
    claude.push(extraction(source_stopped={"value": True, "quote": "the plumber fixed it", "evidence_id": "EV-0001"}))
    svc.process(cid)
    finding = store.events(cid, {EventType.FINDING_CREATED})[-1].payload
    assert finding["finding"]["source_stopped"] is None
    assert any(w["code"] == "QUOTE_NOT_FOUND" for w in finding["warnings"])
    assert "source_stopped" in store.events(cid, {EventType.FNOL_COMPLETENESS_EVALUATED})[-1].payload["missing"]


def test_parallel_claim_opening_gets_unique_ids(make_service, store):
    import threading

    svc, _, _ = make_service()
    ids: list[str] = []
    threads = [threading.Thread(target=lambda: ids.append(svc.open_claim("CUST-01"))) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(ids)) == 10


def test_parallel_assessment_produces_all_three_findings(make_service, store):
    svc, claude, _ = make_service()
    cid = svc.open_claim("CUST-04")
    svc.add_text(cid, WATER_TEXT)
    svc.add_image(cid, jpeg_bytes())
    claude.push(extraction())
    status = svc.process(cid)
    agents = {e.payload["agent"] for e in store.events(cid, {EventType.FINDING_CREATED})}
    assert {"damage_agent", "policy_agent", "risk_agent"} <= agents
    assert status["stage"] == "join" and status["route_reasons"] == []
    assert EventType.VISION_EXTRACTED in types(store, cid) and EventType.RISK_SCORED in types(store, cid)
    assert store.verify_chain(cid).intact


def test_failed_agent_is_reported_at_the_join(make_service, store, monkeypatch):
    from app.agents import risk

    def boom(**_):
        raise RuntimeError("risk service down")

    monkeypatch.setattr(risk, "assess", boom)
    svc, claude, _ = make_service()
    cid = svc.open_claim("CUST-04")
    svc.add_text(cid, WATER_TEXT)
    svc.add_image(cid, jpeg_bytes())
    claude.push(extraction())
    status = svc.process(cid)
    assert status["route_reasons"] == ["ASSESSMENT_FAILED:risk_agent"]
    assert any(e.payload["node"] == "assess.risk" for e in store.events(cid, {EventType.SYSTEM_ERROR}))


def test_every_model_event_has_raw_io_provenance(make_service, store):
    svc, claude, _ = make_service()
    cid = svc.open_claim("CUST-04")
    svc.add_text(cid, WATER_TEXT)
    svc.add_image(cid, jpeg_bytes())
    claude.push(extraction())
    svc.process(cid)
    for e in store.events(cid, {EventType.FINDING_CREATED, EventType.JEV_ANSWERED, EventType.FNOL_FIELD_EXTRACTED}):
        assert e.provenance.model and e.provenance.raw_request_blob and e.provenance.raw_response_blob
