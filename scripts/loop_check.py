"""Live two-turn check of the missing-info loop on S03 (tenant ceiling leak, no date given)."""

from __future__ import annotations

from app.graph.deps import build_deps
from app.service import ClaimService, sqlite_checkpointer
from app.settings import ROOT, Settings


def main() -> None:
    settings = Settings(data_dir=ROOT / "var" / "eval")
    deps = build_deps(settings, fixture_mode="record")
    svc = ClaimService(deps, sqlite_checkpointer(str(settings.checkpoint_db)))
    s = deps.data.scenarios["S03"]
    cid = svc.open_claim(s.customer_id)
    svc.add_text(cid, s.messages[0]["text"], sent_at=s.reported_at)
    svc.add_image(cid, deps.data.image_path("IMG-03").read_bytes(), filename="IMG-03")
    svc.add_estimate(cid, s.estimate)
    print("turn 1:", svc.process(cid))
    print("  bot:", svc.outbound_messages(cid)[-1]["text"])

    svc.add_text(cid, "It happened on Thursday the 15th. The neighbours turned their water off that night and "
                      "their plumber has fixed the shower.", sent_at="2026-10-17T10:00:00+02:00")
    print("turn 2:", svc.process(cid))
    print("  bot:", svc.outbound_messages(cid)[-1]["text"])
    print("chain intact:", deps.store.verify_chain(cid).intact, "events:", len(deps.store.events(cid)))


if __name__ == "__main__":
    main()
