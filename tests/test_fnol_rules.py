from __future__ import annotations

from app.data.loader import load_synthetic
from app.intake.evidence import detect_language, receive_image, receive_text
from app.models.domain import Estimate, EstimateLine
from app.models.events import EventType
from app.rules.completeness import PerilAnswer, evaluate_completeness
from app.settings import load_config
from tests.conftest import jpeg_bytes
from tests.stubs import extraction

DATA = load_synthetic()
CFG = load_config("completeness")


def run(peril="water_burst_or_leak", conf=0.9, x=None, images=1, estimate=None):
    return evaluate_completeness(extraction=x if x is not None else extraction(), peril=PerilAnswer(peril, conf),
                                 image_count=images, estimate=estimate, config=CFG.data, config_version="t",
                                 min_choice_confidence=0.6, book=DATA.policy_book, prices=DATA.prices)


def est(*lines):
    return Estimate(contractor="x", date=None, lines=list(lines), total=sum(l.total for l in lines))


def test_complete_water_claim():
    r = run()
    assert r.complete and r.peril == "water_burst_or_leak"


def test_photo_required():
    assert run(images=0).missing == ["damage_photo"]


def test_catch_all_peril_counts_as_missing():
    assert "peril" in run(peril="other_unclear_cause").missing


def test_fire_report_only_required_for_larger_fires():
    small = est(EstimateLine(code="SOOT-CLEAN-ROOM", description="x", qty=1, unit_price=480, total=480))
    big = est(EstimateLine(code="FIRE-INTERIOR-REBUILD", description="x", qty=10, unit_price=900, total=9000))
    assert run(peril="fire_smoke", estimate=small).complete
    assert "fire_brigade_report" in run(peril="fire_smoke", estimate=big).missing


def test_police_report_required_only_for_theft():
    x = extraction(theft_reported={"value": True, "quote": "Eergisteren", "evidence_id": "EV-0001"})
    assert "police_report_ref_if_theft" in run(peril="theft_burglary", x=x).missing
    assert run(peril="theft_burglary").complete


def test_item_age_required_for_depreciable_lines():
    e = est(EstimateLine(code="FLOOR-WOOD-REPL", description="vloer", qty=10, unit_price=100, total=1000))
    assert "item_age:FLOOR-WOOD-REPL" in run(estimate=e).missing
    x = extraction(item_ages=[{"line_code": "FLOOR-WOOD-REPL", "age_years": 10, "quote": "Eergisteren",
                               "evidence_id": "EV-0001"}])
    assert run(estimate=e, x=x).complete


def test_language_detection():
    assert detect_language("Gisteren is de leiding gesprongen en de muur is kapot") == "nl"
    assert detect_language("Yesterday the pipe burst and the wall is damaged") == "en"


def test_intake_assigns_sequential_ids_and_records_exif_source(store, blobs):
    assert receive_text(store, "C1", "hallo") == "EV-0001"
    ev = receive_image(store, blobs, "C1", jpeg_bytes(), exif_override={"DateTimeOriginal": "2024-02-11T15:42:10"})
    assert ev == "EV-0002"
    norm = store.events("C1", {EventType.EVIDENCE_NORMALIZED})[-1].payload
    assert norm["exif_source"] == "synthetic_demo_metadata"
    assert len(norm["phash"]) == 16
