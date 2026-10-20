"""Jev (TypeSafe System One) wrapper: batched typed questions, measured probabilities, raw I/O capture.

State values that are `pathlib.Path` are sent as images (TypeSafe `Image` assets) and logged by
their sha256. Answers come back as `JevAnswer`, whose `measured_confidence` is the comparable
confidence scale used by routing (choice/score confidence, or |2p-1| for nouls - README 9.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from app.intake.images import normalized_path
from app.llm.fixtures import FixtureStore
from app.settings import get_settings
from app.store.blobs import LocalBlobStore
from app.store.canonical import sha256_hex

IMAGES_HEADER = {"TypeSafe-Danger-Zone-Images": "true"}


class JevAnswer(BaseModel):
    type: Literal["noul", "choice", "score"]
    noul: float | None = None
    choice: str | None = None
    score: float | None = None
    probabilities: dict[str, float] | None = None
    confidence: float | None = None

    @property
    def measured_confidence(self) -> float:
        if self.type == "noul":
            assert self.noul is not None
            return abs(2 * self.noul - 1)
        assert self.confidence is not None
        return self.confidence


@dataclass(frozen=True)
class JevCall:
    answers: dict[str, JevAnswer]
    model: str
    question_set_version: str
    raw_request_blob: str
    raw_response_blob: str


class Jev(Protocol):
    def ask(self, state: dict[str, Any], questions: dict[str, dict[str, Any]], *,
            question_set_version: str) -> JevCall: ...


def _logged_state(state: dict[str, Any]) -> dict[str, Any]:
    return {k: ("image:sha256:" + sha256_hex(v.read_bytes())) if isinstance(v, Path) else v for k, v in state.items()}


class JevClient:
    """Live client, optionally recording fixtures; or pure replay from fixtures (no network)."""

    def __init__(self, blobs: LocalBlobStore, *, model: str | None = None,
                 fixtures: FixtureStore | None = None, client: Any = None) -> None:
        self.blobs = blobs
        self.model = model or get_settings().jev_model
        self.fixtures = fixtures
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            from typesafe_sdk import TypeSafeClient

            self._client = TypeSafeClient(model=self.model, headers=IMAGES_HEADER)
        return self._client

    def ask(self, state: dict[str, Any], questions: dict[str, dict[str, Any]], *,
            question_set_version: str) -> JevCall:
        # Jev only accepts 280-1568 px images: send (and log) the normalized derivative.
        state = {k: normalized_path(v, self.blobs) if isinstance(v, Path) else v for k, v in state.items()}
        logged_request = {
            "model": self.model,
            "state": _logged_state(state),
            "questions": questions,
            "question_set_version": question_set_version,
        }
        request_blob = self.blobs.put_json(logged_request)

        if self.fixtures and self.fixtures.mode == "replay":
            raw = self.fixtures.load(logged_request)
        else:
            from typesafe_sdk import Image

            wire_state = {k: Image(v) if isinstance(v, Path) else v for k, v in state.items()}
            response = self.client.system_one(state=wire_state, questions=questions, model=self.model)
            raw = response.model_dump(mode="json")
            if self.fixtures and self.fixtures.mode == "record":
                self.fixtures.save(logged_request, raw)

        return JevCall(
            answers={name: JevAnswer.model_validate(a) for name, a in raw["answers"].items()},
            model=raw["model"],
            question_set_version=question_set_version,
            raw_request_blob=request_blob,
            raw_response_blob=self.blobs.put_json(raw),
        )
