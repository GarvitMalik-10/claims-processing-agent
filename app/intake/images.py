"""Image normalization for the models (README 7.1): upright, RGB JPEG, each side within 280-1568 px.

Jev rejects images outside 280-1568 px per side; Claude also works best at <= 1568 px. The
normalized derivative is what the models see, so it is stored in the blob store and its hash is
what the raw-request logs reference. The original upload is kept separately as evidence.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps

from app.store.blobs import LocalBlobStore

MAX_SIDE = 1568
MIN_SIDE = 280
JPEG_QUALITY = 90


class ImageTooSmall(ValueError):
    pass


def normalize_image_bytes(data: bytes) -> bytes:
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        if min(img.size) < MIN_SIDE:
            raise ImageTooSmall(f"Image {img.size[0]}x{img.size[1]} is below {MIN_SIDE}px on a side")
        if max(img.size) > MAX_SIDE:
            img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        # A very elongated image could now have its short side below the minimum.
        if min(img.size) < MIN_SIDE:
            raise ImageTooSmall(f"Image aspect ratio too extreme after resizing to {img.size}")
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=JPEG_QUALITY)
        return out.getvalue()


def normalized_path(source: Path, blobs: LocalBlobStore) -> Path:
    """Normalize `source` into the blob store and return the stored file's path."""
    digest = blobs.put(normalize_image_bytes(source.read_bytes()))
    return blobs.path(digest)
