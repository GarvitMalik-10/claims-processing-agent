"""Claude and Jev wrappers: raw I/O capture, redaction, record/replay. No network."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from PIL import Image as PILImage
from pydantic import BaseModel

from tests.conftest import jpeg_bytes

from app.jev.client import JevAnswer, JevClient
from app.llm.claude import ClaudeClient, ModelRefusal, image_block
from app.llm.fixtures import FixtureMissing, FixtureStore


class Extract(BaseModel):
    room: str


class FakeUsage:
    def to_dict(self):
        return {"input_tokens": 10, "output_tokens": 5}


class FakeClaudeResponse:
    def __init__(self, parsed, stop_reason="end_turn"):
        self.parsed_output = parsed
        self.stop_reason = stop_reason
        self.stop_details = SimpleNamespace(category="cyber", explanation="nope") if stop_reason == "refusal" else None
        self.model = "claude-sonnet-5-5"
        self.usage = FakeUsage()

    def to_dict(self):
        return {"model": self.model, "stop_reason": self.stop_reason}


class FakeAnthropic:
    def __init__(self, response):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))
        self._response = response

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def test_claude_record_then_replay(tmp_path, blobs):
    fixtures = FixtureStore(tmp_path / "fx", mode="record")
    fake = FakeAnthropic(FakeClaudeResponse(Extract(room="kitchen")))
    claude = ClaudeClient(blobs, model="claude-sonnet-5-5", client=fake, fixtures=fixtures)
    content = [image_block(jpeg_bytes(2400, 1800)), {"type": "text", "text": "Which room?"}]

    call = claude.structured(system="sys", content=content, output_model=Extract, prompt_version="v1")
    assert call.output.room == "kitchen"
    sent = fake.calls[0]
    assert sent["fallbacks"] == "default" and sent["output_format"] is Extract
    assert sent["output_config"] == {"effort": "medium"}

    logged = json.loads(blobs.get(call.raw_request_blob))
    assert logged["messages"][0]["content"][0]["source"]["data"].startswith("sha256:")

    fixtures.mode = "replay"
    replayed = ClaudeClient(blobs, model="claude-sonnet-5-5", client=None, fixtures=fixtures).structured(
        system="sys", content=content, output_model=Extract, prompt_version="v1")
    assert replayed.output == call.output


def test_claude_replay_misses_on_changed_prompt(tmp_path, blobs):
    fixtures = FixtureStore(tmp_path / "fx", mode="replay")
    with pytest.raises(FixtureMissing):
        ClaudeClient(blobs, model="m", fixtures=fixtures).structured(
            system="sys", content=[{"type": "text", "text": "x"}], output_model=Extract, prompt_version="v2")


def test_claude_refusal_raises(blobs):
    fake = FakeAnthropic(FakeClaudeResponse(None, stop_reason="refusal"))
    with pytest.raises(ModelRefusal):
        ClaudeClient(blobs, model="m", client=fake).structured(
            system="s", content=[{"type": "text", "text": "x"}], output_model=Extract, prompt_version="v1")


class FakeTypeSafe:
    def __init__(self):
        self.calls = []

    def system_one(self, *, state, questions, model):
        self.calls.append(state)
        return SimpleNamespace(model_dump=lambda mode: {
            "model": "jev-1.13.0",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "answers": {
                "photo_supports_story": {"type": "noul", "noul": 0.9},
                "severity": {"type": "choice", "choice": "moderate_localized_damage", "confidence": 0.7,
                             "probabilities": {"moderate_localized_damage": 0.7, "minor_surface_staining": 0.3}},
            },
        })


def test_jev_record_replay_and_image_logging(tmp_path, blobs):
    photo = tmp_path / "p.jpg"
    photo.write_bytes(jpeg_bytes(1920, 1440))
    fixtures = FixtureStore(tmp_path / "jev", mode="record")
    jev = JevClient(blobs, model="jev-latest", fixtures=fixtures, client=FakeTypeSafe())
    questions = {"photo_supports_story": {"type": "noul", "instructions": "Does `photo_1` support `story`?"}}
    call = jev.ask({"story": "pipe burst", "photo_1": photo}, questions, question_set_version="water_v1")

    assert call.model == "jev-1.13.0"
    assert call.answers["photo_supports_story"].measured_confidence == pytest.approx(0.8)
    logged = json.loads(blobs.get(call.raw_request_blob))
    assert logged["state"]["photo_1"].startswith("image:sha256:")
    # The logged (and sent) image is the normalized derivative in the blob store, not the 1920px original.
    sent_digest = logged["state"]["photo_1"].removeprefix("image:sha256:")
    assert max(PILImage.open(blobs.path(sent_digest)).size) <= 1568

    fixtures.mode = "replay"
    again = JevClient(blobs, model="jev-latest", fixtures=fixtures).ask(
        {"story": "pipe burst", "photo_1": photo}, questions, question_set_version="water_v1")
    assert again.answers == call.answers


def test_choice_measured_confidence_uses_reported_confidence():
    assert JevAnswer(type="choice", choice="a", confidence=0.42).measured_confidence == 0.42
