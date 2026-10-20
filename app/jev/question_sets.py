"""Versioned Jev question sets. Option names are self-explanatory and every choice has a catch-all
(README 8.1 note: the decision head follows option names more than descriptions)."""

from __future__ import annotations

FNOL_V1 = "fnol_v2"  # v2: claim-vs-incident asks for an explicit "only informing" statement

PERILS = {
    "water_burst_or_leak": "Water escaped from a pipe, hose, appliance, tap, drain, heating or plumbing inside the home",
    "flood_surface_water": "Water came in from outside at ground level: flooded street, river, rain runoff or groundwater",
    "storm_wind_hail": "Storm, wind, hail or a fallen tree caused the damage, including rain entering through storm damage",
    "fire_smoke": "Fire, smoke, soot, scorching or an electrical fire",
    "theft_burglary": "Break-in, attempted break-in, forced entry, theft or vandalism by intruders",
    "accidental_damage": "Accidental breakage, such as glass broken by a ball or something dropped, knocked or hit",
    "other_unclear_cause": "Another cause, or the messages do not say what caused the damage",
}


DAMAGE_V1 = "damage_v1"
RISK_V1 = "risk_v1"
POLICY_V1 = "policy_v1"

SEVERITY = {
    "none_no_visible_damage": "No visible damage",
    "minor_surface_staining": "Light staining, surface marks or a small isolated defect only",
    "moderate_localized_damage": "Localized damage to materials in one area",
    "severe_extensive_damage": "Extensive damage across multiple surfaces, materials or rooms",
    "other_cannot_assess": "The photos do not allow an assessment",
}

SUDDEN_VS_GRADUAL = {
    "sudden_recent_event": "Fresh damage consistent with a single recent event",
    "gradual_long_term": "Signs of long-term exposure or neglect: mould, rot, rust, layered tide marks, weathering",
    "unclear_cannot_tell": "Cannot tell from the photos",
}


def photo_refs(n: int) -> str:
    refs = ", ".join(f"`photo_{i}`" for i in range(1, n + 1))
    return f"the photo {refs}" if n == 1 else f"the photos ({refs})"


def damage_questions(peril: str | None, n_photos: int, items: dict[str, str]) -> dict[str, dict]:
    """`items` maps question-safe keys (item_1 ...) to English item labels from the estimate."""
    photos = photo_refs(n_photos)
    q: dict[str, dict] = {
        "severity": {"type": "choice", "instructions": f"How severe is the visible damage in {photos}?",
                     "criteria": SEVERITY},
        "sudden_vs_gradual": {"type": "choice", "instructions": f"Does the damage in {photos} look sudden or gradual?",
                              "criteria": SUDDEN_VS_GRADUAL},
        "photo_supports_story": {"type": "noul", "instructions": f"Do {photos} support the customer's account in `story`?"},
        "long_term_moisture_signs": {"type": "noul",
                                     "instructions": f"Are there signs of mould, rot, rust or long-term moisture in {photos}?"},
    }
    for key, label in items.items():
        q[key] = {"type": "noul", "instructions": f"Is the following item visibly damaged in {photos}: {label}?"}
    if peril == "fire_smoke":
        q["open_fire_evident"] = {"type": "noul", "instructions":
            f"Do `story` and {photos} indicate an actual fire with flames, rather than only scorching or melting?"}
    if peril == "storm_wind_hail":
        q["roof_maintenance_poor"] = {"type": "noul", "instructions":
            f"Do {photos} show signs of poor maintenance or long-standing deterioration of the roof "
            "(weathered or rotten battens, moss or lichen, gaps without fresh debris)?"}
        q["building_damage_present"] = {"type": "noul", "instructions": f"Do {photos} show damage to the building itself?"}
    if peril == "theft_burglary":
        q["forced_entry_visible"] = {"type": "noul", "instructions":
            f"Do {photos} show signs of forced entry such as a split frame, broken lock or pried door or window?"}
    return q


def risk_questions(n_photos: int) -> dict[str, dict]:
    q: dict[str, dict] = {
        "story_consistent": {"type": "noul", "instructions": "Is the account in `messages` internally consistent?"},
        "timeline_plausible": {"type": "noul", "instructions":
            "Given `reported_at` and `messages`, is the timeline of events plausible?"},
    }
    if n_photos:
        q["photo_supports_story"] = {"type": "noul",
                                     "instructions": f"Do {photo_refs(n_photos)} support the account in `messages`?"}
    return q


def policy_questions() -> dict[str, dict]:
    return {
        "home_unoccupied_over_60_days": {"type": "noul", "instructions":
            "According to `messages`, had the home been unoccupied for more than 60 days in a row when the damage happened?"},
    }


def fnol_questions() -> dict[str, dict]:
    return {
        "peril": {
            "type": "choice",
            "instructions": "What caused the damage the customer describes in `messages`?",
            "criteria": PERILS,
        },
        # Asymmetric on purpose: a claim is the default. Only an explicit "just letting you know /
        # no need to pay" makes it an incident (wrongly treating a claim as an incident hurts the customer).
        "only_informing": {
            "type": "noul",
            "instructions": "In `messages`, does the customer explicitly say they are only informing the insurer "
                            "and do not want compensation or a repair (for example 'just letting you know', "
                            "'no damage', 'no need to pay anything')?",
        },
    }
