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
