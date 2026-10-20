"""Risk agent (README 8.3): transparent weighted sum of signals (weights in config/risk_weights.yaml)
plus hard flags that force SIU. Code signals + Jev nouls; no LLM prose drives the score."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import imagehash
from PIL import Image

from app.intake.images import normalize_image_bytes
from app.jev.client import Jev, JevCall
from app.jev.question_sets import RISK_V1, risk_questions
from app.models.assessment import RiskFinding, RiskSignalValue
from app.models.common import AgentOutput, Confidence, EvidenceRef, Warning
from app.models.domain import Customer, Estimate, Policy, PriceBook
from app.store.blobs import LocalBlobStore
from app.store.projections import EvidenceItem

AGENT = "risk_agent"
VERSION = "risk_v1"


@dataclass(frozen=True)
class RiskResult:
    output: AgentOutput[RiskFinding]
    jev_call: JevCall | None
    questions: dict[str, dict]


@lru_cache(maxsize=64)
def _phash_file(path: str) -> str:
    import io

    with Image.open(io.BytesIO(normalize_image_bytes(Path(path).read_bytes()))) as img:
        return str(imagehash.phash(img))


def hamming(a: str, b: str) -> int:
    return imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b)


def _km(a: dict[str, float], b: dict[str, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def history_hashes(history: list[dict[str, Any]], root: Path) -> list[dict[str, str]]:
    out = []
    for claim in history:
        for img in claim.get("images", []):
            out.append({"claim_id": claim["claim_id"], "customer_ref": claim["customer_ref"],
                        "phash": _phash_file(str(root / img["phash_source"]))})
    return out


def assess(
    *, jev: Jev, blobs: LocalBlobStore, claim_id: str, customer: Customer, policy: Policy, loss_date: date | None,
    reported_at: datetime | None, texts: list[EvidenceItem], images: list[EvidenceItem], estimate: Estimate | None,
    prices: PriceBook, tolerance: float, past_claims: list[dict[str, Any]], known_hashes: list[dict[str, str]],
    weights_cfg: dict[str, Any], thresholds: dict[str, Any], duplicate_threshold: int,
) -> RiskResult:
    w = weights_cfg["weights"]
    signals: list[RiskSignalValue] = []
    hard_flags: list[str] = []
    warnings: list[Warning] = []

    def add(name: str, strength: float, detail: str, source: str = "rule", weight: float | None = None) -> None:
        wt = w[name] if weight is None else weight
        s = max(0.0, min(1.0, strength))
        signals.append(RiskSignalValue(signal=name, strength=round(s, 4), weight=wt, contribution=round(s * wt, 4),
                                       source=source, detail=detail))

    # EXIF timestamp / GPS
    taken = []
    for img in images:
        ts = img.exif.get("DateTimeOriginal")
        if ts:
            taken.append((img.evidence_id, datetime.fromisoformat(ts).date()))
        gps = img.exif.get("GPS")
        if gps:
            dist = _km(gps, customer.address.geo)
            add("gps_far_from_address", 1.0 if dist > weights_cfg["gps_far_km"] else 0.0,
                f"{img.evidence_id} taken {dist:.1f} km from the insured address")
    if loss_date:
        before = [ev for ev, d in taken if d < loss_date]
        if taken:
            add("exif_before_loss_date", 1.0 if before else 0.0,
                f"photo date before loss date: {before}" if before else "photo dates on/after loss date")
    if images and not taken:
        add("exif_missing", 1.0, "no camera date in any photo")

    # Duplicate photos: claim history + other claims in the claim file. Another customer's photo is a
    # hard flag; the same customer's photo on another claim is a strong (soft) double-claim signal.
    reused_same = []
    for img in images:
        for known in known_hashes:
            if known["claim_id"] == claim_id or not img.phash:
                continue
            d = hamming(img.phash, known["phash"])
            if d > duplicate_threshold:
                continue
            if known.get("customer_ref") == customer.customer_id:
                reused_same.append(f"{img.evidence_id}~{known['claim_id']}")
                warnings.append(Warning(code="PHOTO_REUSED_SAME_CUSTOMER", severity="warning",
                                        message=f"{img.evidence_id} was already sent on {known['claim_id']} (distance {d})"))
            else:
                hard_flags.append("duplicate_image")
                warnings.append(Warning(code="DUPLICATE_IMAGE", severity="critical",
                                        message=f"{img.evidence_id} matches a photo on {known['claim_id']} (distance {d})"))
    hard_flags = sorted(set(hard_flags))
    if reused_same:
        add("photo_reused_same_customer", 1.0, f"same customer's photo on another claim: {', '.join(reused_same)}")

    # Policy age, frequency, late reporting
    if loss_date:
        days = (loss_date - policy.start_date).days
        add("policy_started_lt_60_days", 1.0 if days < weights_cfg["policy_recent_days"] else 0.0,
            f"policy started {days} days before the loss")
        recent = [c for c in past_claims if c["customer_ref"] == customer.customer_id
                  and 0 <= (loss_date - date.fromisoformat(c["loss_date"])).days <= 3 * 365]
        cap = weights_cfg["max_frequency_contribution"]
        contrib = min(cap, w["claim_frequency_3y"] * len(recent))
        add("claim_frequency_3y", contrib / cap if cap else 0, f"{len(recent)} claim(s) in the last 3 years", weight=cap)
        if reported_at:
            late = (reported_at.date() - loss_date).days
            add("late_reporting_days_gt_7", 1.0 if late > 7 else 0.0, f"reported {late} day(s) after the loss")

    # Estimate vs benchmark
    if estimate:
        overs = [(l.code, (l.unit_price - prices.items[l.code].p75 * (1 + tolerance)) / (prices.items[l.code].p75 * (1 + tolerance)))
                 for l in estimate.lines]
        worst = max(overs, key=lambda t: t[1])
        add("estimate_above_benchmark", worst[1] / 0.5 if worst[1] > 0 else 0.0,
            f"largest overrun {worst[1] * 100:.0f}% on {worst[0]}" if worst[1] > 0 else "all lines within benchmark")

    # Jev: narrative signals
    questions = risk_questions(len(images))
    state: dict[str, Any] = {"messages": "\n\n".join(t.text or "" for t in texts),
                             "reported_at": reported_at.isoformat() if reported_at else "unknown"}
    for i, img in enumerate(images, start=1):
        state[f"photo_{i}"] = Path(blobs.path(img.normalized_blob))
    jev_call = jev.ask(state, questions, question_set_version=RISK_V1)
    a = jev_call.answers
    add("story_inconsistent", 1 - a["story_consistent"].noul, f"Jev story_consistent p={a['story_consistent'].noul:.2f}", "jev")
    add("timeline_implausible", 1 - a["timeline_plausible"].noul, f"Jev timeline_plausible p={a['timeline_plausible'].noul:.2f}", "jev")
    if "photo_supports_story" in a:
        add("photo_not_supporting_story", 1 - a["photo_supports_story"].noul,
            f"Jev photo_supports_story p={a['photo_supports_story'].noul:.2f}", "jev")

    score = round(min(1.0, sum(s.contribution for s in signals)), 4)
    rt = thresholds["risk"]
    band = "high" if hard_flags or score >= rt["siu_from"] else "medium" if score >= rt["human_from"] else "low"
    finding = RiskFinding(score=score, band=band, signals=signals, hard_flags=hard_flags)
    top = sorted((s for s in signals if s.contribution > 0), key=lambda s: -s.contribution)[:3]
    output = AgentOutput[RiskFinding](
        agent=AGENT, agent_version=VERSION, claim_id=claim_id, finding=finding,
        confidence=Confidence(value=1.0, source="rule", basis="weighted sum over rule and Jev signals"),
        evidence=[EvidenceRef(evidence_id=policy.policy_id, kind="document", locator="start_date")]
                 + [EvidenceRef(evidence_id=i.evidence_id, kind="image") for i in images]
                 + [EvidenceRef(evidence_id=t.evidence_id, kind="text") for t in texts],
        reasoning="; ".join(f"{s.signal}: {s.strength:.2f} x {s.weight} = {s.contribution:.3f} ({s.detail})" for s in signals),
        summary=f"Risk {score:.2f} ({band})" + (f", hard flags: {', '.join(hard_flags)}" if hard_flags else "")
                + (f"; main drivers: {', '.join(s.signal for s in top)}" if top else ""),
        warnings=warnings,
    )
    return RiskResult(output=output, jev_call=jev_call, questions=questions)
