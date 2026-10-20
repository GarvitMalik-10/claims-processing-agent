"""FNOL subgraph (README section 7).

extract -> classify -> [incident only?] -> completeness -> [missing -> ask -> wait(interrupt) -> extract]
                                                        -> match policy & register -> (assessment, M3)
Deviation from the first diagram, by design: the claim-vs-incident check runs before completeness,
so a customer who is only reporting something is never chased for missing information.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents import conversation, fnol_extract
from app.graph.deps import Deps
from app.graph.emit import claude_provenance, emit_error, emit_jev, emit_rule
from app.jev.question_sets import FNOL_V1, fnol_questions
from app.models.events import Actor, EventType, NewEvent
from app.models.fnol import FnolExtraction
from app.models.state import ClaimGraphState
from app.rules import completeness as completeness_rules
from app.rules import policy_match as policy_rules
from app.store import projections as proj

SYSTEM = Actor(kind="system", id="fnol_graph")
EXTRACTOR = Actor(kind="agent", id=fnol_extract.AGENT)
PERIL_AGENT = Actor(kind="agent", id="fnol_peril_classifier")
CONVERSATION = Actor(kind="agent", id="conversation")


def _customer(deps: Deps, claim_id: str):
    return deps.data.customers[proj.notification(deps.store, claim_id)["customer_id"]]


def _extraction(deps: Deps, claim_id: str) -> FnolExtraction | None:
    e = proj.latest(deps.store, claim_id, EventType.FINDING_CREATED, agent=fnol_extract.AGENT)
    return FnolExtraction.model_validate(e.payload["finding"]) if e else None


def _language(deps: Deps, claim_id: str) -> str:
    x = _extraction(deps, claim_id)
    return x.language if x else _customer(deps, claim_id).language


def _send(deps: Deps, claim_id: str, text: str, language: str, *, kind: str, provenance=None) -> None:
    deps.store.append(claim_id, NewEvent(type=EventType.MESSAGE_SENT, actor=CONVERSATION,
                                         payload={"channel": "chat", "kind": kind, "language": language, "text": text},
                                         **({"provenance": provenance} if provenance is not None else {})))


def build_fnol_graph(deps: Deps, checkpointer: Any):
    """FNOL only (ends at registration). The full claim graph is app.graph.claim.build_claim_graph."""
    g = StateGraph(ClaimGraphState)
    add_fnol(g, deps, after_registration=END)
    return g.compile(checkpointer=checkpointer)


def add_fnol(g: StateGraph, deps: Deps, *, after_registration: str) -> None:
    store = deps.store
    th = deps.thresholds.data

    def extract(state: ClaimGraphState) -> dict:
        cid = state.claim_id
        texts = proj.customer_texts(store, cid)
        try:
            res = fnol_extract.extract(deps.claude, cid, texts, proj.latest_estimate(store, cid))
        except Exception as exc:  # model/API failure -> logged, then a human takes over
            emit_error(store, cid, node="fnol.extract", error=exc)
            return {"route_reasons": ["SYSTEM_ERROR_EXTRACTION"]}
        prov = claude_provenance(res.call, fnol_extract.PROMPT_VERSION)
        refs = [t.evidence_id for t in texts]
        store.append(cid, NewEvent(type=EventType.FINDING_CREATED, actor=EXTRACTOR, evidence_refs=refs,
                                   payload={**res.output.model_dump(mode="json"),
                                            "quote_checks": [q.model_dump() for q in res.quote_checks]},
                                   provenance=prov))
        for field, value, quote, ev in fnol_extract.sourced_fields(res.extraction):
            store.append(cid, NewEvent(type=EventType.FNOL_FIELD_EXTRACTED, actor=EXTRACTOR, evidence_refs=[ev],
                                       payload={"field": field, "value": value, "quote": quote, "evidence_id": ev},
                                       provenance=prov))
        return {"route_reasons": []}

    def classify(state: ClaimGraphState) -> dict:
        cid = state.claim_id
        if "SYSTEM_ERROR_EXTRACTION" in state.route_reasons:
            return {}
        texts = proj.customer_texts(store, cid)
        questions = fnol_questions()
        story = "\n\n".join(t.text or "" for t in texts)
        try:
            call = deps.jev.ask({"messages": story}, questions, question_set_version=FNOL_V1)
        except Exception as exc:
            emit_error(store, cid, node="fnol.classify", error=exc)
            return {"route_reasons": ["SYSTEM_ERROR_JEV"]}
        emit_jev(store, cid, call, questions, actor=PERIL_AGENT, evidence_refs=[t.evidence_id for t in texts])
        return {}

    def after_classify(state: ClaimGraphState) -> str:
        if state.route_reasons:
            return "handover"
        informing = proj.jev_answers(store, state.claim_id, FNOL_V1).get("only_informing")
        has_estimate = proj.latest_estimate(store, state.claim_id) is not None
        if informing and informing["answer"]["noul"] >= th["claim_vs_incident"]["incident_from"] and not has_estimate:
            return "record_incident"
        return "check_completeness"

    def check_completeness(state: ClaimGraphState) -> dict:
        cid = state.claim_id
        peril = proj.jev_answers(store, cid, FNOL_V1).get("peril")
        answer = completeness_rules.PerilAnswer(
            choice=peril["answer"]["choice"] if peril else None,
            confidence=peril["measured_confidence"] if peril else None,
        )
        result = completeness_rules.evaluate_completeness(
            extraction=_extraction(deps, cid), peril=answer, image_count=len(proj.images(store, cid)),
            estimate=proj.latest_estimate(store, cid), config=deps.completeness.data,
            config_version=deps.completeness.sha256[:12], min_choice_confidence=th["min_choice_confidence"],
            book=deps.data.policy_book, prices=deps.data.prices,
        )
        versions = deps.config_versions("completeness", "thresholds")
        store.append(cid, NewEvent(type=EventType.FNOL_COMPLETENESS_EVALUATED, actor=Actor(kind="rule", id=completeness_rules.RULE_ID),
                                   payload=result.model_dump(),
                                   provenance={"rule_id": completeness_rules.RULE_ID,
                                               "rule_source": "config:completeness.yaml", "config_versions": versions}))
        emit_rule(store, cid, rule_id=completeness_rules.RULE_ID, rule_source="config:completeness.yaml",
                  inputs={"peril": answer.choice, "peril_confidence": answer.confidence},
                  output={"complete": result.complete, "missing": result.missing}, config_versions=versions)
        return {}

    def after_completeness(state: ClaimGraphState) -> str:
        e = proj.latest(store, state.claim_id, EventType.FNOL_COMPLETENESS_EVALUATED)
        if e.payload["complete"]:
            return "match_policy"
        if state.info_request_rounds < th["missing_info"]["max_rounds"]:
            return "request_info"
        return "handover"

    def request_info(state: ClaimGraphState) -> dict:
        cid = state.claim_id
        missing = state.pending_missing or proj.latest(store, cid, EventType.FNOL_COMPLETENESS_EVALUATED).payload["missing"]
        customer = _customer(deps, cid)
        language = _language(deps, cid)
        estimate = proj.latest_estimate(store, cid)
        labels = {l.code: l.description for l in (estimate.lines if estimate else [])}
        round_no = state.info_request_rounds + 1
        store.append(cid, NewEvent(type=EventType.FNOL_INFO_REQUESTED, actor=SYSTEM,
                                   payload={"missing": missing, "round": round_no}))
        try:
            call = conversation.write_info_request(deps.claude, language=language,
                                                   customer_first_name=customer.name.split()[0],
                                                   missing=missing, item_labels=labels, round_no=round_no)
            _send(deps, cid, call.output.text, language, kind="info_request",
                  provenance=claude_provenance(call, conversation.PROMPT_VERSION))
        except Exception as exc:
            emit_error(store, cid, node="fnol.request_info", error=exc)
            hints = "; ".join(conversation.field_hint(f, labels) for f in missing)
            _send(deps, cid, hints, language, kind="info_request_fallback")
        return {"info_request_rounds": round_no, "stage": "awaiting_customer"}

    def wait_for_customer(state: ClaimGraphState) -> dict:
        cid = state.claim_id
        asked_at = proj.latest(store, cid, EventType.FNOL_INFO_REQUESTED).seq
        interrupt({"reason": "awaiting_customer_info", "claim_id": cid})
        new = [e.payload["evidence_id"] for e in store.events(cid, {EventType.EVIDENCE_RECEIVED}) if e.seq > asked_at]
        store.append(cid, NewEvent(type=EventType.FNOL_INFO_RECEIVED, actor=SYSTEM, evidence_refs=new,
                                   payload={"new_evidence": new}))
        return {"stage": "fnol", "pending_interrupt": None, "pending_missing": []}

    def match_policy(state: ClaimGraphState) -> dict:
        cid = state.claim_id
        if proj.latest(store, cid, EventType.CLAIM_REGISTERED):  # back from an info loop: already registered
            return {"stage": "assessment"}
        customer = _customer(deps, cid)
        x = _extraction(deps, cid)
        policy = next((p for p in deps.data.policy_book.policies if p.policy_id == customer.policy_id), None)
        loss_date = date.fromisoformat(x.loss_date.value) if x and x.loss_date else None
        m = policy_rules.match_policy(customer, policy, loss_date,
                                      x.loss_address_differs.value if x and x.loss_address_differs else None)
        store.append(cid, NewEvent(type=EventType.POLICY_MATCHED, actor=Actor(kind="rule", id=policy_rules.RULE_ID),
                                   payload=m.model_dump(),
                                   provenance={"rule_id": policy_rules.RULE_ID,
                                               "rule_source": f"policy:{policy_rules.CLAUSE}"}))
        if not m.matched:
            return {"route_reasons": m.reasons}
        store.append(cid, NewEvent(type=EventType.CLAIM_REGISTERED, actor=SYSTEM,
                                   payload={"claim_ref": cid, "policy_id": m.policy_id, "product": m.product,
                                            "loss_date": loss_date.isoformat() if loss_date else None}))
        _send(deps, cid, conversation.template("registered", _language(deps, cid),
                                               name=customer.name.split()[0], claim_ref=cid),
              _language(deps, cid), kind="registered")
        return {"stage": "assessment"}

    def after_match(state: ClaimGraphState) -> str:
        return "handover" if state.route_reasons else after_registration

    def record_incident(state: ClaimGraphState) -> dict:
        cid = state.claim_id
        customer = _customer(deps, cid)
        informing = proj.jev_answers(store, cid, FNOL_V1)["only_informing"]
        emit_rule(store, cid, rule_id="FNOL-INCIDENT-01", rule_source="config:thresholds.yaml#claim_vs_incident",
                  inputs={"only_informing": informing["answer"]["noul"], "estimate_received": False,
                          "incident_from": th["claim_vs_incident"]["incident_from"]},
                  output={"incident_only": True}, config_versions=deps.config_versions("thresholds"))
        store.append(cid, NewEvent(type=EventType.CLAIM_RECORDED_AS_INCIDENT, actor=SYSTEM,
                                   payload={"claim_ref": cid, "policy_id": customer.policy_id,
                                            "reason": "NO_COMPENSATION_REQUESTED"}))
        language = _language(deps, cid)
        _send(deps, cid, conversation.template("incident_recorded", language, name=customer.name.split()[0],
                                               claim_ref=cid), language, kind="incident_recorded")
        return {"stage": "incident_only"}

    def handover(state: ClaimGraphState) -> dict:
        cid = state.claim_id
        reasons = state.route_reasons or ["MISSING_INFO_AFTER_MAX_ROUNDS"]
        store.append(cid, NewEvent(type=EventType.HUMAN_REVIEW_REQUESTED, actor=SYSTEM,
                                   payload={"stage": "fnol", "reasons": reasons}))
        customer = _customer(deps, cid)
        language = _language(deps, cid)
        _send(deps, cid, conversation.template("handover", language, name=customer.name.split()[0]),
              language, kind="handover")
        return {"stage": "review", "route_reasons": reasons}

    for name, fn in [("extract", extract), ("classify", classify), ("check_completeness", check_completeness),
                     ("request_info", request_info), ("wait_for_customer", wait_for_customer),
                     ("match_policy", match_policy), ("record_incident", record_incident), ("handover", handover)]:
        g.add_node(name, fn)
    g.add_edge(START, "extract")
    g.add_edge("extract", "classify")
    g.add_conditional_edges("classify", after_classify, ["record_incident", "check_completeness", "handover"])
    g.add_conditional_edges("check_completeness", after_completeness, ["match_policy", "request_info", "handover"])
    g.add_edge("request_info", "wait_for_customer")
    g.add_edge("wait_for_customer", "extract")
    g.add_conditional_edges("match_policy", after_match, ["handover", after_registration])
    g.add_edge("record_incident", END)
    g.add_edge("handover", END)
