from __future__ import annotations

import io

import pytest
from PIL import Image

from app.data.loader import load_synthetic
from app.intake.images import MAX_SIDE, MIN_SIDE, ImageTooSmall, normalize_image_bytes
from tests.conftest import jpeg_bytes


def size(data: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(data)).size


def test_large_image_is_downscaled_keeping_aspect():
    w, h = size(normalize_image_bytes(jpeg_bytes(3000, 2000)))
    assert max(w, h) == MAX_SIDE and abs(w / h - 1.5) < 0.01


def test_image_within_bounds_keeps_its_size():
    assert size(normalize_image_bytes(jpeg_bytes(800, 600))) == (800, 600)


def test_too_small_image_is_rejected():
    with pytest.raises(ImageTooSmall):
        normalize_image_bytes(jpeg_bytes(200, 600))


def test_png_with_alpha_becomes_jpeg():
    out = io.BytesIO()
    Image.new("RGBA", (500, 500), (0, 0, 0, 0)).save(out, format="PNG")
    assert Image.open(io.BytesIO(normalize_image_bytes(out.getvalue()))).format == "JPEG"


@pytest.mark.parametrize("image_id", sorted(load_synthetic().observations))
def test_every_demo_image_fits_jev_limits(image_id):
    data = load_synthetic()
    w, h = size(normalize_image_bytes(data.image_path(image_id).read_bytes()))
    assert MIN_SIDE <= min(w, h) and max(w, h) <= MAX_SIDE
