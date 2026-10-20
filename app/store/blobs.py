"""Content-addressed blob store for media and raw model I/O (README 6.1). Local folder now, S3 later."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from app.store.canonical import canonical_json, sha256_hex


class BlobStore(Protocol):
    def put(self, data: bytes) -> str: ...
    def get(self, digest: str) -> bytes: ...
    def path(self, digest: str) -> Path: ...


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, digest: str) -> Path:
        return self.root / digest[:2] / digest

    def put(self, data: bytes) -> str:
        digest = sha256_hex(data)
        target = self.path(digest)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(target)
        return digest

    def put_json(self, obj: Any) -> str:
        return self.put(canonical_json(obj))

    def get(self, digest: str) -> bytes:
        return self.path(digest).read_bytes()
