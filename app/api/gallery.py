"""Sample media gallery for free play (README 15.1): photos, contractor estimates and example stories.

Gallery photos are stand-ins for a customer's own photos, so at upload they get synthetic camera
metadata (taken now, at the persona's home) - labelled as synthetic in the claim file. Trick items keep
their trick: IMG-08 carries an old capture date; IMG-13 is registered on a past claim (duplicate)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.data.loader import SyntheticData
from app.models.domain import Customer

TRICKS = {
    "IMG-08": {"label": "old photo (2024 capture date)", "exif": {"DateTimeOriginal": "2024-02-11T15:42:10",
                                                                   "Make": "Samsung", "Model": "SM-A525F"}},
    "IMG-13": {"label": "already used on a past claim", "exif": None},
    "IMG-04": {"label": "taken in a museum", "exif": None},
    "IMG-20": {"label": "no damage visible", "exif": None},
}


def gallery(data: SyntheticData) -> dict[str, Any]:
    photos = []
    for image_id, o in sorted(data.observations.items()):
        photos.append({"id": image_id, "url": f"/api/gallery/images/{image_id}",
                       "caption": o.summary["en"].split(".")[0], "caption_nl": o.summary["nl"].split(".")[0],
                       "trick": TRICKS.get(image_id, {}).get("label")})
    estimates, stories = [], []
    for s in data.scenarios.values():
        if s.estimate:
            estimates.append({"id": s.scenario_id, "contractor": s.estimate.contractor, "total": s.estimate.total,
                              "lines": [l.description for l in s.estimate.lines], "title": s.title})
        stories.append({"id": s.scenario_id, "title": s.title, "customer_id": s.customer_id, "images": s.images,
                        "texts": [m["text"] for m in s.messages], "followup": (s.followup or {}).get("text")})
    return {"photos": photos, "estimates": estimates, "stories": stories}


def gallery_exif(image_id: str, customer: Customer) -> dict[str, Any]:
    trick = TRICKS.get(image_id)
    if trick and trick["exif"] is not None:
        return trick["exif"]
    return {"DateTimeOriginal": datetime.now(UTC).replace(microsecond=0, tzinfo=None).isoformat(),
            "Make": "Apple", "Model": "iPhone 15", "GPS": customer.address.geo}
