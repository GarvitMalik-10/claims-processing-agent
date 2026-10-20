"""Routing decisions at every threshold edge (one of the five required test areas)."""

from __future__ import annotations

import pytest

from app.models.assessment import ConsistencyCheck
from app.rules.routing import approver_for, decide
from app.settings import load_config

TH = load_config("thresholds").data
AUTH = load_config("authority").data


def chk(name, result, severity="minor", source="jev"):
    return ConsistencyCheck(check=name, result=result, severity=severity, source=source, detail="d")


def route(**kw):
    base = dict(coverage_status="covered", coverage_reasons=[], consistency="consistent", checks=[], risk_score=0.1,
                hard_flags=[], payout=1000.0, critical_warnings=[], failed_agents=[], info_rounds_used=0,
                thresholds=TH, authority=AUTH)
    base.update(kw)
    return decide(**base)


def test_clean_claim_goes_stp():
    d = route()
    assert d.route == "stp" and d.approver == "auto_stp"


@pytest.mark.parametrize("score,expected", [(0.299, "stp"), (0.3, "human_review"), (0.699, "human_review"), (0.7, "siu")])
def test_risk_thresholds(score, expected):
    assert route(risk_score=score).route == expected


def test_hard_flag_wins_regardless_of_score():
    d = route(risk_score=0.0, hard_flags=["duplicate_image"])
    assert d.route == "siu" and d.reasons == ["HARD_FLAG:duplicate_image"]


@pytest.mark.parametrize("payout,route_,approver", [
    (5000.0, "stp", "auto_stp"), (5000.01, "human_review", "claims_handler"),
    (25000.0, "human_review", "claims_handler"), (25000.01, "human_review", "senior_handler"),
])
def test_stp_limit_and_authority(payout, route_, approver):
    d = route(payout=payout)
    assert (d.route, d.approver) == (route_, approver)


def test_authority_matrix():
    assert approver_for(0, AUTH) == "auto_stp" and approver_for(10**7, AUTH) == "senior_handler"


@pytest.mark.parametrize("status,reason", [("not_covered", "ADVERSE_DECISION_NOT_COVERED"),
                                           ("partially_covered", "ADVERSE_DECISION_PARTIAL"),
                                           ("unresolved", "COVERAGE_UNRESOLVED")])
def test_denials_and_unresolved_coverage_always_go_to_a_human(status, reason):
    d = route(coverage_status=status)
    assert d.route == "human_review" and reason in d.reasons


def test_inconsistent_photos_go_to_a_human():
    d = route(consistency="inconsistent", checks=[chk("room_matches_claim", "fail", "critical", "rule")])
    assert d.route == "human_review" and "IMAGE_CLAIM_INCONSISTENT" in d.reasons


def test_no_damage_photo_asks_customer_then_human():
    first = route(consistency="cannot_assess")
    assert first.route == "info_request" and first.info_needed == ["damage_photo"]
    exhausted = route(consistency="cannot_assess", info_rounds_used=TH["missing_info"]["max_rounds"])
    assert exhausted.route == "human_review" and "IMAGE_EVIDENCE_INSUFFICIENT" in exhausted.reasons


def test_item_clearly_not_visible_asks_for_photo():  # S01
    d = route(consistency="partially_consistent", checks=[chk("item_visible:KITCH-BASE-CAB", "fail")])
    assert d.route == "info_request" and d.info_needed == ["photo_of:KITCH-BASE-CAB"]


def test_uncertain_minor_item_does_not_block_stp():  # decision 2026-10-20, S19
    d = route(consistency="partially_consistent", checks=[chk("item_visible:LOCK-REPL", "unresolved")])
    assert d.route == "stp"


def test_uncertain_critical_jev_answer_blocks_stp():
    d = route(consistency="partially_consistent", checks=[chk("photo_supports_story", "unresolved", "critical")])
    assert d.route == "human_review" and "JEV_UNCERTAIN:photo_supports_story" in d.reasons


def test_critical_warning_and_failed_agent_go_to_a_human():
    assert route(critical_warnings=["ITEM_AGE_UNKNOWN"]).route == "human_review"
    d = route(failed_agents=["risk_agent"])
    assert d.route == "human_review" and "ASSESSMENT_FAILED:risk_agent" in d.reasons


def test_self_reported_confidence_cannot_reach_the_gate():
    # The gate's signature only accepts rule outcomes and measured values - there is no parameter
    # through which a model's self-reported confidence could influence routing.
    import inspect

    params = set(inspect.signature(decide).parameters)
    assert not any("confidence" in p for p in params)
