"""Join -> coverage -> payout -> routing -> (STP settle | human review | SIU | ask customer) (README 9).

Everything here is plain code except the customer letter (Sonnet, from the decision record only).
Every step writes rule.evaluated / decision events, so the outcome can be replayed from the claim file.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, Field, model_validator

from app.agents import conversation, letters, reviewer_brief
from app.graph.deps import Deps
from app.graph.emit import claude_provenance, emit_error, emit_rule
from app.graph.fnol import _customer, _language, _send
from app.models.assessment import ConsistencyCheck, DamageFinding, PolicyFinding, RiskFinding
from app.models.events import Actor, EventType, NewEvent
from app.models.state import ClaimGraphState
from app.report.builder import build_report
from app.rules import coverage as coverage_rules
from app.rules import routing as routing_rules
from app.rules.payout import calculate_payout
from app.settings import load_config
from app.store import projections as proj

SYSTEM = Actor(kind="system", id="decision_graph")
MISMATCH_CHECKS = ("room_matches_claim", "damage_type_fits_peril", "photo_supports_story")


class ReviewDecision(BaseModel):
    """What a human reviewer submits (README 9.5). Override requires a reason."""

    action: str = Field(pattern="^(approve|override|request_info|escalate_siu)$")
    reviewer_id: str
    reviewer_role: str
    reason: str | None = None
    payout_override: float | None = None
    info_needed: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "ReviewDecision":
        if self.action in ("override", "escalate_siu") and not (self.reason and self.reason.strip()):
            raise ValueError(f"A reason is mandatory for {self.action}")
        if self.action == "override" and self.payout_override is None:
            raise ValueError("override needs payout_override")
        if self.action == "request_info" and not self.info_needed:
            raise ValueError("request_info needs at least one item in info_needed")
        return self


def _latest_finding(deps: Deps, cid: str, agent: str) -> dict | None:
    e = proj.latest(deps.store, cid, EventType.FINDING_CREATED, agent=agent)
    return e.payload["finding"] if e else None


def add_decision(g: StateGraph, deps: Deps) -> None:
    store = deps.store
    th = deps.thresholds.data
    authority = load_config("authority")

    def resolve_coverage(state: ClaimGraphState) -> dict:
        cid = state.claim_id
        pol = _latest_finding(deps, cid, "policy_agent")
        dmg = _latest_finding(deps, cid, "damage_agent")
        estimate = proj.latest_estimate(store, cid)
        codes = [l.code for l in (estimate.lines if estimate else [])]
        if pol is None:
            payload = {"status": "unresolved", "reasons": ["POLICY_FINDING_MISSING"], "excluded_lines": {},
                       "adverse": False, "clauses": []}
        else:
            res = coverage_rules.resolve(PolicyFinding.model_validate(pol), (dmg or {}).get("facts", {}), codes,
                                         non_adverse_line_clauses=set(th["non_adverse_line_clauses"]))
            payload = {"status": res.decision.status, "reasons": res.reasons, "excluded_lines": res.excluded_lines,
                       "adverse": res.adverse, "clauses": [c.model_dump() for c in res.decision.clauses]}
        store.append(cid, NewEvent(type=EventType.COVERAGE_RESOLVED, actor=Actor(kind="rule", id=coverage_rules.RULE_ID),
                                   payload=payload,
                                   provenance={"rule_id": coverage_rules.RULE_ID,
                                               "rule_source": f"policy:{(pol or {}).get('policy_id')}",
                                               "config_versions": deps.config_versions("thresholds")}))
        return {}

    def calculate(state: ClaimGraphState) -> dict:
        cid = state.claim_id
        estimate = proj.latest_estimate(store, cid)
        cov = proj.latest(store, cid, EventType.COVERAGE_RESOLVED).payload
        if estimate is None:
            store.append(cid, NewEvent(type=EventType.PAYOUT_CALCULATED, actor=Actor(kind="rule", id="PAY-CALC-01"),
                                       payload={"recommendation": None, "warnings": [
                                           {"code": "NO_ESTIMATE", "severity": "critical", "message": "No repair estimate received"}]}))
            return {}
        customer = _customer(deps, cid)
        excluded = dict(cov["excluded_lines"])
        if cov["status"] == "not_covered":
            excluded = {l.code: excluded.get(l.code, "NOT_COVERED") for l in estimate.lines}
        res = calculate_payout(estimate.lines, policy=deps.data.policy_book.policy(customer.policy_id),
                               book=deps.data.policy_book, prices=deps.data.prices,
                               tolerance=th["price_tolerance"], excluded_codes=excluded)
        for ev in res.evaluations:
            emit_rule(store, cid, rule_id=ev.rule_id, rule_source=ev.rule_source, inputs={**ev.inputs, "line": ev.line_code},
                      output=ev.output, config_versions=deps.config_versions("thresholds"))
        dep_lines = [l.model_dump() for l in res.recommendation.lines if l.depreciation > 0]
        if dep_lines:
            store.append(cid, NewEvent(type=EventType.DEPRECIATION_CALCULATED, actor=Actor(kind="rule", id="PAY-DEPR-01"),
                                       payload={"lines": dep_lines},
                                       provenance={"rule_id": "PAY-DEPR-01", "rule_source": "policy:C-9.1"}))
        store.append(cid, NewEvent(type=EventType.PAYOUT_CALCULATED, actor=Actor(kind="rule", id="PAY-CALC-01"),
                                   payload={"recommendation": res.recommendation.model_dump(),
                                            "warnings": [w.model_dump() for w in res.warnings]},
                                   provenance={"rule_id": "PAY-CALC-01", "rule_source": "policy:C-9.1,C-9.2",
                                               "config_versions": deps.config_versions("thresholds")}))
        return {}

    def route_claim(state: ClaimGraphState) -> dict:
        cid = state.claim_id
        cov = proj.latest(store, cid, EventType.COVERAGE_RESOLVED).payload
        pay = proj.latest(store, cid, EventType.PAYOUT_CALCULATED).payload
        dmg = _latest_finding(deps, cid, "damage_agent")
        rsk = _latest_finding(deps, cid, "risk_agent")
        damage = DamageFinding.model_validate(dmg) if dmg else None
        risk = RiskFinding.model_validate(rsk) if rsk else None
        failed = [r.split(":", 1)[1] for r in state.route_reasons if r.startswith("ASSESSMENT_FAILED:")]

        # Final risk = Risk agent score + cross-agent signal from the Damage agent (photos contradict claim)
        weights = deps.risk_weights.data["weights"]
        # Only photos that contradict the claim are a risk signal; photos without damage are missing evidence.
        mismatch = ([c.check for c in damage.checks if c.check in MISMATCH_CHECKS and c.result == "fail"]
                    if damage and damage.consistency == "inconsistent" else [])
        base = risk.score if risk else None
        added = weights["image_claim_mismatch"] if mismatch else 0.0
        final = None if base is None else round(min(1.0, base + added), 4)
        hard_flags = risk.hard_flags if risk else []
        store.append(cid, NewEvent(type=EventType.RISK_SCORED, actor=Actor(kind="rule", id="RISK-JOIN-01"),
                                   payload={"stage": "join", "base_score": base, "score": final, "hard_flags": hard_flags,
                                            "added_signals": [{"signal": "image_claim_mismatch", "contribution": added,
                                                               "checks": mismatch}] if added else []},
                                   provenance={"rule_id": "RISK-JOIN-01", "rule_source": "config:risk_weights.yaml",
                                               "config_versions": deps.config_versions("risk_weights")}))

        rec = pay.get("recommendation")
        critical = [w["code"] for w in pay.get("warnings", []) if w["severity"] == "critical"]
        decision = routing_rules.decide(
            coverage_status=cov["status"], coverage_reasons=cov["reasons"],
            consistency=damage.consistency if damage else None,
            checks=damage.checks if damage else [], risk_score=final, hard_flags=hard_flags,
            payout=rec["payout"] if rec else None, critical_warnings=critical, failed_agents=failed,
            info_rounds_used=state.info_request_rounds, thresholds=th, authority=authority.data,
        )
        store.append(cid, NewEvent(type=EventType.ROUTING_DECIDED, actor=Actor(kind="rule", id=routing_rules.RULE_ID),
                                   payload=decision.model_dump(),
                                   provenance={"rule_id": routing_rules.RULE_ID, "rule_source": "config:thresholds.yaml,authority.yaml",
                                               "config_versions": {**deps.config_versions("thresholds", "risk_weights"),
                                                                   "authority": authority.sha256[:12]}}))
        return {"stage": "routing", "route_reasons": decision.reasons, "pending_missing": decision.info_needed}

    def after_route(state: ClaimGraphState) -> str:
        route = proj.latest(store, state.claim_id, EventType.ROUTING_DECIDED).payload["route"]
        return {"stp": "settle", "info_request": "request_info"}.get(route, "request_review")

    def request_review(state: ClaimGraphState) -> dict:
        cid = state.claim_id
        routing = proj.latest(store, cid, EventType.ROUTING_DECIDED).payload
        queue = "siu" if routing["route"] == "siu" else "claims"
        store.append(cid, NewEvent(type=EventType.HUMAN_REVIEW_REQUESTED, actor=SYSTEM,
                                   payload={"stage": "decision", "queue": queue, "reasons": routing["reasons"],
                                            "approver": routing["approver"]}))
        try:
            call = reviewer_brief.write_brief(deps.claude, _review_record(cid, routing))
            store.append(cid, NewEvent(type=EventType.REVIEW_BRIEF, actor=Actor(kind="agent", id="reviewer_brief"),
                                       payload={"queue": queue, **call.output.model_dump()},
                                       provenance=claude_provenance(call, reviewer_brief.PROMPT_VERSION)))
        except Exception as exc:  # the reviewer still has the full file; the brief is a convenience
            emit_error(store, cid, node="decision.reviewer_brief", error=exc)
        customer = _customer(deps, cid)
        lang = _language(deps, cid)
        _send(deps, cid, conversation.template("handover", lang, name=customer.name.split()[0]), lang, kind="handover")
        return {"stage": "review", "pending_interrupt": "awaiting_human_review"}

    def _review_record(cid: str, routing: dict) -> dict:
        """Structured decision record for the reviewer brief: findings and reason codes, no agent prose."""
        cov = proj.latest(store, cid, EventType.COVERAGE_RESOLVED)
        pay = proj.latest(store, cid, EventType.PAYOUT_CALCULATED)
        joined = proj.latest(store, cid, EventType.RISK_SCORED, stage="join")
        dmg, rsk = _latest_finding(deps, cid, "damage_agent"), _latest_finding(deps, cid, "risk_agent")
        book = deps.data.policy_book
        rec = pay.payload.get("recommendation") if pay else None
        return {
            "route": routing["route"], "reason_codes": routing["reasons"], "required_approver": routing["approver"],
            "customer_messages": [t.text for t in proj.customer_texts(store, cid)],
            "coverage": cov.payload["status"] if cov else None,
            "clauses_not_in_customers_favour": [
                {"clause": c["clause_id"], "title": book.clauses[c["clause_id"]].title["en"], "status": c["status"],
                 "facts": c["facts_used"]}
                for c in (cov.payload["clauses"] if cov else []) if c["status"] in ("excluded", "unresolved")
                and c["clause_id"] in book.clauses],
            "photo_checks_not_passed": [{k: c[k] for k in ("check", "result", "detail")}
                                        for c in (dmg or {}).get("checks", []) if c["result"] in ("fail", "unresolved")],
            "photo_observations": {ev: {"room": o["room_type"], "damage": o["damage_types"], "quality": o["image_quality"]}
                                   for ev, o in (dmg or {}).get("images", {}).items()},
            "risk": {"final_score": joined.payload["score"] if joined else None,
                     "hard_flags": joined.payload["hard_flags"] if joined else [],
                     "signals": [{k: s[k] for k in ("signal", "contribution", "detail")}
                                 for s in (rsk or {}).get("signals", []) if s["contribution"] > 0]},
            "payout": None if not rec else {"proposed": rec["payout"], "deductible": rec["deductible"],
                                            "lines": [{k: l[k] for k in ("description", "claimed", "covered", "reason")} for l in rec["lines"]]},
        }

    def human_review(state: ClaimGraphState) -> dict:
        # Separate node: on resume LangGraph re-runs the interrupted node, so nothing is emitted before interrupt().
        cid = state.claim_id
        routing = proj.latest(store, cid, EventType.ROUTING_DECIDED).payload
        queue = "siu" if routing["route"] == "siu" else "claims"
        raw = interrupt({"reason": "awaiting_human_review", "claim_id": cid, "queue": queue})
        decision = ReviewDecision.model_validate(raw)
        store.append(cid, NewEvent(
            type=EventType.HUMAN_DECISION,
            actor=Actor(kind="human", id=decision.reviewer_id, role=decision.reviewer_role),
            payload={**decision.model_dump(), "queue": queue, "proposed_route": routing["route"],
                     "proposed_reasons": routing["reasons"]},
        ))
        update: dict[str, Any] = {"stage": "review", "pending_interrupt": None}
        if decision.action == "request_info":
            update["pending_missing"] = [f"ask:{t}" for t in decision.info_needed]
        return update

    def after_review(state: ClaimGraphState) -> str:
        action = proj.latest(store, state.claim_id, EventType.HUMAN_DECISION).payload["action"]
        return {"approve": "settle", "override": "settle", "request_info": "request_info"}.get(action, "escalated")

    def escalated(state: ClaimGraphState) -> dict:
        store.append(state.claim_id, NewEvent(type=EventType.HUMAN_REVIEW_REQUESTED, actor=SYSTEM,
                                              payload={"stage": "decision", "queue": "siu", "reasons": ["ESCALATED_BY_REVIEWER"],
                                                       "approver": "special_investigations"}))
        return {"stage": "review"}

    def settle(state: ClaimGraphState) -> dict:
        cid = state.claim_id
        routing = proj.latest(store, cid, EventType.ROUTING_DECIDED).payload
        human = proj.latest(store, cid, EventType.HUMAN_DECISION)
        pay = proj.latest(store, cid, EventType.PAYOUT_CALCULATED).payload
        cov = proj.latest(store, cid, EventType.COVERAGE_RESOLVED).payload
        rec = pay.get("recommendation") or {"lines": [], "payout": 0.0, "deductible": 0.0, "eligible": 0.0}
        amount = human.payload["payout_override"] if human and human.payload["action"] == "override" else rec["payout"]

        payment_ref = None
        if amount and amount > 0:
            payment_ref = f"PAY-{uuid.uuid4().hex[:10].upper()}"
            customer = _customer(deps, cid)
            store.append(cid, NewEvent(type=EventType.PAYMENT_INSTRUCTED, actor=SYSTEM,
                                       payload={"payment_ref": payment_ref, "amount": amount, "currency": "EUR",
                                                "beneficiary": customer.name, "mock": True,
                                                "authorised_by": human.payload["reviewer_id"] if human else "auto_stp"}))

        lang = _language(deps, cid)
        book = deps.data.policy_book
        record = {
            "claim_ref": cid, "customer_first_name": _customer(deps, cid).name.split()[0],
            "outcome": "paid" if amount and amount > 0 else "not_paid", "coverage": cov["status"],
            "decided_by": "automatic (all straight-through conditions met)" if not human else
                          f"claims handler review ({human.payload['action']})",
            "lines": [{"item": l["description"], "claimed": l["claimed"], "after_market_price_check": l["validated"],
                       "depreciation": l["depreciation"], "covered": l["covered"], "reason": l.get("reason")}
                      for l in rec["lines"]],
            "excluded_clauses": {code: book.clauses[cl].title[lang] for code, cl in cov["excluded_lines"].items()
                                 if cl in book.clauses},
            "claim_level_reasons": [book.clauses[r.split(":")[1]].title[lang] for r in cov["reasons"]
                                    if r.startswith("EXCLUDED:") and r.split(":")[1] in book.clauses],
            "total_claimed": round(sum(l["claimed"] for l in rec["lines"]), 2),
            "total_covered": rec["eligible"], "caps_applied": rec.get("caps_applied", []),
            "deductible": rec["deductible"], "payout": amount, "payment_ref": payment_ref,
        }
        try:
            letter, call, warnings = letters.write_letter(deps.claude, language=lang, record=record)
            prov = claude_provenance(call, letters.PROMPT_VERSION) if call else None
            store.append(cid, NewEvent(type=EventType.LETTER_GENERATED,
                                       actor=Actor(kind="agent" if call else "rule", id="letter_writer" if call else "letter_template"),
                                       payload={"language": lang, "letter": letter.letter, "record": record,
                                                "amount_check_warnings": warnings},
                                       **({"provenance": prov} if prov else {})))
            _send(deps, cid, letter.chat_message, lang, kind="decision", provenance=prov)
        except Exception as exc:
            emit_error(store, cid, node="decision.letter", error=exc)
            _send(deps, cid, f"{cid}: EUR {amount:.2f}" + (f" ({payment_ref})" if payment_ref else ""), lang,
                  kind="decision_fallback")

        report = build_report(store, deps.data, cid)
        digest = deps.blobs.put_json(report.model_dump(mode="json"))
        store.append(cid, NewEvent(type=EventType.REPORT_GENERATED, actor=SYSTEM,
                                   payload={"report_blob": digest, "route": routing["route"], "payout": amount},
                                   provenance={"raw_response_blob": digest}))
        store.append(cid, NewEvent(type=EventType.CLAIM_CLOSED, actor=SYSTEM,
                                   payload={"closed_at": datetime.now(UTC).isoformat(), "payout": amount}))
        return {"stage": "closed"}

    g.add_node("resolve_coverage", resolve_coverage)
    g.add_node("calculate_payout", calculate)
    g.add_node("route_claim", route_claim)
    g.add_node("request_review", request_review)
    g.add_node("human_review", human_review)
    g.add_node("escalated", escalated)
    g.add_node("settle", settle)
    g.add_edge("resolve_coverage", "calculate_payout")
    g.add_edge("calculate_payout", "route_claim")
    g.add_conditional_edges("route_claim", after_route, ["settle", "request_info", "request_review"])
    g.add_edge("request_review", "human_review")
    g.add_conditional_edges("human_review", after_review, ["settle", "request_info", "escalated"])
    g.add_edge("escalated", END)
    g.add_edge("settle", END)
