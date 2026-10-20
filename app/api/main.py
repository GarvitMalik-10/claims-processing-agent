"""Demo API (FastAPI). The UI polls events by sequence number; every input turn is processed in the
background, one claim at a time. Serves the built React app from web/dist.

Run:  .venv\\Scripts\\python.exe -m uvicorn app.api.main:app --port 8000
"""

from __future__ import annotations

import base64
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.api.gallery import gallery, gallery_exif
from app.audit.replay import replay
from app.graph.deps import build_deps
from app.models.events import EventType
from app.service import ClaimService, sqlite_checkpointer
from app.settings import ROOT, get_settings
from app.store.event_store import tamper_for_demo

settings = get_settings()
checkpointer = sqlite_checkpointer(str(settings.checkpoint_db))
deps = build_deps(settings)
service = ClaimService(deps, checkpointer)
pool = ThreadPoolExecutor(max_workers=4)
_busy: dict[str, bool] = {}
_claim_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()

app = FastAPI(title="Tecto claims demo")


def _lock(cid: str) -> threading.Lock:
    with _locks_guard:
        return _claim_locks.setdefault(cid, threading.Lock())


def _run(cid: str, fn, *args) -> None:
    """Run a graph step in the background; one step per claim at a time."""
    def job() -> None:
        with _lock(cid):
            _busy[cid] = True
            try:
                fn(cid, *args)
            except Exception as exc:  # surfaced in the timeline as a system.error
                from app.graph.emit import emit_error

                emit_error(deps.store, cid, node="api.background", error=exc)
            finally:
                _busy[cid] = False
    _busy[cid] = True
    pool.submit(job)


def _known(cid: str) -> None:
    if cid not in deps.store.claim_ids():
        raise HTTPException(404, f"Unknown claim {cid}")


# --- reference data ---------------------------------------------------------------------------

@app.get("/api/personas")
def personas() -> list[dict]:
    out = []
    for c in deps.data.customers.values():
        p = deps.data.policy_book.policy(c.policy_id)
        product = deps.data.policy_book.products[p.product]
        out.append({"customer_id": c.customer_id, "name": c.name, "language": c.language,
                    "address": c.address.one_line, "note": c.persona_note, "policy_id": p.policy_id,
                    "product": product.name["en"], "extensions": product.extensions, "start_date": str(p.start_date),
                    "deductible": p.deductible.get("default")})
    return out


@app.get("/api/gallery")
def get_gallery() -> dict:
    return gallery(deps.data)


@app.get("/api/gallery/images/{image_id}")
def gallery_image(image_id: str) -> FileResponse:
    if image_id not in deps.data.observations:
        raise HTTPException(404)
    return FileResponse(deps.data.image_path(image_id), media_type="image/jpeg")


@app.get("/api/blobs/{digest}")
def blob(digest: str) -> Response:
    try:
        data = deps.blobs.get(digest)
    except FileNotFoundError:
        raise HTTPException(404)
    media = "image/jpeg" if data[:2] == b"\xff\xd8" else "application/json"
    return Response(data, media_type=media)


# --- claims -----------------------------------------------------------------------------------

class NewClaim(BaseModel):
    customer_id: str


class Upload(BaseModel):
    filename: str
    data_b64: str


class Turn(BaseModel):
    text: str | None = None
    gallery_images: list[str] = Field(default_factory=list)
    uploads: list[Upload] = Field(default_factory=list)
    gallery_estimate: str | None = None


@app.get("/api/claims")
def list_claims() -> list[dict]:
    out = []
    for cid in reversed(deps.store.claim_ids()):
        note = deps.store.events(cid, {EventType.CLAIM_NOTIFIED})[0].payload
        out.append({"claim_id": cid, "customer_id": note["customer_id"], **_status(cid)})
    return out


@app.post("/api/claims")
def create_claim(req: NewClaim) -> dict:
    if req.customer_id not in deps.data.customers:
        raise HTTPException(400, "unknown persona")
    return {"claim_id": service.open_claim(req.customer_id)}


def _process(cid: str) -> None:
    service.process(cid)


@app.post("/api/claims/{cid}/turn")
def post_turn(cid: str, turn: Turn) -> dict:
    """One customer turn: text and/or attachments, then the graph runs (or resumes) once."""
    _known(cid)
    customer = deps.data.customers[deps.store.events(cid, {EventType.CLAIM_NOTIFIED})[0].payload["customer_id"]]
    if turn.text and turn.text.strip():
        service.add_text(cid, turn.text.strip())
    for image_id in turn.gallery_images:
        service.add_image(cid, deps.data.image_path(image_id).read_bytes(), filename=f"{image_id}.jpg",
                          exif_override=gallery_exif(image_id, customer))
    for up in turn.uploads:
        service.add_image(cid, base64.b64decode(up.data_b64), filename=up.filename)
    if turn.gallery_estimate:
        est = deps.data.scenarios[turn.gallery_estimate].estimate
        if est is None:
            raise HTTPException(400, "scenario has no estimate")
        service.add_estimate(cid, est)
    _run(cid, _process)
    return {"ok": True}


def _status(cid: str) -> dict:
    st = service.status(cid)
    st["busy"] = _busy.get(cid, False)
    return st


@app.get("/api/claims/{cid}/status")
def claim_status(cid: str) -> dict:
    _known(cid)
    return _status(cid)


@app.get("/api/claims/{cid}/events")
def claim_events(cid: str, after: int = 0) -> dict:
    _known(cid)
    events = [e.model_dump(mode="json") for e in deps.store.events(cid) if e.seq > after]
    return {"events": events, "status": _status(cid)}


@app.get("/api/claims/{cid}/report")
def claim_report(cid: str) -> dict:
    _known(cid)
    return service.report(cid).model_dump(mode="json")


# --- human review -----------------------------------------------------------------------------

@app.get("/api/review/inbox")
def inbox() -> list[dict]:
    items = []
    for cid in reversed(deps.store.claim_ids()):
        st = _status(cid)
        if st["waiting_for"] != "awaiting_human_review":
            continue
        req = deps.store.events(cid, {EventType.HUMAN_REVIEW_REQUESTED})[-1].payload
        pay = deps.store.events(cid, {EventType.PAYOUT_CALCULATED})
        rec = pay[-1].payload.get("recommendation") if pay else None
        note = deps.store.events(cid, {EventType.CLAIM_NOTIFIED})[0].payload
        items.append({"claim_id": cid, "customer": deps.data.customers[note["customer_id"]].name,
                      "queue": req["queue"], "reasons": req["reasons"], "approver": req["approver"],
                      "proposed_payout": rec["payout"] if rec else None})
    return items


@app.post("/api/claims/{cid}/review")
def post_review(cid: str, decision: dict[str, Any]) -> dict:
    _known(cid)
    from app.graph.decision import ReviewDecision

    try:
        ReviewDecision.model_validate(decision)
    except Exception as exc:
        raise HTTPException(422, str(exc))
    if service.status(cid)["waiting_for"] != "awaiting_human_review":
        raise HTTPException(409, "claim is not waiting for a review")
    _run(cid, service.review, decision)
    return {"ok": True}


# --- audit ------------------------------------------------------------------------------------

@app.get("/api/claims/{cid}/audit/verify")
def verify(cid: str) -> dict:
    _known(cid)
    return deps.store.verify_chain(cid).model_dump()


@app.post("/api/claims/{cid}/audit/tamper")
def tamper(cid: str) -> dict:
    """Demo only: an 'attacker' edits the payout in the database directly, bypassing the application."""
    _known(cid)
    pay = deps.store.events(cid, {EventType.PAYOUT_CALCULATED})
    target = pay[-1] if pay else deps.store.events(cid)[-1]
    patch = {"recommendation": {**target.payload["recommendation"], "payout": 99999.0}} \
        if target.payload.get("recommendation") else {"tampered": True}
    tamper_for_demo(deps.store, cid, target.seq, patch)
    return {"tampered_seq": target.seq, "type": target.type}


@app.get("/api/claims/{cid}/audit/replay")
def audit_replay(cid: str) -> dict:
    _known(cid)
    return replay(deps.store, deps.data, cid).model_dump()


@app.get("/api/claims/{cid}/audit/export")
def export(cid: str) -> JSONResponse:
    """One JSON bundle: every event, the report, chain verification, replay, and raw model I/O."""
    _known(cid)
    events = deps.store.events(cid)
    raw: dict[str, Any] = {}
    for e in events:
        for digest in (e.provenance.raw_request_blob, e.provenance.raw_response_blob):
            if digest and digest not in raw:
                data = deps.blobs.get(digest)
                if data[:2] != b"\xff\xd8":
                    raw[digest] = json.loads(data)
    bundle = {"claim_id": cid, "verification": deps.store.verify_chain(cid).model_dump(),
              "replay": replay(deps.store, deps.data, cid).model_dump(),
              "report": service.report(cid).model_dump(mode="json"),
              "events": [e.model_dump(mode="json") for e in events], "raw_model_io": raw}
    return JSONResponse(bundle, headers={"Content-Disposition": f'attachment; filename="{cid}-audit.json"'})


# --- demo housekeeping ------------------------------------------------------------------------

@app.post("/api/demo/reset")
def reset_demo() -> dict:
    """Start a clean demo session: the current claim file and graph checkpoints are moved to
    var/archive/<timestamp>/ (nothing is deleted), then fresh stores are opened."""
    global deps, service, checkpointer
    if any(_busy.values()):
        raise HTTPException(409, "a claim is still being processed - try again in a moment")
    import shutil
    import time

    archive = settings.data_dir / "archive" / time.strftime("%Y%m%d-%H%M%S")
    archive.mkdir(parents=True, exist_ok=True)
    deps.store.close()
    checkpointer.conn.close()
    for path in (settings.event_db, settings.checkpoint_db):
        for f in path.parent.glob(path.name + "*"):  # include -wal / -shm files
            shutil.move(str(f), archive / f.name)
    checkpointer = sqlite_checkpointer(str(settings.checkpoint_db))
    deps = build_deps(settings)
    service = ClaimService(deps, checkpointer)
    _busy.clear()
    _claim_locks.clear()
    return {"archived_to": str(archive.relative_to(ROOT))}


# --- frontend ---------------------------------------------------------------------------------

_dist = ROOT / "web" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
