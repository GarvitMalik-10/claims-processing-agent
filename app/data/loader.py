"""Load data/synthetic/*.json into typed models."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.models.domain import (
    ClaimScenario,
    Clause,
    Customer,
    DepreciationRow,
    ImageObservationRef,
    Policy,
    PolicyBook,
    PriceBook,
    PriceItem,
    Product,
    SublimitRow,
)
from app.settings import SYNTHETIC_DIR


def _read(root: Path, name: str) -> Any:
    return json.loads((root / name).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class SyntheticData:
    root: Path
    customers: dict[str, Customer]
    policy_book: PolicyBook
    prices: PriceBook
    scenarios: dict[str, ClaimScenario]
    observations: dict[str, ImageObservationRef]
    history: list[dict[str, Any]]

    def image_path(self, image_id: str) -> Path:
        return self.root / self.observations[image_id].file

    def customer_policy(self, customer_id: str) -> Policy:
        return self.policy_book.policy(self.customers[customer_id].policy_id)


def load_synthetic(root: Path = SYNTHETIC_DIR) -> SyntheticData:
    pol = _read(root, "policies.json")
    tables = pol["tables"]
    book = PolicyBook(
        products={k: Product.model_validate(v) for k, v in pol["products"].items()},
        policies=[Policy.model_validate(p) for p in pol["policies"]],
        sublimits=[SublimitRow.model_validate(r) for r in tables["sublimits"]],
        depreciation_clause_id=tables["depreciation"]["clause_id"],
        depreciation=[DepreciationRow.model_validate(r) for r in tables["depreciation"]["categories"]],
        clauses={c["clause_id"]: Clause.model_validate(c) for c in pol["clauses"]},
    )
    pb = _read(root, "price_benchmark.json")
    prices = PriceBook(
        region=pb["_meta"]["region"], currency=pb["_meta"]["currency"], tolerance=pb["_meta"]["tolerance"],
        items={i["code"]: PriceItem.model_validate(i) for i in pb["items"]},
    )
    return SyntheticData(
        root=root,
        customers={c["customer_id"]: Customer.model_validate(c) for c in _read(root, "customers.json")["customers"]},
        policy_book=book,
        prices=prices,
        scenarios={c["scenario_id"]: ClaimScenario.model_validate(c) for c in _read(root, "claims.json")["claims"]},
        observations={o["image_id"]: ImageObservationRef.model_validate(o)
                      for o in _read(root, "image_observations.json")["observations"]},
        history=_read(root, "history.json")["past_claims"],
    )


@lru_cache
def synthetic() -> SyntheticData:
    return load_synthetic()
