"""Scripted stand-ins for Claude and Jev, for deterministic graph tests."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from app.jev.client import JevAnswer, JevCall
from app.llm.claude import ModelCall
from app.models.fnol import FnolExtraction, InfoRequestMessage


class StubClaude:
    def __init__(self, blobs) -> None:
        self.blobs = blobs
        self.queue: dict[type, deque] = defaultdict(deque)
        self.calls: list[dict[str, Any]] = []
        self.fail_next = False

    def push(self, output: Any) -> None:
        self.queue[type(output)].append(output)

    def structured(self, *, system, content, output_model, prompt_version, effort=None, max_tokens=16000):
        self.calls.append({"output_model": output_model, "content": content, "prompt_version": prompt_version})
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("simulated API outage")
        if output_model is InfoRequestMessage and not self.queue[output_model]:
            out = InfoRequestMessage(text="Kun je nog een paar dingen laten weten?")
        else:
            out = self.queue[output_model].popleft()
        return ModelCall(output=out, model="stub-sonnet", stop_reason="end_turn", usage={},
                         raw_request_blob=self.blobs.put_json({"stub": prompt_version}),
                         raw_response_blob=self.blobs.put_json(out.model_dump(mode="json")))


class StubJev:
    def __init__(self, blobs, peril: str = "water_burst_or_leak", peril_conf: float = 0.9,
                 only_informing: float = 0.05) -> None:
        self.blobs = blobs
        self.peril, self.peril_conf, self.only_informing = peril, peril_conf, only_informing
        self.calls: list[dict] = []

    def ask(self, state, questions, *, question_set_version):
        self.calls.append({"state": state, "questions": questions})
        answers = {
            "peril": JevAnswer(type="choice", choice=self.peril, confidence=self.peril_conf,
                               probabilities={self.peril: self.peril_conf}),
            "only_informing": JevAnswer(type="noul", noul=self.only_informing),
        }
        return JevCall(answers={k: answers[k] for k in questions}, model="jev-stub",
                       question_set_version=question_set_version,
                       raw_request_blob=self.blobs.put_json({"stub": "jev"}),
                       raw_response_blob=self.blobs.put_json({"answers": list(questions)}))


def extraction(evidence_id: str = "EV-0001", **overrides: Any) -> FnolExtraction:
    """A water-claim extraction whose quotes match WATER_TEXT."""
    base = dict(
        language="nl",
        loss_date={"value": "2026-10-16", "quote": "Eergisteren", "evidence_id": evidence_id},
        loss_time=None,
        what_happened={"value": "washing machine hose burst", "quote": "toevoerslang van de wasmachine op zolder geknapt", "evidence_id": evidence_id},
        source={"value": "washing machine inlet hose", "quote": "toevoerslang van de wasmachine", "evidence_id": evidence_id},
        location={"value": "bedroom ceiling", "quote": "plafond van de slaapkamer", "evidence_id": evidence_id},
        loss_address_differs=None,
        source_stopped={"value": True, "quote": "Slang is al vervangen", "evidence_id": evidence_id},
        emergency_measures=None, third_party_involved=None, police_report_ref=None, fire_brigade_report_ref=None,
        theft_reported=None, affected_items=[], item_ages=[], extraction_confidence=0.9,
        reasoning="clear", summary="Hose burst upstairs, bedroom ceiling damaged.",
    )
    base.update(overrides)
    return FnolExtraction.model_validate(base)


WATER_TEXT = ("Eergisteren is de toevoerslang van de wasmachine op zolder geknapt. Voordat ik het doorhad was het "
              "water door het plafond van de slaapkamer eronder gelopen. Slang is al vervangen.")
