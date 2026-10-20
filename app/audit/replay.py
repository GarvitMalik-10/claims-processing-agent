"""Replay (README 6.5): recompute coverage, payout and route from the claim file alone and prove they
match what was logged. Uses only logged findings + rules + current config - no model calls."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.data.loader import SyntheticData
from app.models.assessment import DamageFinding, PolicyFinding
from app.models.events import EventType
from app.rules import coverage as coverage_rules
from app.rules import routing as routing_rules
from app.rules.payout import calculate_payout
from app.settings import load_config
from app.store import projections as proj
from app.store.event_store import EventStore


class ReplayCheck(BaseModel):
    item: str
    logged: Any
    replayed: Any
    match: bool


class ReplayResult(BaseModel):
    claim_id: str
    replayable: bool
    all_match: bool
    checks: list[ReplayCheck]
    note: str | None = None
    config_changed: list[str] = []


def _finding(store: EventStore, cid: str, agent: str) -> dict | None:
    e = proj.latest(store, cid, EventType.FINDING_CREATED, agent=agent)
    return e.payload["finding"] if e else None


def replay(store: EventStore, data: SyntheticData, cid: str) -> ReplayResult:
    routed = proj.latest(store, cid, EventType.ROUTING_DECIDED)
    pol, dmg = _finding(store, cid, "policy_agent"), _finding(store, cid, "damage_agent")
    if routed is None or pol is None:
        return ReplayResult(claim_id=cid, replayable=False, all_match=False, checks=[],
                            note="Claim has not reached a routing decision yet")
    th, authority = load_config("thresholds"), load_config("authority")
    logged_versions = routed.provenance.config_versions
    changed = [n for n, cfg in (("thresholds", th), ("authority", authority))
               if n in logged_versions and logged_versions[n] != cfg.sha256[:12]]

    estimate = proj.latest_estimate(store, cid)
    codes = [l.code for l in (estimate.lines if estimate else [])]
    cov = coverage_rules.resolve(PolicyFinding.model_validate(pol), (dmg or {}).get("facts", {}), codes,
                                 non_adverse_line_clauses=set(th.data["non_adverse_line_clauses"]))
    logged_cov = proj.latest(store, cid, EventType.COVERAGE_RESOLVED).payload
    checks = [ReplayCheck(item="coverage", logged=logged_cov["status"], replayed=cov.decision.status,
                          match=logged_cov["status"] == cov.decision.status)]

    payout = None
    logged_pay = proj.latest(store, cid, EventType.PAYOUT_CALCULATED).payload.get("recommendation")
    if estimate:
        customer = data.customers[proj.notification(store, cid)["customer_id"]]
        excluded = dict(cov.excluded_lines)
        if cov.decision.status == "not_covered":
            excluded = {l.code: excluded.get(l.code, "NOT_COVERED") for l in estimate.lines}
        res = calculate_payout(estimate.lines, policy=data.policy_book.policy(customer.policy_id),
                               book=data.policy_book, prices=data.prices, tolerance=th.data["price_tolerance"],
                               excluded_codes=excluded)
        payout = res.recommendation.payout
        checks.append(ReplayCheck(item="payout", logged=logged_pay["payout"] if logged_pay else None, replayed=payout,
                                  match=bool(logged_pay) and abs(logged_pay["payout"] - payout) < 0.005))

    joined = proj.latest(store, cid, EventType.RISK_SCORED, stage="join").payload
    damage = DamageFinding.model_validate(dmg) if dmg else None
    rounds = sum(1 for e in store.events(cid, {EventType.FNOL_INFO_REQUESTED}) if e.seq < routed.seq)
    pay_warn = proj.latest(store, cid, EventType.PAYOUT_CALCULATED).payload.get("warnings", [])
    failed = [r.split(":", 1)[1] for r in routed.payload["reasons"] if r.startswith("ASSESSMENT_FAILED:")]
    decision = routing_rules.decide(
        coverage_status=cov.decision.status, coverage_reasons=cov.reasons,
        consistency=damage.consistency if damage else None, checks=damage.checks if damage else [],
        risk_score=joined["score"], hard_flags=joined["hard_flags"], payout=payout,
        critical_warnings=[w["code"] for w in pay_warn if w["severity"] == "critical"], failed_agents=failed,
        info_rounds_used=rounds, thresholds=th.data, authority=authority.data,
    )
    checks.append(ReplayCheck(item="route", logged=routed.payload["route"], replayed=decision.route,
                              match=routed.payload["route"] == decision.route))
    return ReplayResult(claim_id=cid, replayable=True, all_match=all(c.match for c in checks), checks=checks,
                        config_changed=changed,
                        note="Config changed since the decision; replay uses the current config" if changed else None)
