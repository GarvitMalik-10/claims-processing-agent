"""FNOL field extraction (Sonnet) with deterministic quote verification.

The model must copy the exact words that support each field. Code then checks every quote against
the cited message; a field whose quote cannot be found is dropped (treated as missing) and logged as
a warning. Extraction never decides anything - it only feeds the completeness rules.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from app.llm.claude import ClaudeClient, ModelCall
from app.models.common import AgentOutput, Confidence, EvidenceRef, Warning
from app.models.domain import Estimate
from app.models.fnol import FnolExtraction, QuoteCheck, SourcedBool, SourcedText
from app.store.projections import EvidenceItem

AGENT = "fnol_extractor"
PROMPT_VERSION = "fnol_extract_v1"

SYSTEM = """You extract facts from a customer's first notification of a home insurance loss.
The customer writes in Dutch or English on WhatsApp. Messages may arrive over several turns.

Rules:
- Only extract what the customer actually says. If something is not stated, return null. Never guess.
- For every value, copy the exact supporting words from the message into `quote` (verbatim, in the
  original language, no translation, no ellipsis) and give that message's id as `evidence_id`.
- Write `value` in English. Resolve relative dates ("yesterday", "last night", "Tuesday") against the
  message's sent timestamp and give dates as YYYY-MM-DD.
- `source_stopped` is true only if the customer says the cause was stopped, fixed or put out.
- `item_ages`: when the customer states how old something on the repair estimate is (or when it was
  bought), map it to that estimate line's code.
- If the customer later corrects an earlier statement, use the latest statement.
- `extraction_confidence` is your own overall confidence; it is never used for decisions."""


def _messages_block(texts: list[EvidenceItem]) -> str:
    lines = []
    for t in texts:
        sent = t.sent_at or t.received_at.isoformat()
        lines.append(f"[{t.evidence_id}] sent {sent}:\n{t.text}")
    return "\n\n".join(lines)


def _estimate_block(estimate: Estimate | None) -> str:
    if not estimate:
        return "No repair estimate received yet."
    rows = [f"- {l.code}: {l.description} (age on estimate: {l.age_years if l.age_years is not None else 'not stated'})"
            for l in estimate.lines]
    return "Repair estimate lines:\n" + "\n".join(rows)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip(" .,!?;:\"'")


def verify_quotes(x: FnolExtraction, texts: list[EvidenceItem]) -> tuple[FnolExtraction, list[QuoteCheck], list[Warning]]:
    by_id = {t.evidence_id: _norm(t.text or "") for t in texts}
    checks: list[QuoteCheck] = []
    warnings: list[Warning] = []

    def locate(quote: str, evidence_id: str) -> str | None:
        q = _norm(quote)
        if q and q in by_id.get(evidence_id, ""):
            return evidence_id
        for other, text in by_id.items():  # right quote, wrong message id: correct it
            if q and q in text:
                return other
        return None

    updates: dict[str, Any] = {}
    for name, value in x:
        if isinstance(value, (SourcedText, SourcedBool)):
            found = locate(value.quote, value.evidence_id)
            checks.append(QuoteCheck(field=name, evidence_id=value.evidence_id, found=found is not None))
            if found is None:
                updates[name] = None
                warnings.append(Warning(code="QUOTE_NOT_FOUND", severity="warning",
                                        message=f"Dropped '{name}': quote not found in {value.evidence_id}"))
            elif found != value.evidence_id:
                updates[name] = value.model_copy(update={"evidence_id": found})
    for list_name in ("affected_items", "item_ages"):
        kept = []
        for item in getattr(x, list_name):
            found = locate(item.quote, item.evidence_id)
            checks.append(QuoteCheck(field=list_name, evidence_id=item.evidence_id, found=found is not None))
            if found is not None:
                kept.append(item.model_copy(update={"evidence_id": found}))
            else:
                warnings.append(Warning(code="QUOTE_NOT_FOUND", severity="warning",
                                        message=f"Dropped {list_name} entry: quote not found"))
        updates[list_name] = kept
    return x.model_copy(update=updates), checks, warnings


@dataclass(frozen=True)
class ExtractionResult:
    extraction: FnolExtraction
    output: AgentOutput[FnolExtraction]
    quote_checks: list[QuoteCheck]
    call: ModelCall[FnolExtraction]


def extract(claude: ClaudeClient, claim_id: str, texts: list[EvidenceItem], estimate: Estimate | None) -> ExtractionResult:
    content = [{"type": "text", "text": f"Customer messages:\n\n{_messages_block(texts)}\n\n{_estimate_block(estimate)}"}]
    call = claude.structured(system=SYSTEM, content=content, output_model=FnolExtraction, prompt_version=PROMPT_VERSION)
    verified, checks, warnings = verify_quotes(call.output, texts)
    evidence = [EvidenceRef(evidence_id=t.evidence_id, kind="text") for t in texts]
    output = AgentOutput[FnolExtraction](
        agent=AGENT, agent_version=PROMPT_VERSION, claim_id=claim_id, finding=verified,
        confidence=Confidence(value=verified.extraction_confidence, source="self_reported", basis="sonnet extraction"),
        evidence=evidence, reasoning=verified.reasoning, summary=verified.summary, warnings=warnings,
    )
    return ExtractionResult(extraction=verified, output=output, quote_checks=checks, call=call)


def sourced_fields(x: FnolExtraction) -> list[tuple[str, Any, str, str]]:
    """(field, value, quote, evidence_id) for every non-null sourced field - one fnol.field_extracted each."""
    out = []
    for name, v in x:
        if isinstance(v, (SourcedText, SourcedBool)):
            out.append((name, v.value, v.quote, v.evidence_id))
    for a in x.item_ages:
        out.append((f"item_age:{a.line_code}", a.age_years, a.quote, a.evidence_id))
    return out
