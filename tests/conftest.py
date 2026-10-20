from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count

import pytest

from app.store.blobs import LocalBlobStore
from app.store.event_store import SqliteEventStore


@pytest.fixture
def clock():
    ticks = count()
    start = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    return lambda: start + timedelta(seconds=next(ticks))


@pytest.fixture
def store(tmp_path, clock):
    s = SqliteEventStore(tmp_path / "claims.sqlite", clock=clock)
    yield s
    s.close()


@pytest.fixture
def blobs(tmp_path):
    return LocalBlobStore(tmp_path / "blobs")


def jpeg_bytes(width: int = 800, height: int = 600, color=(180, 120, 90)) -> bytes:
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (width, height), color).save(out, format="JPEG")
    return out.getvalue()
