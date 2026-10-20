from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from app.models.common import AgentOutput, Confidence, EvidenceRef
from app.models.events import Actor, EventType, NewEvent
from app.store.views import agent_view, strip_prose


class Finding(BaseModel):
    severity: str


def make_output(**overrides):
    data = dict(
        agent="damage_agent", agent_version="1", claim_id="CLM-1", finding=Finding(severity="minor"),
        confidence=Confidence(value=0.8, source="measured", basis="jev choice severity"),
        evidence=[EvidenceRef(evidence_id="EV-0001", kind="image")],
        reasoning="long prose", summary="short prose",
    )
    data.update(overrides)
    return AgentOutput[Finding](**data)


def test_agent_output_requires_evidence():
    with pytest.raises(ValidationError):
        make_output(evidence=[])


def test_self_reported_confidence_is_not_routable():
    assert Confidence(value=0.9, source="measured", basis="x").routable
    assert Confidence(value=1.0, source="rule", basis="x").routable
    assert not Confidence(value=0.99, source="self_reported", basis="x").routable


def test_strip_prose_removes_prose_at_any_depth():
    doc = {"summary": "x", "finding": {"reasoning": "y", "items": [{"summary": "z", "code": "A"}]}, "keep": 1}
    assert strip_prose(doc) == {"finding": {"items": [{"code": "A"}]}, "keep": 1}


def test_agent_views_never_contain_prose(store):
    out = make_output()
    store.append("CLM-1", NewEvent(type=EventType.FINDING_CREATED, actor=Actor(kind="agent", id="damage_agent"),
                                   payload=out.model_dump(mode="json")))
    view = agent_view(store, "CLM-1", {EventType.FINDING_CREATED})
    flat = repr(view)
    assert "long prose" not in flat and "short prose" not in flat
    assert view[0]["payload"]["finding"] == {"severity": "minor"}
