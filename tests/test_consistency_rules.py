"""Image-claim mismatch rules (one of the five required test areas)."""

from __future__ import annotations

from app.rules.consistency import claimed_rooms, evaluate
from app.settings import load_config
from tests.stubs import observation

CFG = load_config("consistency").data
GOOD_JEV = {"photo_supports_story": 0.92, "long_term_moisture_signs": 0.05,
            "sudden_vs_gradual": ("sudden_recent_event", 0.9)}


def run(images, peril="water_burst_or_leak", location="bedroom ceiling", jev=None, items=None):
    return evaluate(images=images, peril=peril, location=location, jev=jev or GOOD_JEV, item_nouls=items or {}, cfg=CFG)


def check(checks, name):
    return next(c for c in checks if c.check == name)


def test_consistent_claim():
    result, _ = run({"EV-0002": observation()})
    assert result == "consistent"


def test_museum_photo_is_inconsistent():  # S04 / IMG-04
    result, checks = run({"EV-0002": observation(room_type="non_residential", damage_types=["swelling_buckling"])},
                         location="living room")
    assert result == "inconsistent"
    assert check(checks, "room_matches_claim").result == "fail"


def test_wrong_room_is_inconsistent():  # S06: says kitchen, photo shows bathroom
    result, checks = run({"EV-0002": observation(room_type="bathroom")}, location="kitchen ceiling")
    assert result == "inconsistent"
    assert "bathroom" in check(checks, "room_matches_claim").detail


def test_unidentifiable_room_is_not_held_against_the_customer():  # only a ceiling in frame
    result, checks = run({"EV-0002": observation(room_type="unknown")}, location="living room")
    assert check(checks, "room_matches_claim").result == "not_applicable"
    assert result == "consistent"


def test_roof_photo_compatible_with_attic_claim():
    _, checks = run({"EV-0002": observation(room_type="exterior_roof", damage_types=["roof_tiles_missing_or_broken"])},
                    peril="storm_wind_hail", location="attic / roof")
    assert check(checks, "room_matches_claim").result == "pass"


def test_damage_type_must_fit_peril():  # fire claimed, photo shows only water staining
    result, checks = run({"EV-0002": observation()}, peril="fire_smoke", location="living room")
    assert check(checks, "damage_type_fits_peril").result == "fail"
    assert result == "inconsistent"


def test_no_damage_photo_cannot_be_assessed():  # S20 / IMG-20
    result, _ = run({"EV-0002": observation(image_quality="not_a_damage_photo", damage_present=False,
                                            damage_types=[], room_type="living_room")}, location="living room")
    assert result == "cannot_assess"


def test_long_term_damage_contradicts_sudden_story():  # S07/S08/S09
    jev = {"photo_supports_story": 0.6, "long_term_moisture_signs": 0.93,
           "sudden_vs_gradual": ("gradual_long_term", 0.88)}
    result, checks = run({"EV-0002": observation(damage_types=["mould", "rot"])}, jev=jev)
    assert check(checks, "sudden_event_not_long_term").result == "fail"
    assert result == "inconsistent"


def test_low_photo_support_is_critical():
    result, _ = run({"EV-0002": observation()}, jev={**GOOD_JEV, "photo_supports_story": 0.1})
    assert result == "inconsistent"


def test_uncertain_jev_answers_make_it_partial():
    result, checks = run({"EV-0002": observation()}, jev={**GOOD_JEV, "photo_supports_story": 0.5})
    assert check(checks, "photo_supports_story").result == "unresolved"
    assert result == "partially_consistent"


def test_claimed_items_not_visible_make_it_partial():  # S01: photo shows only the trap
    result, checks = run({"EV-0002": observation()},
                         items={"KITCH-BASE-CAB": ("Replace kitchen base cabinet", 0.08)})
    assert check(checks, "item_visible:KITCH-BASE-CAB").result == "fail"
    assert result == "partially_consistent"


def test_room_keywords():
    assert claimed_rooms("bedroom ceiling", CFG) == {"bedroom"}
    assert claimed_rooms("facade / upstairs window", CFG) == {"exterior_facade"}
