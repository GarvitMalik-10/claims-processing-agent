"""Play synthetic scenarios through the FNOL graph with live models and compare to golden labels.

Usage:  .venv\\Scripts\\python.exe -m scripts.run_scenarios [S01 S14 ...] [--record]
Writes to var/eval (separate from the demo database). --record saves model fixtures to tests/fixtures.
FNOL-stage expectation per scenario: incident_only | info_request (waiting) | registered (assessment).
"""

from __future__ import annotations

import sys
import time

from app.graph.deps import build_deps
from app.jev.question_sets import FNOL_V1
from app.models.events import EventType
from app.service import ClaimService, sqlite_checkpointer
from app.settings import ROOT, Settings
from app.store import projections as proj


def expected_fnol(golden: dict) -> str:
    if golden.get("claim_vs_incident") == "incident_only":
        return "incident_only"
    if golden.get("completeness") == "incomplete":
        return "info_request"
    return "registered"


def actual_fnol(status: dict) -> str:
    if status["stage"] == "incident_only":
        return "incident_only"
    if status["waiting"]:
        return "info_request"
    if status["stage"] == "assessment":
        return "registered"
    return f"review({','.join(status['route_reasons'])})"


def main(argv: list[str]) -> int:
    record = "--record" in argv
    ids = [a for a in argv if not a.startswith("--")]
    settings = Settings(data_dir=ROOT / "var" / "eval")
    deps = build_deps(settings, fixture_mode="record" if record else "off")
    svc = ClaimService(deps, sqlite_checkpointer(str(settings.checkpoint_db)))
    data = deps.data
    scenarios = [data.scenarios[i] for i in ids] if ids else list(data.scenarios.values())

    rows = []
    for s in scenarios:
        t0 = time.time()
        cid = svc.open_claim(s.customer_id)
        for m in s.messages:
            svc.add_text(cid, m["text"], sent_at=s.reported_at)
        for img in s.images:
            override = (s.exif_override or {}).get(img)
            svc.add_image(cid, data.image_path(img).read_bytes(), filename=img, sent_at=s.reported_at,
                          exif_override=override)
        if s.estimate:
            svc.add_estimate(cid, s.estimate, sent_at=s.reported_at)
        status = svc.process(cid)
        secs = time.time() - t0

        peril = proj.jev_answers(deps.store, cid, FNOL_V1).get("peril", {})
        comp = proj.latest(deps.store, cid, EventType.FNOL_COMPLETENESS_EVALUATED)
        exp, act = expected_fnol(s.golden), actual_fnol(status)
        peril_choice = peril.get("answer", {}).get("choice")
        ok_route = exp == act
        ok_peril = peril_choice == s.golden.get("peril")
        rows.append((s.scenario_id, ok_route, ok_peril))
        print(f"\n=== {s.scenario_id} {s.title}  [{cid}, {secs:.1f}s]")
        print(f"  FNOL outcome: expected {exp:<13} actual {act:<13} {'OK' if ok_route else 'MISMATCH'}")
        print(f"  peril: expected {s.golden.get('peril')} actual {peril_choice} "
              f"(conf {peril.get('measured_confidence')}) {'OK' if ok_peril else 'MISMATCH'}")
        if comp:
            print(f"  missing: {comp.payload['missing']}")
        for msg in svc.outbound_messages(cid):
            print(f"  -> [{msg['kind']}] {msg['text']}")
        errors = deps.store.events(cid, {EventType.SYSTEM_ERROR})
        for e in errors:
            print(f"  !! {e.payload['node']}: {e.payload['error_type']}: {e.payload['message'][:200]}")

    n = len(rows)
    print(f"\nFNOL outcome {sum(r[1] for r in rows)}/{n}   peril {sum(r[2] for r in rows)}/{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
