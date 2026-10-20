"""Append-only claim file with a per-claim sha256 hash chain (README section 6).

The store is the system of record: nothing is updated or deleted (SQLite triggers enforce it),
current status is a projection over events, and `verify_chain` proves nothing was altered.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from app.models.events import GENESIS_HASH, Event, EventType, NewEvent
from app.store.canonical import canonical_json, sha256_hex


class ChainVerification(BaseModel):
    claim_id: str
    event_count: int
    intact: bool
    first_broken_seq: int | None = None
    problem: str | None = None


class EventStore(Protocol):
    def append(self, claim_id: str, event: NewEvent) -> Event: ...
    def events(self, claim_id: str, types: Iterable[EventType] | None = None) -> list[Event]: ...
    def claim_ids(self) -> list[str]: ...
    def verify_chain(self, claim_id: str) -> ChainVerification: ...


def compute_hash(event: Event) -> str:
    return sha256_hex(canonical_json(event.hash_material()))


_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    claim_id      TEXT    NOT NULL,
    seq           INTEGER NOT NULL,
    event_id      TEXT    NOT NULL UNIQUE,
    type          TEXT    NOT NULL,
    actor         TEXT    NOT NULL,
    timestamp     TEXT    NOT NULL,
    payload       TEXT    NOT NULL,
    evidence_refs TEXT    NOT NULL,
    provenance    TEXT    NOT NULL,
    prev_hash     TEXT    NOT NULL,
    hash          TEXT    NOT NULL,
    PRIMARY KEY (claim_id, seq)
);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'claim file is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'claim file is append-only'); END;
"""


class SqliteEventStore:
    def __init__(self, db_path: Path | str, clock: Callable[[], datetime] | None = None) -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, isolation_level=None)
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._listeners: list[Callable[[Event], None]] = []

    def subscribe(self, listener: Callable[[Event], None]) -> None:
        """Called after every append (live timeline / websocket feed)."""
        self._listeners.append(listener)

    def append(self, claim_id: str, event: NewEvent) -> Event:
        # Parallel agents append concurrently: the lock + IMMEDIATE transaction make seq and
        # prev_hash assignment atomic.
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT seq, hash FROM events WHERE claim_id = ? ORDER BY seq DESC LIMIT 1", (claim_id,)
                ).fetchone()
                seq, prev_hash = (row[0] + 1, row[1]) if row else (1, GENESIS_HASH)
                stored = Event(
                    **event.model_dump(),
                    claim_id=claim_id,
                    seq=seq,
                    event_id=str(uuid.uuid4()),
                    timestamp=self._clock(),
                    prev_hash=prev_hash,
                    hash="",
                )
                stored = stored.model_copy(update={"hash": compute_hash(stored)})
                d = stored.model_dump(mode="json")
                self._conn.execute(
                    "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        claim_id, seq, d["event_id"], d["type"], json.dumps(d["actor"]), d["timestamp"],
                        json.dumps(d["payload"], ensure_ascii=False), json.dumps(d["evidence_refs"]),
                        json.dumps(d["provenance"]), d["prev_hash"], d["hash"],
                    ),
                )
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
        for listener in self._listeners:
            listener(stored)
        return stored

    def events(self, claim_id: str, types: Iterable[EventType] | None = None) -> list[Event]:
        rows = self._conn.execute(
            "SELECT claim_id, seq, event_id, type, actor, timestamp, payload, evidence_refs, provenance, prev_hash, hash "
            "FROM events WHERE claim_id = ? ORDER BY seq",
            (claim_id,),
        ).fetchall()
        wanted = set(types) if types is not None else None
        out = [self._row_to_event(r) for r in rows]
        return [e for e in out if wanted is None or e.type in wanted]

    def claim_ids(self) -> list[str]:
        return [r[0] for r in self._conn.execute("SELECT DISTINCT claim_id FROM events ORDER BY claim_id")]

    def verify_chain(self, claim_id: str) -> ChainVerification:
        events = self.events(claim_id)
        prev = GENESIS_HASH
        for i, e in enumerate(events, start=1):
            if e.seq != i:
                return ChainVerification(claim_id=claim_id, event_count=len(events), intact=False,
                                         first_broken_seq=e.seq, problem="sequence gap")
            if e.prev_hash != prev:
                return ChainVerification(claim_id=claim_id, event_count=len(events), intact=False,
                                         first_broken_seq=e.seq, problem="prev_hash does not match previous event")
            if compute_hash(e) != e.hash:
                return ChainVerification(claim_id=claim_id, event_count=len(events), intact=False,
                                         first_broken_seq=e.seq, problem="event content does not match its hash")
            prev = e.hash
        return ChainVerification(claim_id=claim_id, event_count=len(events), intact=True)

    @staticmethod
    def _row_to_event(r: tuple) -> Event:
        return Event(
            claim_id=r[0], seq=r[1], event_id=r[2], type=r[3], actor=json.loads(r[4]), timestamp=r[5],
            payload=json.loads(r[6]), evidence_refs=json.loads(r[7]), provenance=json.loads(r[8]),
            prev_hash=r[9], hash=r[10],
        )

    def close(self) -> None:
        self._conn.close()


def tamper_for_demo(store: SqliteEventStore, claim_id: str, seq: int, payload_patch: dict) -> None:
    """Demo-only 'attacker' edit: bypasses the append-only triggers and rewrites one payload.

    Exists solely so the Audit tab can show Verify integrity turning red. Never used by the pipeline.
    """
    with store._lock:
        conn = store._conn
        row = conn.execute("SELECT payload FROM events WHERE claim_id=? AND seq=?", (claim_id, seq)).fetchone()
        if row is None:
            raise KeyError(f"{claim_id}#{seq}")
        payload = {**json.loads(row[0]), **payload_patch}
        conn.executescript("DROP TRIGGER IF EXISTS events_no_update;")
        try:
            conn.execute("UPDATE events SET payload=? WHERE claim_id=? AND seq=?",
                         (json.dumps(payload, ensure_ascii=False), claim_id, seq))
        finally:
            conn.executescript(_SCHEMA)
