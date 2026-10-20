"""The full claim graph: FNOL subgraph -> parallel assessment -> join (-> payout & routing in M4)."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from app.graph.assessment import add_assessment
from app.graph.deps import Deps
from app.graph.fnol import add_fnol
from app.models.state import ClaimGraphState


def build_claim_graph(deps: Deps, checkpointer: Any):
    g = StateGraph(ClaimGraphState)
    add_fnol(g, deps, after_registration="start_assessment")
    add_assessment(g, deps, after_join=END)
    return g.compile(checkpointer=checkpointer)
