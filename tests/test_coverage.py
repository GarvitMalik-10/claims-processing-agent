"""Coverage resolution: policy conditions x damage facts (part of the 'policy decisions' test area)."""

from __future__ import annotations

from app.models.assessment import ClauseCondition, FactCondition, PolicyFinding
from app.rules.coverage import resolve, resolve_clause

NON_ADVERSE = {"C-2.3"}


def finding(*clauses, peril_covered=True):
    return PolicyFinding(policy_id="P", product="WONEN-BASIS", peril="water_burst_or_leak", peril_covered=peril_covered,
                         clauses=list(clauses), deductible={"default": 100}, sum_insured={"building": 1})


GRADUAL = ClauseCondition(
    clause_id="C-2.4", kind="exclusion", status="conditional", reason="r",
    exclude_if=[FactCondition(fact_key="sudden_vs_gradual", op="==", value="gradual_long_term"),
                FactCondition(fact_key="long_term_moisture_signs", op=">=", value=0.75)],
    unresolved_if=[FactCondition(fact_key="sudden_vs_gradual", op="==", value="unclear_cannot_tell")])
COVER = ClauseCondition(clause_id="C-2.1", kind="cover", status="covered", reason="r")


def test_gradual_damage_excludes_claim():
    r = resolve(finding(COVER, GRADUAL), {"sudden_vs_gradual": "gradual_long_term", "long_term_moisture_signs": 0.9},
                ["CEIL-PAINT"], non_adverse_line_clauses=NON_ADVERSE)
    assert r.decision.status == "not_covered" and r.adverse and "EXCLUDED:C-2.4" in r.reasons


def test_sudden_damage_is_covered_and_exclusion_not_applicable():
    r = resolve(finding(COVER, GRADUAL), {"sudden_vs_gradual": "sudden_recent_event", "long_term_moisture_signs": 0.4},
                ["CEIL-PAINT"], non_adverse_line_clauses=NON_ADVERSE)
    assert r.decision.status == "covered"
    assert {c.clause_id: c.status for c in r.decision.clauses}["C-2.4"] == "not_applicable"


def test_unclear_timing_is_unresolved_not_guessed():
    r = resolve(finding(COVER, GRADUAL), {"sudden_vs_gradual": "unclear_cannot_tell", "long_term_moisture_signs": 0.4},
                ["CEIL-PAINT"], non_adverse_line_clauses=NON_ADVERSE)
    assert r.decision.status == "unresolved" and not r.adverse


def test_missing_fact_is_unresolved():
    status, _ = resolve_clause(GRADUAL, {})
    assert status == "unresolved"


def test_source_repair_exclusion_is_not_adverse():  # S02: hose itself is never paid
    src = ClauseCondition(clause_id="C-2.3", kind="exclusion", status="excluded", reason="r", scope="lines",
                          line_codes=["PLB-HOSE-REPL"])
    r = resolve(finding(COVER, src), {}, ["PLB-HOSE-REPL", "CEIL-PAINT"], non_adverse_line_clauses=NON_ADVERSE)
    assert r.decision.status == "covered" and r.excluded_lines == {"PLB-HOSE-REPL": "C-2.3"}


def test_adverse_line_exclusion_makes_partial():
    glass = ClauseCondition(clause_id="C-6.1", kind="cover", status="excluded", reason="r", scope="lines",
                            line_codes=["GLASS-DG-REPL"])
    r = resolve(finding(COVER, glass), {}, ["GLASS-DG-REPL", "WALL-PAINT"], non_adverse_line_clauses=NON_ADVERSE)
    assert r.decision.status == "partially_covered" and r.adverse


def test_all_lines_excluded_is_not_covered():  # S03: tenant claims only building lines
    tenant = ClauseCondition(clause_id="C-1.3", kind="exclusion", status="excluded", reason="r", scope="lines",
                             line_codes=["CEIL-PLAST-REPAIR", "CEIL-PAINT"])
    r = resolve(finding(COVER, tenant), {}, ["CEIL-PLAST-REPAIR", "CEIL-PAINT"], non_adverse_line_clauses=NON_ADVERSE)
    assert r.decision.status == "not_covered"


def test_peril_not_insured():
    r = resolve(finding(COVER, peril_covered=False), {}, ["WALL-PAINT"], non_adverse_line_clauses=NON_ADVERSE)
    assert r.decision.status == "not_covered" and "PERIL_NOT_INSURED" in r.reasons


def test_tree_removal_needs_building_damage():
    tree = ClauseCondition(clause_id="C-3.3", kind="cover", status="conditional", reason="r", scope="lines",
                           line_codes=["TREE-REMOVAL"],
                           exclude_if=[FactCondition(fact_key="building_damage_present", op="<", value=0.25)])
    r = resolve(finding(COVER, tree), {"building_damage_present": 0.05}, ["TREE-REMOVAL", "ROOF-TILE-REPL"],
                non_adverse_line_clauses=NON_ADVERSE)
    assert r.excluded_lines == {"TREE-REMOVAL": "C-3.3"} and r.decision.status == "partially_covered"
