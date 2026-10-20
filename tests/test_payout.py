"""Payout decisions: the engine must reproduce every golden payout in claims.json to the cent."""

from __future__ import annotations

import pytest

from app.data.loader import load_synthetic
from app.models.domain import EstimateLine
from app.rules.payout import calculate_payout

DATA = load_synthetic()


def golden_payout(s):
    g = s.golden
    for key in ("payout", "payout_if_confirmed", "proposed_payout"):
        block = g.get(key)
        if isinstance(block, dict) and "payout" in block:
            return block
    return None


CASES = [s for s in DATA.scenarios.values() if s.estimate and golden_payout(s)]


def run(lines, customer_id, excluded=None):
    return calculate_payout(lines, policy=DATA.customer_policy(customer_id), book=DATA.policy_book,
                            prices=DATA.prices, tolerance=DATA.prices.tolerance, excluded_codes=excluded)


def test_there_are_golden_payout_cases():
    assert {s.scenario_id for s in CASES} >= {"S01", "S02", "S10", "S14", "S16", "S18", "S19"}


@pytest.mark.parametrize("scenario", CASES, ids=lambda s: s.scenario_id)
def test_golden_payout(scenario):
    expected = golden_payout(scenario)
    result = run(scenario.estimate.lines, scenario.customer_id).recommendation
    assert result.payout == pytest.approx(expected["payout"], abs=0.005)
    if "eligible" in expected:
        assert result.eligible == pytest.approx(expected["eligible"], abs=0.005)
    if "lines" in expected:
        by_code = {l.code: l for l in result.lines}
        for gl in expected["lines"]:
            assert by_code[gl["code"]].covered == pytest.approx(gl["covered"], abs=0.005), gl["code"]
            assert by_code[gl["code"]].depreciation == pytest.approx(gl["depreciation"], abs=0.005), gl["code"]


def line(code, qty, unit, age=None):
    return EstimateLine(code=code, description=code, qty=qty, unit_price=unit, total=qty * unit, age_years=age)


def test_overpriced_line_is_trimmed_to_benchmark():
    # ROOF-STRUCT-REPAIR p75 = 230 -> cap 253/m2
    r = run([line("ROOF-STRUCT-REPAIR", 10, 340)], "CUST-08").recommendation
    assert r.lines[0].validated == 2530.0
    assert r.payout == 2430.0


def test_source_repair_is_never_paid():
    r = run([line("PLB-PIPE-REPAIR", 1, 200)], "CUST-01").recommendation
    assert r.lines[0].covered == 0 and r.payout == 0


def test_payout_never_negative():
    r = run([line("WALL-PAINT", 2, 15)], "CUST-04").recommendation  # 30 < deductible 500
    assert r.payout == 0


def test_depreciation_respects_new_value_period_and_cap():
    young = run([line("CONT-LAPTOP", 1, 1000, age=1)], "CUST-02").recommendation  # within new-value year
    old = run([line("CONT-LAPTOP", 1, 1000, age=20)], "CUST-02").recommendation   # capped at 70%
    assert young.lines[0].depreciation == 0
    assert old.lines[0].depreciation == 700


def test_unknown_age_on_depreciable_item_warns():
    res = run([line("FLOOR-WOOD-REPL", 10, 100)], "CUST-01")
    assert any(w.code == "ITEM_AGE_UNKNOWN" for w in res.warnings)


def test_sublimit_caps_tree_removal():
    r = run([line("TREE-REMOVAL", 1, 1150)], "CUST-08").recommendation  # within benchmark cap 1210
    assert "SL-TREE" in r.caps_applied
    assert r.eligible == 1000


def test_coverage_exclusion_zeroes_line():
    r = run([line("CEIL-PAINT", 10, 18)], "CUST-02", excluded={"CEIL-PAINT": "C-1.3"}).recommendation
    assert r.payout == 0 and r.lines[0].reason == "C-1.3 excluded"


def test_glass_deductible_applies_only_to_glass_only_claims():
    glass = run([line("GLASS-DG-REPL", 1, 200)], "CUST-08").recommendation
    mixed = run([line("GLASS-DG-REPL", 1, 200), line("WALL-PAINT", 10, 15)], "CUST-08").recommendation
    assert glass.deductible == 0 and mixed.deductible == 100


def test_every_number_has_a_rule_trail():
    res = run([line("ROOF-TILE-REPL", 6, 82, age=18)], "CUST-01")
    ids = [e.rule_id for e in res.evaluations]
    assert ids[:2] == ["PAY-BENCH-01", "PAY-DEPR-01"]
    assert ids[-2:] == ["PAY-CAP-01", "PAY-DEDUCT-01"]
    assert all(e.rule_source for e in res.evaluations)
