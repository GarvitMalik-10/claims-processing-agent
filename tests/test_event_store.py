from __future__ import annotations

import sqlite3
import threading

import pytest

from app.models.events import GENESIS_HASH, Actor, EventType, NewEvent
from app.store.event_store import tamper_for_demo

RULE = Actor(kind="rule", id="test_rule")


def ev(n: int) -> NewEvent:
    return NewEvent(type=EventType.RULE_EVALUATED, actor=RULE, payload={"n": n, "text": "schade €"})


def test_append_assigns_sequence_and_chain(store):
    a = store.append("CLM-1", ev(1))
    b = store.append("CLM-1", ev(2))
    assert (a.seq, b.seq) == (1, 2)
    assert a.prev_hash == GENESIS_HASH
    assert b.prev_hash == a.hash
    assert [e.payload["n"] for e in store.events("CLM-1")] == [1, 2]


def test_chains_are_per_claim(store):
    store.append("CLM-1", ev(1))
    first_other = store.append("CLM-2", ev(1))
    assert first_other.seq == 1 and first_other.prev_hash == GENESIS_HASH


def test_roundtrip_preserves_hash(store):
    store.append("CLM-1", ev(1))
    assert store.verify_chain("CLM-1").intact


def test_tampering_is_detected_at_the_edited_event(store):
    for i in range(1, 5):
        store.append("CLM-1", ev(i))
    tamper_for_demo(store, "CLM-1", 3, {"n": 999})
    result = store.verify_chain("CLM-1")
    assert not result.intact
    assert result.first_broken_seq == 3
    assert "hash" in result.problem


def test_store_is_append_only_at_database_level(store):
    store.append("CLM-1", ev(1))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store._conn.execute("UPDATE events SET payload='{}' WHERE seq=1")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store._conn.execute("DELETE FROM events")


def test_triggers_restored_after_demo_tamper(store):
    store.append("CLM-1", ev(1))
    tamper_for_demo(store, "CLM-1", 1, {"n": 2})
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("DELETE FROM events")


def test_concurrent_appends_keep_chain_intact(store):
    # Damage / Policy / Risk append in parallel during fan-out.
    def worker(k: int) -> None:
        for i in range(20):
            store.append("CLM-1", ev(k * 100 + i))

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    result = store.verify_chain("CLM-1")
    assert result.intact and result.event_count == 60


def test_type_filter_and_listener(store):
    seen = []
    store.subscribe(seen.append)
    store.append("CLM-1", ev(1))
    store.append("CLM-1", NewEvent(type=EventType.MESSAGE_SENT, actor=RULE, payload={"text": "hoi"}))
    assert [e.type for e in store.events("CLM-1", {EventType.MESSAGE_SENT})] == [EventType.MESSAGE_SENT]
    assert len(seen) == 2
