"""FNOL completeness (README 7.2 step 3): per-peril required-fields matrix from config/completeness.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.domain import Estimate, PolicyBook, PriceBook
from app.models.fnol import CompletenessResult, FnolExtraction

RULE_ID = "FNOL-COMPLETE-01"


@dataclass(frozen=True)
class PerilAnswer:
    choice: str | None
    confidence: float | None


def evaluate_completeness(
    *,
    extraction: FnolExtraction | None,
    peril: PerilAnswer,
    image_count: int,
    estimate: Estimate | None,
    config: dict[str, Any],
    config_version: str,
    min_choice_confidence: float,
    book: PolicyBook,
    prices: PriceBook,
) -> CompletenessResult:
    x = extraction
    satisfied: dict[str, str] = {}
    missing: list[str] = []

    peril_ok = (
        peril.choice is not None
        and peril.choice != config.get("catch_all_peril")
        and (peril.confidence or 0) >= min_choice_confidence
    )
    required = list(config["common"])
    if peril_ok:
        required += config["perils"].get(peril.choice, [])

    for f in required:
        ok, where = _check(f, x, peril_ok, peril, image_count, estimate, config)
        if ok:
            satisfied[f] = where
        elif ok is False:
            missing.append(f)

    if config.get("require_item_age_for_depreciable") and estimate:
        given = {a.line_code for a in (x.item_ages if x else [])}
        for line in estimate.lines:
            item = prices.items.get(line.code)
            row = book.depreciation_row(item.category) if item else None
            if row and row.depreciable:
                key = f"item_age:{line.code}"
                if line.age_years is not None:
                    satisfied[key] = "estimate"
                elif line.code in given:
                    satisfied[key] = "customer message"
                else:
                    missing.append(key)

    return CompletenessResult(complete=not missing, peril=peril.choice if peril_ok else None, missing=missing,
                              satisfied=satisfied, rule_set_version=config_version)


def _check(field: str, x: FnolExtraction | None, peril_ok: bool, peril: PerilAnswer, image_count: int,
           estimate: Estimate | None, config: dict[str, Any]) -> tuple[bool | None, str]:
    """(True, where) satisfied, (False, '') missing, (None, '') not applicable."""
    def sourced(v: Any) -> tuple[bool, str]:
        return (True, v.evidence_id) if v is not None else (False, "")

    match field:
        case "peril":
            return (True, "jev") if peril_ok else (False, "")
        case "loss_date":
            return sourced(x.loss_date if x else None)
        case "location":
            return sourced(x.location if x else None)
        case "source":
            return sourced(x.source if x else None)
        case "source_stopped":
            return sourced(x.source_stopped if x else None)
        case "damage_photo":
            return (True, f"{image_count} image(s)") if image_count else (False, "")
        case "fire_brigade_report":
            threshold = config.get("fire_brigade_report_required_above", 0)
            if estimate is None or estimate.total <= threshold:
                return None, ""
            return sourced(x.fire_brigade_report_ref if x else None)
        case "police_report_ref_if_theft":
            if not (x and x.theft_reported and x.theft_reported.value):
                return None, ""
            return sourced(x.police_report_ref)
    raise ValueError(f"Unknown completeness field {field!r} in config")
