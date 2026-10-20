"""The full claim graph: FNOL -> parallel assessment -> join -> coverage -> payout -> routing ->
(STP settle | human review | SIU | back to the customer).

`upto` builds a shorter graph (ending after registration or after the join) for focused tests."""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, StateGraph

from app.graph.assessment import add_assessment
from app.graph.decision import add_decision
from app.graph.deps import Deps
from app.graph.fnol import add_fnol
from app.models.state import ClaimGraphState

Upto = Literal["fnol", "assessment", "full"]


def build_claim_graph(deps: Deps, checkpointer: Any, upto: Upto = "full"):
    g = StateGraph(ClaimGraphState)
    add_fnol(g, deps, after_registration=END if upto == "fnol" else "start_assessment")
    if upto != "fnol":
        add_assessment(g, deps, after_join=END if upto == "assessment" else "resolve_coverage")
    if upto == "full":
        add_decision(g, deps)
    return g.compile(checkpointer=checkpointer)
