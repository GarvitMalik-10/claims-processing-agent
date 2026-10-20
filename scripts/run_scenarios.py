"""Play synthetic scenarios through the claim graph with live models and compare to golden labels.

Usage:  .venv\\Scripts\\python.exe -m scripts.run_scenarios [S01 S14 ...] [--record]
Writes to var/eval (separate from the demo database). --record saves model fixtures to tests/fixtures.
If a scenario stops at an info request and has a scripted `followup`, the answer is sent and the
claim continues. Reports FNOL outcome, peril, image-claim consistency and risk band vs golden.
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor

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


def finding(store, cid, agent):
    e = proj.latest(store, cid, EventType.FINDING_CREATED, agent=agent)
    return e.payload if e else None


def run_one(svc: ClaimService, s) -> dict:
    deps, data = svc.deps, svc.deps.data
    t0 = time.time()
    cid = svc.open_claim(s.customer_id)
    for m in s.messages:
        svc.add_text(cid, m["text"], sent_at=s.reported_at)
    for img in s.images:
        svc.add_image(cid, data.image_path(img).read_bytes(), filename=img, sent_at=s.reported_at,
                      exif_override=(s.exif_override or {}).get(img))
    if s.estimate:
        svc.add_estimate(cid, s.estimate, sent_at=s.reported_at)
    status = svc.process(cid)
    fnol = ("incident_only" if status["stage"] == "incident_only" else "info_request" if status["waiting"]
            else "registered" if status["stage"] in ("assessment", "join") else f"review{status['route_reasons']}")
    if status["waiting"] and s.followup:
        svc.add_text(cid, s.followup["text"])
        status = svc.process(cid)

    dmg, pol, rsk = (finding(deps.store, cid, a) for a in ("damage_agent", "policy_agent", "risk_agent"))
    peril = proj.jev_answers(deps.store, cid, FNOL_V1).get("peril", {}).get("answer", {}).get("choice")
    return {"s": s, "cid": cid, "secs": time.time() - t0, "fnol": fnol, "status": status, "peril": peril,
            "damage": dmg, "policy": pol, "risk": rsk,
            "errors": [e.payload for e in deps.store.events(cid, {EventType.SYSTEM_ERROR})]}


def isolated_service(run_dir, sid: str, record: bool) -> ClaimService:
    """Scenarios are independent by design: each gets its own claim file, so one scenario's photos
    can never show up as another's duplicates (S13 and S14 share a photo on purpose)."""
    settings = Settings(data_dir=run_dir / sid)
    deps = build_deps(settings, fixture_mode="record" if record else "off")
    return ClaimService(deps, sqlite_checkpointer(str(settings.checkpoint_db)))


def main(argv: list[str]) -> int:
    record = "--record" in argv
    ids = [a for a in argv if not a.startswith("--")]
    run_dir = ROOT / "var" / "eval" / time.strftime("run-%Y%m%d-%H%M%S")
    data = build_deps(Settings(data_dir=run_dir / "_meta")).data
    scenarios = [data.scenarios[i] for i in ids] if ids else list(data.scenarios.values())
    print(f"run dir: {run_dir}")

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda s: run_one(isolated_service(run_dir, s.scenario_id, record), s), scenarios))

    score = {"fnol": 0, "peril": 0, "consistency": [0, 0], "risk": [0, 0]}
    for r in results:
        s, g = r["s"], r["s"].golden
        exp_fnol = expected_fnol(g)
        score["fnol"] += r["fnol"] == exp_fnol
        score["peril"] += r["peril"] == g.get("peril")
        print(f"\n=== {s.scenario_id} {s.title}  [{r['cid']}, {r['secs']:.0f}s]")
        print(f"  FNOL      expected {exp_fnol:<13} actual {r['fnol']}")
        print(f"  peril     expected {g.get('peril')} actual {r['peril']}")
        if r["damage"]:
            f = r["damage"]["finding"]
            exp = g.get("image_claim_consistency")
            score["consistency"][0] += f["consistency"] == exp
            score["consistency"][1] += 1
            fails = [f"{c['check']}={c['result']}" for c in f["checks"] if c["result"] in ("fail", "unresolved")]
            print(f"  damage    expected {exp:<21} actual {f['consistency']:<21} severity {f['severity']}")
            print(f"            facts {f['facts']}")
            if fails:
                print(f"            not passed: {fails}")
            for ev, o in f["images"].items():
                print(f"            {ev}: room={o['room_type']} quality={o['image_quality']} types={o['damage_types']}")
        if r["risk"]:
            f = r["risk"]["finding"]
            score["risk"][0] += f["band"] == g.get("risk_band")
            score["risk"][1] += 1
            top = sorted(f["signals"], key=lambda x: -x["contribution"])[:4]
            print(f"  risk      expected {g.get('risk_band'):<6} actual {f['band']:<6} score {f['score']} flags {f['hard_flags']}")
            print(f"            {[(x['signal'], x['contribution']) for x in top if x['contribution'] > 0]}")
        if r["policy"]:
            f = r["policy"]["finding"]
            interesting = [f"{c['clause_id']}={c['status']}" for c in f["clauses"] if c["status"] != "not_applicable"]
            print(f"  policy    peril_covered={f['peril_covered']} {interesting}")
        for e in r["errors"]:
            print(f"  !! {e['node']}: {e['error_type']}: {e['message'][:300]}")

    n = len(results)
    print(f"\nFNOL {score['fnol']}/{n}  peril {score['peril']}/{n}  "
          f"consistency {score['consistency'][0]}/{score['consistency'][1]}  risk band {score['risk'][0]}/{score['risk'][1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
