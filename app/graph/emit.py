"""Helpers that turn model calls and rule results into claim-file events with full provenance."""

from __future__ import annotations

from typing import Any

from app.jev.client import JevCall
from app.llm.claude import ModelCall
from app.models.events import Actor, EventType, NewEvent, Provenance
from app.store.event_store import EventStore


def claude_provenance(call: ModelCall, prompt_version: str) -> Provenance:
    return Provenance(model=call.model, prompt_or_question_set_version=prompt_version,
                      raw_request_blob=call.raw_request_blob, raw_response_blob=call.raw_response_blob)


def emit_jev(store: EventStore, claim_id: str, call: JevCall, questions: dict[str, dict], *,
             actor: Actor, evidence_refs: list[str]) -> None:
    """One `jev.answered` event per question: question, answer, probabilities, confidence, evidence."""
    for qid, answer in call.answers.items():
        store.append(claim_id, NewEvent(
            type=EventType.JEV_ANSWERED, actor=actor, evidence_refs=evidence_refs,
            payload={
                "question_set": call.question_set_version,
                "question_id": qid,
                "question": questions[qid],
                "answer": answer.model_dump(exclude_none=True),
                "measured_confidence": round(answer.measured_confidence, 4),
            },
            provenance=Provenance(model=call.model, prompt_or_question_set_version=call.question_set_version,
                                  raw_request_blob=call.raw_request_blob, raw_response_blob=call.raw_response_blob),
        ))


def emit_rule(store: EventStore, claim_id: str, *, rule_id: str, rule_source: str, inputs: dict[str, Any],
              output: dict[str, Any], config_versions: dict[str, str] | None = None,
              evidence_refs: list[str] | None = None) -> None:
    store.append(claim_id, NewEvent(
        type=EventType.RULE_EVALUATED, actor=Actor(kind="rule", id=rule_id), evidence_refs=evidence_refs or [],
        payload={"rule_id": rule_id, "inputs": inputs, "output": output},
        provenance=Provenance(rule_id=rule_id, rule_source=rule_source, config_versions=config_versions or {}),
    ))


def emit_error(store: EventStore, claim_id: str, *, node: str, error: BaseException) -> None:
    store.append(claim_id, NewEvent(
        type=EventType.SYSTEM_ERROR, actor=Actor(kind="system", id=node),
        payload={"node": node, "error_type": type(error).__name__, "message": str(error)[:2000]},
    ))
