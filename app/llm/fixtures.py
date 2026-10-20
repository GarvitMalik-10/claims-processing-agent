"""Record/replay of model calls, so tests and the eval suite can run without live models.

A fixture is keyed by the sha256 of the canonical (redacted) request, so a changed prompt, question
set or input automatically misses the fixture instead of silently replaying a stale answer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from app.store.canonical import canonical_json, sha256_hex

FixtureMode = Literal["off", "record", "replay"]


class FixtureMissing(LookupError):
    pass


class FixtureStore:
    def __init__(self, root: Path, mode: FixtureMode = "off") -> None:
        self.root = root
        self.mode = mode

    @staticmethod
    def key(request: Any) -> str:
        return sha256_hex(canonical_json(request))[:24]

    def load(self, request: Any) -> dict[str, Any]:
        path = self.root / f"{self.key(request)}.json"
        if not path.exists():
            raise FixtureMissing(f"No recorded response for request {self.key(request)} in {self.root}")
        return json.loads(path.read_text(encoding="utf-8"))["response"]

    def save(self, request: Any, response: Any) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{self.key(request)}.json"
        path.write_text(json.dumps({"request": request, "response": response}, ensure_ascii=False, indent=2,
                                   default=str), encoding="utf-8")
