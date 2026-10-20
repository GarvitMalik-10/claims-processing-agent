"""ClaimService - the single entry point used by the API, the scenario runner and tests.

Inputs only ever append evidence; `process` then starts the graph or resumes it from its interrupt.
"""

from __future__ import annotations

import sqlite3
import threading
from typing import Any

from langgraph.types import Command

from app.graph.deps import Deps
from app.graph.claim import build_claim_graph
from app.intake import evidence as intake
from app.models.domain import Estimate
from app.models.events import Actor, EventType, NewEvent
from app.store import projections as proj


def sqlite_checkpointer(path: str) -> Any:
    from langgraph.checkpoint.sqlite import SqliteSaver

    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))


class ClaimService:
    def __init__(self, deps: Deps, checkpointer: Any) -> None:
        self.deps = deps
        self.graph = build_claim_graph(deps, checkpointer)
        self._open_lock = threading.Lock()

    # --- intake -------------------------------------------------------------------------------
    def open_claim(self, customer_id: str, *, channel: str = "chat") -> str:
        customer = self.deps.data.customers[customer_id]
        with self._open_lock:  # number allocation + first event must be atomic (parallel intake)
            claim_id = f"CLM-2026-{len(self.deps.store.claim_ids()) + 1:06d}"
            self.deps.store.append(claim_id, NewEvent(
                type=EventType.CLAIM_NOTIFIED, actor=Actor(kind="customer", id=customer_id),
                payload={"customer_id": customer_id, "policy_hint": customer.policy_id, "channel": channel,
                         "language_preference": customer.language},
            ))
        return claim_id

    def add_text(self, claim_id: str, text: str, *, sent_at: str | None = None) -> str:
        lang = proj.notification(self.deps.store, claim_id)["language_preference"]
        return intake.receive_text(self.deps.store, claim_id, text, sent_at=sent_at, default_language=lang)

    def add_image(self, claim_id: str, data: bytes, *, filename: str | None = None, sent_at: str | None = None,
                  exif_override: dict | None = None) -> str:
        return intake.receive_image(self.deps.store, self.deps.blobs, claim_id, data, filename=filename,
                                    sent_at=sent_at, exif_override=exif_override)

    def add_estimate(self, claim_id: str, estimate: Estimate, *, sent_at: str | None = None) -> str:
        return intake.receive_estimate(self.deps.store, claim_id, estimate, sent_at=sent_at)

    # --- processing ---------------------------------------------------------------------------
    def _config(self, claim_id: str) -> dict:
        return {"configurable": {"thread_id": claim_id}}

    def process(self, claim_id: str) -> dict:
        """Run the graph until it finishes or waits. Safe to call after every new input."""
        cfg = self._config(claim_id)
        snapshot = self.graph.get_state(cfg)
        if snapshot.next:  # waiting on interrupt() -> resume with the new evidence
            self.graph.invoke(Command(resume=True), cfg)
        elif not snapshot.values:  # never started
            self.graph.invoke({"claim_id": claim_id}, cfg)
        return self.status(claim_id)

    def status(self, claim_id: str) -> dict:
        snapshot = self.graph.get_state(self._config(claim_id))
        values = snapshot.values or {}
        return {
            "claim_id": claim_id,
            "stage": values.get("stage"),
            "waiting": bool(snapshot.next),
            "info_request_rounds": values.get("info_request_rounds", 0),
            "route_reasons": values.get("route_reasons", []),
        }

    def outbound_messages(self, claim_id: str) -> list[dict]:
        return [e.payload for e in self.deps.store.events(claim_id, {EventType.MESSAGE_SENT})]
