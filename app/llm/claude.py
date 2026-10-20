"""Claude Sonnet 5.5 wrapper: structured outputs (Pydantic), vision, raw I/O capture, refusal fallback.

Every call stores the exact request (images replaced by their blob hash) and the exact response in
the blob store; the caller puts both digests in the event's provenance.
"""

from __future__ import annotations

import base64
import copy
import os
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar

import anthropic
from pydantic import BaseModel

from app.intake.images import normalize_image_bytes
from app.llm.fixtures import FixtureStore
from app.settings import get_settings
from app.store.blobs import LocalBlobStore
from app.store.canonical import sha256_hex

T = TypeVar("T", bound=BaseModel)

Effort = Literal["low", "medium", "high", "xhigh", "max"]

# Server-side refusal fallback ("default" routing by refusal category). Claude API only.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ModelRefusal(RuntimeError):
    def __init__(self, category: str | None, explanation: str | None) -> None:
        super().__init__(f"Model declined ({category}): {explanation}")
        self.category = category
        self.explanation = explanation


class ModelOutputInvalid(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelCall(Generic[T]):
    output: T
    model: str
    stop_reason: str | None
    usage: dict[str, Any]
    raw_request_blob: str
    raw_response_blob: str


def image_block(data: bytes) -> dict[str, Any]:
    """Image content block from raw upload bytes, normalized to an upright JPEG <= 1568 px."""
    jpeg = normalize_image_bytes(data)
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(jpeg).decode()},
    }


def redact_images(params: dict[str, Any]) -> dict[str, Any]:
    """Replace inline base64 images with 'sha256:<digest>' so stored requests stay small and hashable."""
    out = copy.deepcopy(params)
    for msg in out.get("messages", []):
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            src = block.get("source") if isinstance(block, dict) else None
            if src and src.get("type") == "base64":
                src["data"] = "sha256:" + sha256_hex(base64.standard_b64decode(src["data"]))
    return out


class ClaudeClient:
    def __init__(
        self,
        blobs: LocalBlobStore,
        *,
        model: str | None = None,
        client: anthropic.Anthropic | None = None,
        fixtures: FixtureStore | None = None,
        default_effort: Effort = "medium",
    ) -> None:
        self.blobs = blobs
        self.model = model or get_settings().llm_model
        self.fixtures = fixtures
        self.default_effort = default_effort
        self._client = client

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            # Org-level API keys must name a workspace on every request; workspace-scoped keys don't.
            workspace = os.getenv("ANTHROPIC_WORKSPACE_ID", "").strip()
            headers = {"anthropic-workspace-id": workspace} if workspace else None
            self._client = anthropic.Anthropic(default_headers=headers)
        return self._client

    def structured(
        self,
        *,
        system: str,
        content: list[dict[str, Any]],
        output_model: type[T],
        prompt_version: str,
        effort: Effort | None = None,
        max_tokens: int = 16000,
    ) -> ModelCall[T]:
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": content}],
            "output_config": {"effort": effort or self.default_effort},
        }
        logged_request = {
            **redact_images(params),
            "output_schema": output_model.__name__,
            "prompt_version": prompt_version,
        }
        request_blob = self.blobs.put_json(logged_request)

        if self.fixtures and self.fixtures.mode == "replay":
            recorded = self.fixtures.load(logged_request)
            return ModelCall(
                output=output_model.model_validate(recorded["parsed_output"]),
                model=recorded["model"],
                stop_reason=recorded.get("stop_reason"),
                usage=recorded.get("usage", {}),
                raw_request_blob=request_blob,
                raw_response_blob=self.blobs.put_json(recorded),
            )

        response = self.client.beta.messages.parse(
            **params,
            output_format=output_model,
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        raw = response.to_dict()
        response_blob = self.blobs.put_json(raw)

        if response.stop_reason == "refusal":
            details = response.stop_details
            raise ModelRefusal(getattr(details, "category", None), getattr(details, "explanation", None))
        if response.parsed_output is None:
            raise ModelOutputInvalid(f"No parsed output (stop_reason={response.stop_reason})")

        usage = response.usage.to_dict() if response.usage else {}
        if self.fixtures and self.fixtures.mode == "record":
            self.fixtures.save(logged_request, {
                "parsed_output": response.parsed_output.model_dump(mode="json"),
                "model": response.model,
                "stop_reason": response.stop_reason,
                "usage": usage,
            })
        return ModelCall(
            output=response.parsed_output,
            model=response.model,
            stop_reason=response.stop_reason,
            usage=usage,
            raw_request_blob=request_blob,
            raw_response_blob=response_blob,
        )
