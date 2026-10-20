"""Live smoke test: one Sonnet vision call + one Jev image question on IMG-14.

Run:  .venv\\Scripts\\python.exe -m scripts.smoke_live
Costs a few cents. Verifies both API keys, Sonnet structured output, and Jev image support
(the TypeSafe-Danger-Zone-Images header must be enabled on the account).
"""

from __future__ import annotations

import sys

from pydantic import BaseModel, Field

from app.data.loader import synthetic
from app.jev.client import JevClient
from app.llm.claude import ClaudeClient, image_block
from app.settings import get_settings
from app.store.blobs import LocalBlobStore


class QuickLook(BaseModel):
    room_type: str = Field(description="exterior_roof, kitchen, bathroom, ... or unknown")
    damage_types: list[str]
    summary_en: str


def main() -> int:
    data = synthetic()
    blobs = LocalBlobStore(get_settings().blob_dir)
    path = data.image_path("IMG-14")

    print("1/2 Claude vision ...", flush=True)
    claude = ClaudeClient(blobs, default_effort="low")
    call = claude.structured(
        system="You describe property damage photos for an insurance adjuster. Only report what is visible.",
        content=[image_block(path.read_bytes()), {"type": "text", "text": "Describe the damage in this photo."}],
        output_model=QuickLook,
        prompt_version="smoke_v1",
    )
    print(f"    model={call.model} usage={call.usage}")
    print(f"    {call.output.model_dump()}")

    print("2/2 Jev image question ...", flush=True)
    jev = JevClient(blobs)
    answer = jev.ask(
        {"story": "During last night's storm the chimney fell onto our roof.", "photo_1": path},
        {"photo_supports_story": {"type": "noul", "instructions": "Does `photo_1` support `story`?"}},
        question_set_version="smoke_v1",
    )
    a = answer.answers["photo_supports_story"]
    print(f"    model={answer.model} noul={a.noul:.3f} measured_confidence={a.measured_confidence:.3f}")
    print("OK - both models reachable; raw I/O stored in", blobs.root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
