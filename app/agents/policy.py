"""Policy agent (README 8.2). Sources: policy wording, policy tables, explicit config - nothing else.

1. Sonnet reads the product's clause wording and selects relevant clause ids (ids only, no decisions).
2. The selection is unioned with the mandatory peril->clause matrix, so no exclusion is ever skipped.
3. A registry of clause rules (one function per clause, each citing it) turns every selected clause into
   a decision now (e.g. no flood extension) or a condition over Damage fact keys, resolved at the join.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.jev.client import Jev, JevCall
from app.jev.question_sets import POLICY_V1, policy_questions
from app.llm.claude import ClaudeClient, ModelCall
from app.models.assessment import ClauseCondition, ClauseSelection, FactCondition, PolicyFinding
from app.models.common import AgentOutput, Confidence, EvidenceRef, Warning
from app.models.domain import Estimate, Policy, PolicyBook, PriceBook
from app.models.fnol import FnolExtraction
from app.store.projections import EvidenceItem

AGENT = "policy_agent"
VERSION = "policy_v1"
PROMPT_VERSION = "clause_select_v1"
BAND = [0.25, 0.75]
TENANT_BURGLARY_CODES = {"DOOR-FRAME-REPAIR", "LOCK-REPL", "WINDOW-FRAME-REPL"}

SYSTEM = """You help a claims handler find the clauses of a home insurance policy that are relevant to a loss.
You get the policy wording (clause id, title, text) and structured facts about the loss.
Return the ids of every clause that could affect cover, exclusions, conditions or the payout for this loss.
Return ids exactly as given. Do not decide whether the claim is covered."""


@dataclass
class Ctx:
    peril: str | None
    policy: Policy
    extensions: list[str]
    product_code: str
    estimate: Estimate | None
    prices: PriceBook
    loss_date: date | None
    storm_days: set[str]
    extraction: FnolExtraction | None
    unoccupied: float | None
    lines: dict[str, Any] = field(default_factory=dict)

    def codes(self, pred: Callable[[str], bool]) -> list[str]:
        return [l.code for l in (self.estimate.lines if self.estimate else []) if pred(l.code)]

    def item(self, code: str):
        return self.prices.items[code]


def _c(cid: str, kind: str, status: str, reason: str, **kw: Any) -> ClauseCondition:
    return ClauseCondition(clause_id=cid, kind=kind, status=status, reason=reason, **kw)


def _band(key: str) -> FactCondition:
    return FactCondition(fact_key=key, op="in_band", value=BAND)


def rule(cid: str, x: Ctx) -> ClauseCondition:
    p = x.peril
    water = p in ("water_burst_or_leak", "flood_surface_water")
    match cid:
        case "C-1.1":
            return _c(cid, "cover", "covered", "Policy active on loss date and loss at insured address (checked at registration)")
        case "C-1.2":
            insured = ", ".join(k for k, v in x.policy.sum_insured.items() if v > 0)
            return _c(cid, "cover", "covered", f"Policy insures: {insured}")
        case "C-1.3":
            if x.product_code != "INBOEDEL-HUUR":
                return _c(cid, "exclusion", "not_applicable", "Not a tenant policy")
            allowed = TENANT_BURGLARY_CODES if p == "theft_burglary" else set()
            lines = x.codes(lambda c: x.item(c).object == "building" and c not in allowed)
            if not lines:
                return _c(cid, "exclusion", "not_applicable", "No building lines claimed")
            return _c(cid, "exclusion", "excluded", "Tenant policy: the rented building itself is not insured",
                      scope="lines", line_codes=lines)
        case "C-2.1":
            if p != "water_burst_or_leak":
                return _c(cid, "cover", "not_applicable", f"Peril is {p}")
            return _c(cid, "cover", "covered", "Escape of water from installations is an insured peril (see C-2.4)")
        case "C-2.2":
            lines = x.codes(lambda c: c == "LEAK-DETECT")
            if p != "water_burst_or_leak" or not lines:
                return _c(cid, "cover", "not_applicable", "No leak detection claimed")
            return _c(cid, "cover", "covered", "Leak detection payable when C-2.1 applies", scope="lines", line_codes=lines)
        case "C-2.3":
            lines = x.codes(lambda c: x.item(c).source_repair)
            if not lines:
                return _c(cid, "exclusion", "not_applicable", "No repair of the source claimed")
            return _c(cid, "exclusion", "excluded", "Repair of the pipe/hose/appliance itself is not covered",
                      scope="lines", line_codes=lines)
        case "C-2.4":
            if not water:
                return _c(cid, "exclusion", "not_applicable", f"Peril is {p}")
            return _c(cid, "exclusion", "conditional", "Gradual damage, mould and lack of maintenance are excluded",
                      exclude_if=[FactCondition(fact_key="sudden_vs_gradual", op="==", value="gradual_long_term"),
                                  FactCondition(fact_key="long_term_moisture_signs", op=">=", value=BAND[1])],
                      unresolved_if=[FactCondition(fact_key="sudden_vs_gradual", op="==", value="unclear_cannot_tell")])
        case "C-2.5":
            if p != "flood_surface_water":
                return _c(cid, "exclusion", "not_applicable", f"Peril is {p}")
            if "flood" in x.extensions:
                return _c(cid, "exclusion", "not_applicable", "Policy has the Flood extension (C-2.6)")
            return _c(cid, "exclusion", "excluded", "Flooding from outside is excluded; no Flood extension")
        case "C-2.6":
            if p != "flood_surface_water" or "flood" not in x.extensions:
                return _c(cid, "cover", "not_applicable", "Flood extension not relevant")
            return _c(cid, "cover", "covered", "Flood extension covers flooding from outside")
        case "C-3.1":
            if p != "storm_wind_hail":
                return _c(cid, "cover", "not_applicable", f"Peril is {p}")
            if x.loss_date and x.loss_date.isoformat() in x.storm_days:
                return _c(cid, "cover", "covered", f"Storm recorded on {x.loss_date} (config:storm_days.yaml)")
            return _c(cid, "cover", "unresolved", f"No storm recorded on loss date {x.loss_date}")
        case "C-3.2":
            if p != "storm_wind_hail":
                return _c(cid, "exclusion", "not_applicable", f"Peril is {p}")
            return _c(cid, "exclusion", "conditional", "Storm damage mainly caused by poor roof maintenance is excluded",
                      exclude_if=[FactCondition(fact_key="roof_maintenance_poor", op=">=", value=BAND[1]),
                                  FactCondition(fact_key="long_term_moisture_signs", op=">=", value=BAND[1])],
                      unresolved_if=[_band("roof_maintenance_poor")])
        case "C-3.3":
            lines = x.codes(lambda c: c == "TREE-REMOVAL")
            if not lines:
                return _c(cid, "cover", "not_applicable", "No tree removal claimed")
            return _c(cid, "cover", "conditional", "Tree removal only when the tree damaged the building",
                      scope="lines", line_codes=lines,
                      exclude_if=[FactCondition(fact_key="building_damage_present", op="<", value=BAND[0])],
                      unresolved_if=[_band("building_damage_present")])
        case "C-4.1":
            if p != "fire_smoke":
                return _c(cid, "cover", "not_applicable", f"Peril is {p}")
            return _c(cid, "cover", "covered", "Fire, smoke and soot are insured (see C-4.2)")
        case "C-4.2":
            if p != "fire_smoke":
                return _c(cid, "exclusion", "not_applicable", f"Peril is {p}")
            return _c(cid, "exclusion", "conditional", "Scorching or melting without fire is excluded",
                      exclude_if=[FactCondition(fact_key="open_fire_evident", op="<", value=BAND[0])],
                      unresolved_if=[FactCondition(fact_key="open_fire_evident", op="in_band", value=[0.25, 0.5])])
        case "C-5.1":
            if p != "theft_burglary":
                return _c(cid, "cover", "not_applicable", f"Peril is {p}")
            theft_lines = x.codes(lambda c: x.item(c).object == "contents")
            if theft_lines and not (x.extraction and x.extraction.police_report_ref):
                return _c(cid, "cover", "excluded", "Theft must be reported to the police; no report reference given",
                          scope="lines", line_codes=theft_lines)
            return _c(cid, "cover", "conditional", "Burglary requires visible signs of forced entry",
                      exclude_if=[FactCondition(fact_key="forced_entry_visible", op="<", value=BAND[0])],
                      unresolved_if=[_band("forced_entry_visible")])
        case "C-5.2":
            lines = x.codes(lambda c: c in TENANT_BURGLARY_CODES)
            if x.product_code != "INBOEDEL-HUUR" or p != "theft_burglary" or not lines:
                return _c(cid, "cover", "not_applicable", "Not a tenant burglary-damage case")
            return _c(cid, "cover", "covered", "Tenants are covered for burglary damage to doors, frames and locks",
                      scope="lines", line_codes=lines)
        case "C-5.3":
            lines = x.codes(lambda c: x.item(c).category == "electronics")
            if p != "theft_burglary" or not lines:
                return _c(cid, "condition", "not_applicable", "No stolen electronics")
            return _c(cid, "condition", "covered", "Electronics theft limited per event (SL-ELECTRONICS-THEFT)",
                      scope="lines", line_codes=lines)
        case "C-6.1":
            lines = x.codes(lambda c: x.item(c).category == "glass")
            if not lines:
                return _c(cid, "cover", "not_applicable", "No glass claimed")
            if "glass" in x.extensions:
                return _c(cid, "cover", "covered", "Glass extension: breakage covered whatever the cause",
                          scope="lines", line_codes=lines)
            return _c(cid, "cover", "excluded", "Policy has no Glass extension", scope="lines", line_codes=lines)
        case "C-8.1":
            if p not in ("water_burst_or_leak", "theft_burglary") or x.unoccupied is None:
                return _c(cid, "exclusion", "not_applicable", "Vacancy not relevant for this peril")
            if x.unoccupied >= BAND[1]:
                return _c(cid, "exclusion", "excluded", f"Home unoccupied > 60 days (Jev p={x.unoccupied:.2f})")
            if x.unoccupied > BAND[0]:
                return _c(cid, "exclusion", "unresolved", f"Unclear whether the home was unoccupied (Jev p={x.unoccupied:.2f})")
            return _c(cid, "exclusion", "not_applicable", f"Home was occupied (Jev p={x.unoccupied:.2f})")
        case "C-8.2":
            lines = x.codes(lambda c: c == "TEMP-COVER")
            if not lines:
                return _c(cid, "cover", "not_applicable", "No emergency measures claimed")
            return _c(cid, "cover", "covered", "Emergency measures payable when the main damage is covered",
                      scope="lines", line_codes=lines)
        case "C-9.1" | "C-9.2":
            return _c(cid, "condition", "covered", "Applied in the payout calculation")
    return _c(cid, "condition", "unresolved", "No rule implemented for this clause - needs a human")


@dataclass(frozen=True)
class PolicyResult:
    output: AgentOutput[PolicyFinding]
    selection_call: ModelCall[ClauseSelection] | None
    jev_call: JevCall | None
    questions: dict[str, dict]


def _facts_block(peril: str | None, x: FnolExtraction | None, estimate: Estimate | None) -> str:
    facts = {"peril": peril}
    if x:
        for name in ("what_happened", "source", "location", "police_report_ref", "fire_brigade_report_ref"):
            v = getattr(x, name)
            facts[name] = v.value if v else None
        facts["theft_reported"] = x.theft_reported.value if x.theft_reported else None
    facts["estimate_lines"] = [f"{l.code}: {l.description}" for l in (estimate.lines if estimate else [])]
    return "\n".join(f"{k}: {v}" for k, v in facts.items())


def assess(
    *, claude: ClaudeClient, jev: Jev, claim_id: str, book: PolicyBook, policy: Policy, prices: PriceBook,
    peril: str | None, extraction: FnolExtraction | None, estimate: Estimate | None, loss_date: date | None,
    texts: list[EvidenceItem], storm_days: set[str], peril_clauses: dict[str, Any],
) -> PolicyResult:
    product = book.products[policy.product]
    warnings: list[Warning] = []

    wording = "\n\n".join(f"[{c}] {book.clauses[c].title['en']}: {book.clauses[c].text['en']}" for c in product.clauses)
    selection_call = claude.structured(
        system=SYSTEM,
        content=[{"type": "text", "text": f"Policy wording:\n\n{wording}\n\nLoss facts:\n{_facts_block(peril, extraction, estimate)}"}],
        output_model=ClauseSelection, prompt_version=PROMPT_VERSION, effort="low")
    selected = set()
    for cid in selection_call.output.clause_ids:
        if cid in product.clauses:
            selected.add(cid)
        else:
            warnings.append(Warning(code="CLAUSE_ID_UNKNOWN", severity="warning",
                                    message=f"Sonnet selected '{cid}', which is not in product {policy.product}; ignored"))
    mandatory = {c for c in peril_clauses["always"] + peril_clauses["perils"].get(peril or "", []) if c in product.clauses}
    for cid in sorted(mandatory - selected):
        warnings.append(Warning(code="CLAUSE_ADDED_BY_MATRIX", severity="info",
                                message=f"{cid} not selected by Sonnet but required for peril {peril}; evaluated anyway"))

    questions = policy_questions()
    story = "\n\n".join(t.text or "" for t in texts)
    jev_call = jev.ask({"messages": story}, questions, question_set_version=POLICY_V1)
    unoccupied = jev_call.answers["home_unoccupied_over_60_days"].noul

    ctx = Ctx(peril=peril, policy=policy, extensions=product.extensions, product_code=policy.product, estimate=estimate,
              prices=prices, loss_date=loss_date, storm_days=storm_days, extraction=extraction, unoccupied=unoccupied)
    clauses = []
    for cid in sorted(selected | mandatory, key=lambda c: [int(n) for n in c[2:].split(".")]):
        cond = rule(cid, ctx)
        cond.selected_by = [s for s, hit in (("sonnet", cid in selected), ("peril_matrix", cid in mandatory)) if hit]
        clauses.append(cond)

    peril_covered = (peril in product.perils) or (peril == "accidental_damage" and "glass" in product.extensions)
    finding = PolicyFinding(policy_id=policy.policy_id, product=policy.product, peril=peril,
                            peril_covered=peril_covered if peril else None, clauses=clauses,
                            deductible=policy.deductible, sum_insured=policy.sum_insured)
    if not peril_covered:
        warnings.append(Warning(code="PERIL_NOT_IN_PRODUCT", severity="critical",
                                message=f"{peril} is not an insured peril under {policy.product}"))
    decided = [c for c in clauses if c.status in ("covered", "excluded", "not_applicable")]
    output = AgentOutput[PolicyFinding](
        agent=AGENT, agent_version=VERSION, claim_id=claim_id, finding=finding,
        confidence=Confidence(value=1.0, source="rule", basis="clause rules over policy tables"),
        evidence=[EvidenceRef(evidence_id=c.clause_id, kind="policy_clause") for c in clauses],
        reasoning="; ".join(f"{c.clause_id}={c.status}: {c.reason}" for c in clauses),
        summary=(f"{len(clauses)} clauses evaluated for {peril} under {policy.product}: {len(decided)} decided now, "
                 f"{len(clauses) - len(decided)} depend on damage facts or need review."),
        warnings=warnings,
    )
    return PolicyResult(output=output, selection_call=selection_call, jev_call=jev_call, questions=questions)
