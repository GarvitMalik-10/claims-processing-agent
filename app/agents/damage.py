"""Damage Evidence agent (README 8.1): vision extraction -> Jev fact battery -> consistency rules ->
per-line price and visibility assessment. Reads the damage view only; writes structured findings."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.agents import vision
from app.jev.client import Jev, JevCall
from app.jev.question_sets import DAMAGE_V1, damage_questions
from app.llm.claude import ClaudeClient, ModelCall
from app.models.assessment import DamageFinding, ImageObservation, LineAssessment
from app.models.common import AgentOutput, Confidence, EvidenceRef, Warning
from app.models.domain import Estimate, PriceBook
from app.rules import consistency
from app.store.blobs import LocalBlobStore
from app.store.projections import EvidenceItem

AGENT = "damage_agent"
VERSION = "damage_v1"
FACT_NOULS = ("photo_supports_story", "long_term_moisture_signs", "open_fire_evident", "roof_maintenance_poor",
              "building_damage_present", "forced_entry_visible")


@dataclass(frozen=True)
class DamageResult:
    output: AgentOutput[DamageFinding]
    vision_calls: dict[str, ModelCall[ImageObservation]]
    jev_call: JevCall | None
    questions: dict[str, dict]


def _line_assessments(estimate: Estimate | None, prices: PriceBook, tolerance: float,
                      item_nouls: dict[str, tuple[str, float]], exempt: set[str]) -> list[LineAssessment]:
    out = []
    for line in (estimate.lines if estimate else []):
        item = prices.items[line.code]
        cap = item.p75 * (1 + tolerance)
        over = (line.unit_price - cap) / cap if line.unit_price > cap else 0.0
        status = "above_range" if over > 0 else ("below_range" if line.unit_price < item.p25 else "within_range")
        if line.code in item_nouls:
            p = item_nouls[line.code][1]
            vis = "visible" if p >= 0.75 else "not_visible" if p <= 0.25 else "unresolved"
        else:
            p, vis = None, "not_applicable"
        out.append(LineAssessment(code=line.code, description=line.description, price_status=status,
                                  over_benchmark_pct=round(over * 100, 1), visible=vis, visible_noul=p))
    return out


def _summary(f: DamageFinding) -> str:
    failed = [c.check for c in f.checks if c.result == "fail"]
    sev = (f.severity or "unknown").replace("_", " ")
    s = f"Photos assessed as {f.consistency.replace('_', ' ')} with the claim; severity {sev}."
    return s + (f" Failed checks: {', '.join(failed)}." if failed else "")


def assess(
    *, claude: ClaudeClient, jev: Jev, blobs: LocalBlobStore, claim_id: str, texts: list[EvidenceItem],
    images: list[EvidenceItem], estimate: Estimate | None, peril: str | None, location: str | None,
    prices: PriceBook, tolerance: float, cfg: dict[str, Any],
) -> DamageResult:
    # 1. Vision, one call per photo, in parallel
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {img.evidence_id: pool.submit(vision.observe, claude, blobs.get(img.normalized_blob))
                   for img in images}
        vision_calls = {ev: f.result() for ev, f in futures.items()}
    observations = {ev: call.output for ev, call in vision_calls.items()}

    # 2. Jev battery: all questions in one call against story + photos + estimate items
    exempt = set(cfg["visibility_exempt_categories"])
    contents_exempt = peril in cfg.get("visibility_exempt_contents_for_perils", [])
    eligible = [l for l in (estimate.lines if estimate else [])
                if prices.items[l.code].category not in exempt and not prices.items[l.code].source_repair
                and not (contents_exempt and prices.items[l.code].object == "contents")]
    item_keys = {f"item_{i}": l for i, l in enumerate(eligible, start=1)}
    questions = damage_questions(peril, len(images), {k: prices.items[l.code].label["en"] for k, l in item_keys.items()})
    jev_call: JevCall | None = None
    facts: dict[str, Any] = {}
    item_nouls: dict[str, tuple[str, float]] = {}
    if images:
        state: dict[str, Any] = {"story": "\n\n".join(t.text or "" for t in texts)}
        for i, img in enumerate(images, start=1):
            state[f"photo_{i}"] = Path(blobs.path(img.normalized_blob))
        jev_call = jev.ask(state, questions, question_set_version=DAMAGE_V1)
        a = jev_call.answers
        for key in FACT_NOULS:
            if key in a:
                facts[key] = round(a[key].noul, 4)
        for key in ("severity", "sudden_vs_gradual"):
            if key in a:
                facts[key] = a[key].choice
                facts[f"{key}_confidence"] = round(a[key].confidence, 4)
        for key, line in item_keys.items():
            item_nouls[line.code] = (prices.items[line.code].label["en"], a[key].noul)

    # 3. Consistency rules
    jev_view = {k: v for k, v in facts.items() if isinstance(v, float)}
    if "sudden_vs_gradual" in facts:
        jev_view["sudden_vs_gradual"] = (facts["sudden_vs_gradual"], facts["sudden_vs_gradual_confidence"])
    result, checks = consistency.evaluate(images=observations, peril=peril, location=location, jev=jev_view,
                                          item_nouls=item_nouls, cfg=cfg)

    finding = DamageFinding(
        peril=peril, severity=facts.get("severity"), severity_confidence=facts.get("severity_confidence"),
        facts={k: v for k, v in facts.items() if not k.endswith("_confidence")},
        consistency=result, checks=checks,
        lines=_line_assessments(estimate, prices, tolerance, item_nouls, exempt), images=observations,
    )
    measured = [facts[k] for k in ("sudden_vs_gradual_confidence",) if k in facts]
    if "photo_supports_story" in facts:
        measured.append(abs(2 * facts["photo_supports_story"] - 1))
    warnings = [Warning(code=f"CHECK_FAILED_{c.check.upper().replace(':', '_')}", severity=c.severity
                        if c.severity == "critical" else "warning", message=c.detail)
                for c in checks if c.result == "fail"]
    for ev, obs in observations.items():
        if obs.visible_text or obs.regional_indicators:
            warnings.append(Warning(code="REGIONAL_INDICATORS", severity="info",
                                    message=f"{ev}: {'; '.join(obs.visible_text + obs.regional_indicators)}"))
    output = AgentOutput[DamageFinding](
        agent=AGENT, agent_version=VERSION, claim_id=claim_id, finding=finding,
        confidence=(Confidence(value=round(min(measured), 4), source="measured",
                               basis="min(jev sudden_vs_gradual confidence, |2p-1| photo_supports_story)")
                    if measured else Confidence(value=0.0, source="rule", basis="no photos to assess")),
        evidence=[EvidenceRef(evidence_id=i.evidence_id, kind="image") for i in images]
                 + [EvidenceRef(evidence_id=t.evidence_id, kind="text") for t in texts],
        reasoning="; ".join(f"{c.check}={c.result} ({c.detail})" for c in checks),
        summary=_summary(finding), warnings=warnings,
    )
    return DamageResult(output=output, vision_calls=vision_calls, jev_call=jev_call, questions=questions)
