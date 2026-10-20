"""Reviewer brief (README 9.6): a short briefing for the human reviewer, written by Sonnet from the
decision record only (structured findings + reason codes + the customer's own words).

Prose for humans only - no agent ever reads it. The suggested action is advice shown to the reviewer;
the system never acts on it."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.llm.claude import ClaudeClient, ModelCall

PROMPT_VERSION = "reviewer_brief_v1"


class ReviewerBrief(BaseModel):
    headline: str = Field(description="One line: what this claim is and why it needs a human")
    key_points: list[str] = Field(description="3-6 bullets: the facts that matter for the decision, with numbers")
    open_questions: list[str] = Field(description="What the reviewer may want to check or ask the customer")
    suggested_action: Literal["approve", "override", "request_info", "escalate_siu", "needs_judgement"]
    suggestion_rationale: str = Field(description="One sentence; advice only")


SYSTEM = """You brief an experienced claims handler on a home insurance claim the automated process could not
settle on its own. You get the decision record as structured data. Write in English, concise and neutral.
- Only use facts in the record; quote numbers exactly. Do not invent facts or policy rules.
- Explain each reason code in plain words (e.g. IMAGE_CLAIM_INCONSISTENT: the photos contradict the account).
- Never accuse the customer; describe signals, not intentions.
- The suggested action is advice for the human; the human decides."""


def write_brief(claude: ClaudeClient, record: dict[str, Any]) -> ModelCall[ReviewerBrief]:
    text = "Decision record:\n" + json.dumps(record, ensure_ascii=False, indent=2, default=str)
    return claude.structured(system=SYSTEM, content=[{"type": "text", "text": text}], output_model=ReviewerBrief,
                             prompt_version=PROMPT_VERSION, effort="low")
