"""Remove original camera metadata (EXIF/GPS) from the demo images.

The Wikimedia photos are stand-ins for customer photos; their real 2007-2011 capture dates and US GPS
positions would make honest demo claims look fraudulent. Scenarios that need metadata set it explicitly
(`exif_override`), recorded in the claim file as synthetic demo metadata. Re-saved with quality="keep"
(same JPEG quantization tables), so the pixels are effectively unchanged.

Run once:  .venv\\Scripts\\python.exe -m scripts.strip_demo_exif
"""

from __future__ import annotations

from PIL import Image

from app.data.loader import load_synthetic
from app.intake.evidence import read_exif


def main() -> None:
    data = load_synthetic()
    for image_id in sorted(data.observations):
        path = data.image_path(image_id)
        if not read_exif(path.read_bytes()):
            continue
        with Image.open(path) as img:
            img.load()
            img.info.pop("exif", None)
            img.save(path, format="JPEG", quality="keep", exif=b"")
        print(f"stripped {image_id}: now {read_exif(path.read_bytes()) or 'no EXIF'}")


if __name__ == "__main__":
    main()
