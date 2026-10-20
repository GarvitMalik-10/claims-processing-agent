"""Image-claim consistency (README 8.1 step 3). Two independent signal families:
vision-extracted facts compared by rules, and Jev's measured judgement. Plain, tested code."""

from __future__ import annotations

import re
from typing import Any

from app.models.assessment import ConsistencyCheck, ImageObservation

RULE_ID = "DMG-CONSIST-01"
BAND = (0.25, 0.75)


def _noul_check(name: str, p: float | None, *, critical: bool, detail: str, ev: list[str]) -> ConsistencyCheck:
    if p is None:
        return ConsistencyCheck(check=name, result="not_applicable", severity="minor", source="jev", detail="not asked")
    if p >= BAND[1]:
        res = "pass"
    elif p <= BAND[0]:
        res = "fail"
    else:
        res = "unresolved"
    return ConsistencyCheck(check=name, result=res, severity="critical" if critical else "minor", source="jev",
                            detail=f"{detail} (p={p:.2f})", evidence_ids=ev)


def claimed_rooms(location: str | None, cfg: dict[str, Any]) -> set[str]:
    if not location:
        return set()
    # Match at word starts: "stair" matches "stairwell" but not "upstairs", "hall" not "bathroom".
    text = location.lower()
    return {room for room, words in cfg["room_keywords"].items()
            if any(re.search(r"\b" + re.escape(w), text) for w in words)}


def evaluate(
    *,
    images: dict[str, ImageObservation],
    peril: str | None,
    location: str | None,
    jev: dict[str, Any],
    item_nouls: dict[str, tuple[str, float]],
    cfg: dict[str, Any],
) -> tuple[str, list[ConsistencyCheck]]:
    """`jev` holds fact values (nouls as floats, choices as (choice, confidence)); returns (result, checks)."""
    ids = list(images)
    checks: list[ConsistencyCheck] = []

    usable = {i: o for i, o in images.items() if o.image_quality != "not_a_damage_photo"}
    damaged = [i for i, o in images.items() if o.damage_present]
    checks.append(ConsistencyCheck(
        check="damage_visible", result="pass" if damaged else "fail", severity="critical", source="rule",
        detail=f"damage visible in {len(damaged)} of {len(images)} photo(s)", evidence_ids=damaged or ids))
    poor = [i for i, o in images.items() if o.image_quality in ("blurry", "too_dark", "partial_view")]
    if poor:
        checks.append(ConsistencyCheck(check="image_quality", result="unresolved", severity="minor", source="rule",
                                       detail=f"limited quality: {', '.join(poor)}", evidence_ids=poor))

    # Room: claimed location vs what the photos show
    claimed = claimed_rooms(location, cfg)
    bad = [i for i, o in usable.items() if o.room_type in cfg["always_inconsistent_rooms"]]
    informative = {i: o.room_type for i, o in usable.items() if o.room_type not in cfg["uninformative_rooms"]}
    if bad:
        checks.append(ConsistencyCheck(check="room_matches_claim", result="fail", severity="critical", source="rule",
                                       detail=f"photo shows a non-residential setting ({', '.join(bad)})", evidence_ids=bad))
    elif not claimed or not informative:
        checks.append(ConsistencyCheck(check="room_matches_claim", result="not_applicable", severity="minor",
                                       source="rule", detail="room not stated or not identifiable in photos"))
    else:
        allowed = set(claimed)
        for r in claimed:
            allowed |= set(cfg["compatible_rooms"].get(r, []))
        matching = [i for i, r in informative.items() if r in allowed]
        detail = f"claimed {sorted(claimed)}; photos show {sorted(set(informative.values()))}"
        checks.append(ConsistencyCheck(check="room_matches_claim", result="pass" if matching else "fail",
                                       severity="critical", source="rule", detail=detail,
                                       evidence_ids=list(informative)))

    # Damage types vs claimed peril
    expected = set(cfg["expected_damage_types"].get(peril or "", []))
    seen = {t for o in usable.values() for t in o.damage_types}
    if expected and seen:
        overlap = sorted(seen & expected)
        checks.append(ConsistencyCheck(
            check="damage_type_fits_peril", result="pass" if overlap else "fail", severity="critical", source="rule",
            detail=f"{peril}: photos show {sorted(seen)}" + (f", matching {overlap}" if overlap else ", none expected"),
            evidence_ids=list(usable)))

    checks.append(_noul_check("photo_supports_story", jev.get("photo_supports_story"), critical=True,
                              detail="Jev: photos support the customer's account", ev=ids))

    # Timing: claims are for sudden events; long-term damage contradicts that. The sudden-vs-gradual
    # choice leads; the long-term-moisture noul only overrides it when clearly high.
    choice, conf = jev.get("sudden_vs_gradual") or (None, None)
    lt = jev.get("long_term_moisture_signs")
    confident = (conf or 0) >= 0.6
    if (choice == "gradual_long_term" and confident) or (lt is not None and lt >= BAND[1]):
        res, sev = "fail", "critical"
    elif choice == "sudden_recent_event" and confident:
        res, sev = "pass", "critical"
    elif choice is None and lt is not None and lt <= BAND[0]:
        res, sev = "pass", "critical"
    else:
        res, sev = "unresolved", "minor"
    checks.append(ConsistencyCheck(check="sudden_event_not_long_term", result=res, severity=sev, source="jev",
                                   detail=f"sudden_vs_gradual={choice} ({conf}), long_term_moisture_signs={lt}",
                                   evidence_ids=ids))

    for code, (label, p) in item_nouls.items():
        checks.append(_noul_check(f"item_visible:{code}", p, critical=False, detail=f"{label} visibly damaged", ev=ids))

    if any(c.check == "damage_visible" and c.result == "fail" for c in checks):
        result = "cannot_assess"
    elif any(c.result == "fail" and c.severity == "critical" for c in checks):
        result = "inconsistent"
    elif any(c.result in ("fail", "unresolved") for c in checks):
        result = "partially_consistent"
    else:
        result = "consistent"
    return result, checks
