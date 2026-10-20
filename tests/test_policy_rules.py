"""Policy decisions (one of the five required test areas). Every outcome cites a clause."""

from __future__ import annotations

from datetime import date

import pytest

from app.agents import policy as pol
from app.data.loader import load_synthetic
from app.models.assessment import ClauseSelection
from app.models.domain import Estimate, EstimateLine
from app.settings import load_config
from tests.stubs import StubClaude, StubJev, extraction

DATA = load_synthetic()


def est(*codes):
    lines = [EstimateLine(code=c, description=c, qty=1, unit_price=100, total=100) for c in codes]
    return Estimate(contractor="x", date=None, lines=lines, total=100.0 * len(lines))


def ctx(customer="CUST-01", peril="water_burst_or_leak", codes=(), loss=date(2026, 10, 14), x=None, unoccupied=0.05):
    policy = DATA.customer_policy(customer)
    return pol.Ctx(peril=peril, policy=policy, extensions=DATA.policy_book.products[policy.product].extensions,
                   product_code=policy.product, estimate=est(*codes) if codes else None, prices=DATA.prices,
                   loss_date=loss, storm_days={"2026-10-14"}, extraction=x, unoccupied=unoccupied)


def test_tenant_policy_excludes_building_lines():  # S03
    c = pol.rule("C-1.3", ctx("CUST-02", codes=("CEIL-PLAST-REPAIR", "CEIL-PAINT")))
    assert c.status == "excluded" and c.line_codes == ["CEIL-PLAST-REPAIR", "CEIL-PAINT"]


def test_tenant_burglary_damage_is_covered():  # S19
    x = ctx("CUST-02", peril="theft_burglary", codes=("DOOR-FRAME-REPAIR", "LOCK-REPL", "CONT-LAPTOP"))
    assert pol.rule("C-1.3", x).status == "not_applicable"
    assert pol.rule("C-5.2", x).status == "covered"


def test_flood_excluded_without_extension_covered_with():  # S05 vs Lotte's TOP policy
    assert pol.rule("C-2.5", ctx("CUST-06", peril="flood_surface_water")).status == "excluded"
    assert pol.rule("C-2.5", ctx("CUST-05", peril="flood_surface_water")).status == "not_applicable"
    assert pol.rule("C-2.6", ctx("CUST-05", peril="flood_surface_water")).status == "covered"


def test_gradual_exclusion_is_conditional_on_damage_facts():
    c = pol.rule("C-2.4", ctx())
    assert c.status == "conditional"
    assert {f.fact_key for f in c.exclude_if} == {"sudden_vs_gradual", "long_term_moisture_signs"}


def test_storm_needs_a_recorded_storm_day():
    assert pol.rule("C-3.1", ctx(peril="storm_wind_hail")).status == "covered"
    assert pol.rule("C-3.1", ctx(peril="storm_wind_hail", loss=date(2026, 10, 1))).status == "unresolved"


def test_source_repair_excluded():
    assert pol.rule("C-2.3", ctx(codes=("PLB-HOSE-REPL", "CEIL-PAINT"))).line_codes == ["PLB-HOSE-REPL"]


def test_glass_needs_extension():  # Emma (PLUS) vs Pieter (BASIS)
    assert pol.rule("C-6.1", ctx("CUST-08", peril="accidental_damage", codes=("GLASS-DG-REPL",))).status == "covered"
    assert pol.rule("C-6.1", ctx("CUST-04", peril="accidental_damage", codes=("GLASS-DG-REPL",))).status == "excluded"


def test_theft_without_police_report_excludes_stolen_items():
    x = extraction(police_report_ref=None)
    c = pol.rule("C-5.1", ctx("CUST-02", peril="theft_burglary", codes=("CONT-LAPTOP",), x=x))
    assert c.status == "excluded" and c.line_codes == ["CONT-LAPTOP"]


def test_vacancy_exclusion_bands():
    assert pol.rule("C-8.1", ctx(unoccupied=0.9)).status == "excluded"
    assert pol.rule("C-8.1", ctx(unoccupied=0.5)).status == "unresolved"
    assert pol.rule("C-8.1", ctx(unoccupied=0.1)).status == "not_applicable"


def test_clause_without_rule_goes_to_a_human():
    assert pol.rule("C-99.9", ctx()).status == "unresolved"


def test_sonnet_selection_is_validated_and_matrix_always_added(tmp_path):
    from app.store.blobs import LocalBlobStore

    blobs = LocalBlobStore(tmp_path)
    claude = StubClaude(blobs)
    claude.push(ClauseSelection(clause_ids=["C-2.1", "C-77.1"], reasoning="r", summary="s"))
    policy = DATA.customer_policy("CUST-01")
    res = pol.assess(claude=claude, jev=StubJev(blobs), claim_id="C1", book=DATA.policy_book, policy=policy,
                     prices=DATA.prices, peril="water_burst_or_leak", extraction=extraction(), estimate=None,
                     loss_date=date(2026, 10, 16), texts=[], storm_days=set(),
                     peril_clauses=load_config("peril_clauses").data)
    ids = [c.clause_id for c in res.output.finding.clauses]
    assert "C-77.1" not in ids and "C-2.4" in ids  # unknown id dropped, gradual exclusion forced in
    codes = {w.code for w in res.output.warnings}
    assert {"CLAUSE_ID_UNKNOWN", "CLAUSE_ADDED_BY_MATRIX"} <= codes
    by_id = {c.clause_id: c for c in res.output.finding.clauses}
    assert by_id["C-2.1"].selected_by == ["sonnet", "peril_matrix"]
    assert by_id["C-2.4"].selected_by == ["peril_matrix"]


@pytest.mark.parametrize("peril,customer,covered", [
    ("water_burst_or_leak", "CUST-01", True), ("accidental_damage", "CUST-04", False),
    ("accidental_damage", "CUST-08", True), ("flood_surface_water", "CUST-06", False),
])
def test_peril_in_product(tmp_path, peril, customer, covered):
    from app.store.blobs import LocalBlobStore

    blobs = LocalBlobStore(tmp_path)
    res = pol.assess(claude=StubClaude(blobs), jev=StubJev(blobs), claim_id="C1", book=DATA.policy_book,
                     policy=DATA.customer_policy(customer), prices=DATA.prices, peril=peril, extraction=None,
                     estimate=None, loss_date=date(2026, 10, 16), texts=[], storm_days=set(),
                     peril_clauses=load_config("peril_clauses").data)
    assert res.output.finding.peril_covered is covered
