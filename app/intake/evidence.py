"""Channel normalizers (README 7.1): every input becomes `evidence.received` + `evidence.normalized`.

Text: stored as-is, language detected. Image: original kept, normalized derivative for the models,
EXIF (timestamp, GPS, device) and a perceptual hash for duplicate detection. Estimate: a structured
contractor quote. Voice and video arrive in M2b (they need ffmpeg / faster-whisper).
"""

from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Any

import imagehash
from PIL import ExifTags, Image

from app.intake.images import normalize_image_bytes
from app.models.domain import Estimate
from app.models.events import Actor, EventType, NewEvent
from app.store.blobs import LocalBlobStore
from app.store.event_store import EventStore

CUSTOMER = Actor(kind="customer", id="customer")
NORMALIZER = Actor(kind="system", id="intake_normalizer")

_NL = {"de", "het", "een", "en", "is", "van", "ik", "we", "wij", "niet", "er", "op", "dat", "in", "mijn", "ons",
       "onze", "gisteren", "vanochtend", "graag", "bij", "zijn", "ook", "nog", "maar", "kunnen", "hebben", "geen"}
_EN = {"the", "a", "an", "and", "is", "of", "i", "we", "not", "there", "on", "that", "in", "my", "our", "yesterday",
       "this", "morning", "please", "at", "are", "also", "still", "but", "can", "have", "no", "was", "it"}


def detect_language(text: str, default: str = "nl") -> str:
    words = re.findall(r"[a-zà-ÿ]+", text.lower())
    nl = sum(w in _NL for w in words)
    en = sum(w in _EN for w in words)
    if nl == en:
        return default
    return "nl" if nl > en else "en"


def _next_evidence_id(store: EventStore, claim_id: str) -> str:
    return f"EV-{len(store.events(claim_id, {EventType.EVIDENCE_RECEIVED})) + 1:04d}"


def receive_text(store: EventStore, claim_id: str, text: str, *, channel: str = "chat",
                 sent_at: str | None = None, default_language: str = "nl") -> str:
    ev_id = _next_evidence_id(store, claim_id)
    store.append(claim_id, NewEvent(type=EventType.EVIDENCE_RECEIVED, actor=CUSTOMER, evidence_refs=[ev_id],
                                    payload={"evidence_id": ev_id, "kind": "text", "channel": channel,
                                             "text": text, "sent_at": sent_at}))
    store.append(claim_id, NewEvent(type=EventType.EVIDENCE_NORMALIZED, actor=NORMALIZER, evidence_refs=[ev_id],
                                    payload={"evidence_id": ev_id, "language": detect_language(text, default_language)}))
    return ev_id


def _gps_decimal(gps: dict[int, Any]) -> dict[str, float] | None:
    try:
        def conv(vals: Any, ref: str) -> float:
            d, m, s = (float(v) for v in vals)
            sign = -1 if ref in ("S", "W") else 1
            return sign * (d + m / 60 + s / 3600)
        return {"lat": round(conv(gps[2], gps[1]), 6), "lon": round(conv(gps[4], gps[3]), 6)}
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def read_exif(data: bytes) -> dict[str, Any]:
    with Image.open(io.BytesIO(data)) as img:
        exif = img.getexif()
        if not exif:
            return {}
        base = {ExifTags.TAGS.get(k, str(k)): v for k, v in exif.items()}
        sub = exif.get_ifd(ExifTags.IFD.Exif)
        taken = sub.get(ExifTags.Base.DateTimeOriginal) or base.get("DateTime")
        gps = _gps_decimal(dict(exif.get_ifd(ExifTags.IFD.GPSInfo)))
    out: dict[str, Any] = {}
    if taken:
        try:
            out["DateTimeOriginal"] = datetime.strptime(str(taken), "%Y:%m:%d %H:%M:%S").isoformat()
        except ValueError:
            out["DateTimeOriginal_raw"] = str(taken)
    for key in ("Make", "Model", "Software"):
        if base.get(key):
            out[key] = str(base[key]).strip("\x00 ")
    if gps:
        out["GPS"] = gps
    return out


def receive_image(store: EventStore, blobs: LocalBlobStore, claim_id: str, data: bytes, *,
                  filename: str | None = None, channel: str = "chat", sent_at: str | None = None,
                  exif_override: dict[str, Any] | None = None) -> str:
    """`exif_override` is for synthetic demo media only; it is recorded as such in the trail."""
    ev_id = _next_evidence_id(store, claim_id)
    original = blobs.put(data)
    store.append(claim_id, NewEvent(type=EventType.EVIDENCE_RECEIVED, actor=CUSTOMER, evidence_refs=[ev_id],
                                    payload={"evidence_id": ev_id, "kind": "image", "channel": channel,
                                             "blob": original, "filename": filename, "sent_at": sent_at}))
    normalized = blobs.put(normalize_image_bytes(data))
    with Image.open(blobs.path(normalized)) as img:
        phash = str(imagehash.phash(img))
        size = list(img.size)
    exif, exif_source = (exif_override, "synthetic_demo_metadata") if exif_override is not None else (read_exif(data), "file")
    store.append(claim_id, NewEvent(type=EventType.EVIDENCE_NORMALIZED, actor=NORMALIZER, evidence_refs=[ev_id],
                                    payload={"evidence_id": ev_id, "normalized_blob": normalized, "size": size,
                                             "phash": phash, "exif": exif or {}, "exif_source": exif_source}))
    return ev_id


def receive_estimate(store: EventStore, claim_id: str, estimate: Estimate, *, channel: str = "chat",
                     sent_at: str | None = None) -> str:
    ev_id = _next_evidence_id(store, claim_id)
    store.append(claim_id, NewEvent(type=EventType.EVIDENCE_RECEIVED, actor=CUSTOMER, evidence_refs=[ev_id],
                                    payload={"evidence_id": ev_id, "kind": "document", "subtype": "estimate",
                                             "channel": channel, "estimate": estimate.model_dump(mode="json"),
                                             "sent_at": sent_at}))
    return ev_id
