"""Risk thresholds and signals (one of the five required test areas)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.agents import risk
from app.data.loader import load_synthetic
from app.intake.evidence import receive_image
from app.settings import load_config
from app.store import projections as proj
from tests.stubs import StubJev

DATA = load_synthetic()
WEIGHTS = load_config("risk_weights").data
THRESH = load_config("thresholds").data
KNOWN = risk.history_hashes(DATA.history, DATA.root)


def run(store, blobs, customer="CUST-01", images=(), exif=None, loss=date(2026, 10, 14), jev=None, estimate=None):
    for img in images:
        receive_image(store, blobs, "C1", DATA.image_path(img).read_bytes(), exif_override=exif)
    c = DATA.customers[customer]
    return risk.assess(
        jev=StubJev(blobs, answers=jev), blobs=blobs, claim_id="C1", customer=c,
        policy=DATA.customer_policy(customer), loss_date=loss, reported_at=datetime(2026, 10, 15, 9),
        texts=[], images=proj.images(store, "C1"), estimate=estimate, prices=DATA.prices, tolerance=0.1,
        past_claims=DATA.history, known_hashes=KNOWN, weights_cfg=WEIGHTS, thresholds=THRESH,
        duplicate_threshold=DATA.history_meta["duplicate_threshold_hamming"],
    ).output.finding


def signal(f, name):
    return next(s for s in f.signals if s.signal == name)


def test_duplicate_of_past_claim_photo_is_a_hard_flag(store, blobs):  # S13
    f = run(store, blobs, images=["IMG-13"])
    assert f.hard_flags == ["duplicate_image"] and f.band == "high"


def test_same_scene_different_photo_is_not_a_duplicate(store, blobs):  # S14 must stay clean
    f = run(store, blobs, images=["IMG-14"])
    assert f.hard_flags == []


@pytest.mark.parametrize("image_id", [i for i in sorted(DATA.observations) if i != "IMG-13"])
def test_no_other_demo_image_collides_with_history(store, blobs, image_id):
    assert run(store, blobs, images=[image_id]).hard_flags == []


def test_exif_before_loss_date(store, blobs):  # S08
    f = run(store, blobs, images=["IMG-08"], exif={"DateTimeOriginal": "2024-02-11T15:42:10"})
    assert signal(f, "exif_before_loss_date").strength == 1.0


def test_gps_far_from_insured_address(store, blobs):
    f = run(store, blobs, images=["IMG-14"], exif={"DateTimeOriginal": "2026-10-15T09:14:02",
                                                   "GPS": {"lat": 51.92, "lon": 4.48}})  # Rotterdam vs Utrecht
    assert signal(f, "gps_far_from_address").strength == 1.0


def test_recent_policy_and_frequency(store, blobs):
    new = run(store, blobs, customer="CUST-03", loss=date(2026, 10, 17))
    assert signal(new, "policy_started_lt_60_days").strength == 1.0
    henk = run(store, blobs, customer="CUST-06")
    assert signal(henk, "claim_frequency_3y").contribution == pytest.approx(0.30)


def test_score_bands_follow_thresholds(store, blobs):
    clean = run(store, blobs, jev={"story_consistent": 0.95, "timeline_plausible": 0.95})
    assert clean.band == "low" and clean.score < THRESH["risk"]["human_from"]
    # A doubtful story plus claim frequency is worth a human look, not a fraud referral...
    shaky = run(store, blobs, customer="CUST-06", jev={"story_consistent": 0.2, "timeline_plausible": 0.3})
    assert shaky.band == "medium"


def test_old_photo_plus_frequency_and_doubtful_story_reaches_siu(store, blobs):  # S08
    f = run(store, blobs, customer="CUST-06", images=["IMG-08"], exif={"DateTimeOriginal": "2024-02-11T15:42:10"},
            jev={"story_consistent": 0.4, "timeline_plausible": 0.3, "photo_supports_story": 0.3})
    assert f.score >= THRESH["risk"]["siu_from"] and f.band == "high"


def test_every_signal_carries_weight_and_detail(store, blobs):
    f = run(store, blobs, customer="CUST-06", images=["IMG-08"], exif={"DateTimeOriginal": "2024-02-11T15:42:10"})
    assert f.score == pytest.approx(min(1, sum(s.contribution for s in f.signals)), abs=1e-3)
    assert all(s.detail for s in f.signals)
