"""Parallel assessment (README section 8): Damage, Policy and Risk run in parallel after registration and
the join waits for all three. Agents never call each other; each reads its own view, writes findings."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from langgraph.graph import StateGraph

from app.agents import damage, policy, risk
from app.graph.deps import Deps
from app.graph.emit import claude_provenance, emit_error, emit_jev, emit_rule
from app.graph.fnol import _extraction
from app.jev.question_sets import FNOL_V1
from app.models.events import Actor, EventType, NewEvent, Provenance
from app.models.state import ClaimGraphState
from app.store import projections as proj

AGENTS = (damage.AGENT, policy.AGENT, risk.AGENT)


def _peril(deps: Deps, cid: str) -> str | None:
    e = proj.latest(deps.store, cid, EventType.FNOL_COMPLETENESS_EVALUATED)
    return e.payload["peril"] if e else None


def _loss_date(deps: Deps, cid: str) -> date | None:
    e = proj.latest(deps.store, cid, EventType.CLAIM_REGISTERED)
    return date.fromisoformat(e.payload["loss_date"]) if e and e.payload.get("loss_date") else None


def _finding_event(deps: Deps, cid: str, output: Any, refs: list[str], prov: Any = None) -> None:
    deps.store.append(cid, NewEvent(type=EventType.FINDING_CREATED, actor=Actor(kind="agent", id=output.agent),
                                    evidence_refs=refs, payload=output.model_dump(mode="json"),
                                    **({"provenance": prov} if prov else {})))


def jev_provenance(call: Any, config_versions: dict[str, str]) -> Provenance | None:
    """Findings built from a Jev battery point at that call's raw request/response."""
    if call is None:
        return None
    return Provenance(model=call.model, prompt_or_question_set_version=call.question_set_version,
                      raw_request_blob=call.raw_request_blob, raw_response_blob=call.raw_response_blob,
                      config_versions=config_versions)


def known_image_hashes(deps: Deps) -> list[dict[str, str]]:
    known = risk.history_hashes(deps.data.history, deps.data.root)
    for other in deps.store.claim_ids():
        owner = proj.notification(deps.store, other)["customer_id"]
        for e in deps.store.events(other, {EventType.EVIDENCE_NORMALIZED}):
            if e.payload.get("phash"):
                known.append({"claim_id": other, "customer_ref": owner, "phash": e.payload["phash"]})
    return known


def add_assessment(g: StateGraph, deps: Deps, *, after_join: str) -> None:
    store = deps.store
    tolerance = deps.thresholds.data["price_tolerance"]

    def start_assessment(state: ClaimGraphState) -> dict:
        return {"stage": "assessment"}

    def assess_damage(state: ClaimGraphState) -> dict:
        cid = state.claim_id
        x = _extraction(deps, cid)
        try:
            res = damage.assess(claude=deps.claude, jev=deps.jev, blobs=deps.blobs, claim_id=cid,
                                texts=proj.customer_texts(store, cid), images=proj.images(store, cid),
                                estimate=proj.latest_estimate(store, cid), peril=_peril(deps, cid),
                                location=x.location.value if x and x.location else None, prices=deps.data.prices,
                                tolerance=tolerance, cfg=deps.consistency.data)
        except Exception as exc:
            emit_error(store, cid, node="assess.damage", error=exc)
            return {}
        actor = Actor(kind="agent", id=damage.AGENT)
        for ev, call in res.vision_calls.items():
            store.append(cid, NewEvent(type=EventType.VISION_EXTRACTED, actor=actor, evidence_refs=[ev],
                                       payload={"evidence_id": ev, "observation": call.output.model_dump(mode="json")},
                                       provenance=claude_provenance(call, "vision_extract_v1")))
        refs = [r.evidence_id for r in res.output.evidence]
        if res.jev_call:
            emit_jev(store, cid, res.jev_call, res.questions, actor=actor, evidence_refs=refs)
        emit_rule(store, cid, rule_id="DMG-CONSIST-01", rule_source="config:consistency.yaml",
                  inputs={"checks": [c.model_dump() for c in res.output.finding.checks]},
                  output={"consistency": res.output.finding.consistency},
                  config_versions=deps.config_versions("consistency"), evidence_refs=refs)
        _finding_event(deps, cid, res.output, refs, jev_provenance(res.jev_call, deps.config_versions("consistency")))
        return {}

    def assess_policy(state: ClaimGraphState) -> dict:
        cid = state.claim_id
        customer = deps.data.customers[proj.notification(store, cid)["customer_id"]]
        try:
            res = policy.assess(claude=deps.claude, jev=deps.jev, claim_id=cid, book=deps.data.policy_book,
                                policy=deps.data.policy_book.policy(customer.policy_id), prices=deps.data.prices,
                                peril=_peril(deps, cid), extraction=_extraction(deps, cid),
                                estimate=proj.latest_estimate(store, cid), loss_date=_loss_date(deps, cid),
                                texts=proj.customer_texts(store, cid), storm_days=set(deps.storm_days.data.get("NL", [])),
                                peril_clauses=deps.peril_clauses.data,
                                storm_window_days=deps.storm_days.data.get("demo_recent_storm_window_days", 0))
        except Exception as exc:
            emit_error(store, cid, node="assess.policy", error=exc)
            return {}
        actor = Actor(kind="agent", id=policy.AGENT)
        texts = [t.evidence_id for t in proj.customer_texts(store, cid)]
        emit_jev(store, cid, res.jev_call, res.questions, actor=actor, evidence_refs=texts)
        versions = deps.config_versions("peril_clauses", "storm_days")
        for c in res.output.finding.clauses:
            emit_rule(store, cid, rule_id=f"POL-{c.clause_id}", rule_source=f"policy:{res.output.finding.policy_id}#{c.clause_id}",
                      inputs={"peril": res.output.finding.peril, "selected_by": c.selected_by},
                      output={"status": c.status, "scope": c.scope, "line_codes": c.line_codes, "reason": c.reason},
                      config_versions=versions)
        _finding_event(deps, cid, res.output, [c.clause_id for c in res.output.finding.clauses],
                       claude_provenance(res.selection_call, policy.PROMPT_VERSION))
        return {}

    def assess_risk(state: ClaimGraphState) -> dict:
        cid = state.claim_id
        customer = deps.data.customers[proj.notification(store, cid)["customer_id"]]
        texts = proj.customer_texts(store, cid)
        first = texts[0] if texts else None
        reported = datetime.fromisoformat(first.sent_at) if first and first.sent_at else (first.received_at if first else None)
        try:
            res = risk.assess(jev=deps.jev, blobs=deps.blobs, claim_id=cid, customer=customer,
                              policy=deps.data.policy_book.policy(customer.policy_id), loss_date=_loss_date(deps, cid),
                              reported_at=reported, texts=texts, images=proj.images(store, cid),
                              estimate=proj.latest_estimate(store, cid), prices=deps.data.prices, tolerance=tolerance,
                              past_claims=deps.data.history, known_hashes=known_image_hashes(deps),
                              weights_cfg=deps.risk_weights.data, thresholds=deps.thresholds.data,
                              duplicate_threshold=deps.data.history_meta["duplicate_threshold_hamming"])
        except Exception as exc:
            emit_error(store, cid, node="assess.risk", error=exc)
            return {}
        actor = Actor(kind="agent", id=risk.AGENT)
        refs = [r.evidence_id for r in res.output.evidence]
        emit_jev(store, cid, res.jev_call, res.questions, actor=actor, evidence_refs=refs)
        f = res.output.finding
        store.append(cid, NewEvent(type=EventType.RISK_SCORED, actor=actor, evidence_refs=refs,
                                   payload={"score": f.score, "band": f.band, "hard_flags": f.hard_flags,
                                            "signals": [s.model_dump() for s in f.signals]},
                                   provenance={"rule_id": "RISK-SCORE-01", "rule_source": "config:risk_weights.yaml",
                                               "config_versions": deps.config_versions("risk_weights", "thresholds")}))
        _finding_event(deps, cid, res.output, refs,
                       jev_provenance(res.jev_call, deps.config_versions("risk_weights", "thresholds")))
        return {}

    def join(state: ClaimGraphState) -> dict:
        cid = state.claim_id
        done = {e.payload.get("agent") for e in store.events(cid, {EventType.FINDING_CREATED})}
        missing = [a for a in AGENTS if a not in done]
        return {"stage": "join", "route_reasons": [f"ASSESSMENT_FAILED:{a}" for a in missing]}

    g.add_node("start_assessment", start_assessment)
    g.add_node("assess_damage", assess_damage)
    g.add_node("assess_policy", assess_policy)
    g.add_node("assess_risk", assess_risk)
    g.add_node("join", join)
    for n in ("assess_damage", "assess_policy", "assess_risk"):
        g.add_edge("start_assessment", n)
        g.add_edge(n, "join")
    g.add_edge("join", after_join)
