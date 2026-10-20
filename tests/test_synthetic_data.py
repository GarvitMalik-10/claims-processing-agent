"""Integrity of the synthetic data set, incl. README principle 10: no rule without a policy source."""

from __future__ import annotations

import pytest

from app.data.loader import load_synthetic


@pytest.fixture(scope="module")
def data():
    return load_synthetic()


def test_counts(data):
    assert len(data.customers) == 8
    assert len(data.scenarios) == 20
    assert len(data.observations) == 20


def test_every_image_file_exists(data):
    for image_id in data.observations:
        assert data.image_path(image_id).is_file(), image_id


def test_demo_images_carry_no_real_camera_metadata(data):
    from app.intake.evidence import read_exif

    for image_id in data.observations:
        assert read_exif(data.image_path(image_id).read_bytes()) == {}, image_id


def test_scenarios_reference_known_customers_images_and_codes(data):
    for s in data.scenarios.values():
        assert s.customer_id in data.customers
        for img in s.images:
            assert img in data.observations, (s.scenario_id, img)
        for line in (s.estimate.lines if s.estimate else []):
            assert line.code in data.prices.items, (s.scenario_id, line.code)


def test_estimate_totals_add_up(data):
    for s in data.scenarios.values():
        if s.estimate:
            assert round(sum(l.total for l in s.estimate.lines), 2) == s.estimate.total, s.scenario_id
            for l in s.estimate.lines:
                assert round(l.qty * l.unit_price, 2) == l.total, (s.scenario_id, l.code)


def test_every_customer_has_a_policy_with_known_product(data):
    for c in data.customers.values():
        policy = data.customer_policy(c.customer_id)
        assert policy.product in data.policy_book.products


def test_no_policy_rule_without_a_source(data):
    book = data.policy_book
    for product in book.products.values():
        for clause_id in product.clauses:
            assert clause_id in book.clauses, clause_id
    for row in book.sublimits:
        assert row.clause_id in book.clauses, row.row_id
    assert book.depreciation_clause_id in book.clauses
    for clause in book.clauses.values():
        assert clause.text.get("nl") and clause.text.get("en"), clause.clause_id


def test_golden_clauses_exist(data):
    for s in data.scenarios.values():
        for clause_id in s.golden.get("clauses", []):
            assert clause_id in data.policy_book.clauses, (s.scenario_id, clause_id)
