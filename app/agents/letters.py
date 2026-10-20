"""Customer letter / WhatsApp message (README 9.6), written by Sonnet from the decision record ONLY.
The model gets structured facts, precomputed totals and reason codes - never other agents' prose - and
decides and calculates nothing. Code then checks that every euro amount in the text exists in the
record; otherwise it regenerates once, and falls back to a deterministic template."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from app.llm.claude import ClaudeClient, ModelCall

PROMPT_VERSION = "letter_v2"
BRAND = "Tecto"


class CustomerLetter(BaseModel):
    chat_message: str = Field(description="Short WhatsApp message (max ~80 words)")
    letter: str = Field(description="Formal decision letter in Markdown, explaining each amount and reason")


SYSTEM = f"""You write the outcome message for a {BRAND} home insurance claim, in the requested language
(nl = Dutch with informal 'je', en = English). You receive the decision record as structured data.
Rules:
- State only what is in the record. Never add amounts, reasons, promises or advice that are not in it.
- NEVER add up, subtract or calculate anything. Every amount you mention must be copied from the record;
  the record already contains every total you need (total_covered, deductible, payout).
- Explain each deduction in plain words using the given reason (benchmark price, depreciation, deductible,
  excluded item with its clause title).
- For a refusal or partial refusal, be clear and kind, cite the clause title, and mention that the customer
  can reply in the chat with questions or new information.
- Amounts in euros with two decimals. No internal codes like PAY-BENCH-01 in the text.
- Sign the letter as "{BRAND} Schadeservice" (nl) or "{BRAND} Claims Team" (en)."""

_AMOUNT = re.compile(r"€\s?(-?\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d{1,2})?|-?\d+(?:[.,]\d{1,2})?)")


def _parse_amount(s: str) -> float | None:
    s = s.replace(" ", "")
    if re.search(r"[.,]\d{1,2}$", s):  # last separator is the decimal one
        whole, dec = s[:-3 if s[-3] in ".," else -2], s[-2:].lstrip(".,")
        whole = re.sub(r"[.,]", "", whole)
        try:
            return round(float(f"{whole}.{dec}"), 2)
        except ValueError:
            return None
    try:
        return float(re.sub(r"[.,]", "", s))
    except ValueError:
        return None


def _numbers(obj: Any) -> set[float]:
    out: set[float] = set()
    if isinstance(obj, dict):
        for v in obj.values():
            out |= _numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _numbers(v)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out.add(round(float(obj), 2))
    return out


def unknown_amounts(text: str, record: dict[str, Any]) -> list[str]:
    """Euro amounts in `text` that do not appear anywhere in the record."""
    allowed = _numbers(record) | {0.0}
    bad = []
    for m in _AMOUNT.finditer(text):
        v = _parse_amount(m.group(1))
        if v is not None and round(abs(v), 2) not in allowed:
            bad.append(m.group(0))
    return bad


def _call(claude: ClaudeClient, language: str, record: dict[str, Any], feedback: str | None) -> ModelCall[CustomerLetter]:
    text = f"Language: {language}\nDecision record:\n{json.dumps(record, ensure_ascii=False, indent=2)}"
    if feedback:
        text += f"\n\nYour previous draft contained amounts that are not in the record: {feedback}. Only copy amounts from the record."
    return claude.structured(system=SYSTEM, content=[{"type": "text", "text": text}], output_model=CustomerLetter,
                             prompt_version=PROMPT_VERSION, effort="low")


def template_letter(language: str, record: dict[str, Any]) -> CustomerLetter:
    nl = language == "nl"
    eur = (lambda x: f"€ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")) if nl else (lambda x: f"€{x:,.2f}")
    rows = "\n".join(f"| {l['item']} | {eur(l['claimed'])} | {eur(l['covered'])} |" for l in record["lines"])
    head = "| Onderdeel | Gevraagd | Vergoed |\n|---|---|---|" if nl else "| Item | Claimed | Covered |\n|---|---|---|"
    name, ref, pay = record["customer_first_name"], record["claim_ref"], record["payout"]
    if nl:
        letter = (f"# Besluit op je claim {ref}\n\nHoi {name},\n\n{head}\n{rows}\n\nTotaal vergoed: {eur(record['total_covered'])}\n\n"
                  f"Eigen risico: {eur(record['deductible'])}\n\n**Uitkering: {eur(pay)}**\n\nVragen? Reageer in de chat.\n\n{BRAND} Schadeservice")
        chat = f"Hoi {name}, je claim {ref} is afgehandeld. Uitkering: {eur(pay)}. Details staan in de brief."
    else:
        letter = (f"# Decision on your claim {ref}\n\nDear {name},\n\n{head}\n{rows}\n\nTotal covered: {eur(record['total_covered'])}\n\n"
                  f"Deductible: {eur(record['deductible'])}\n\n**Payout: {eur(pay)}**\n\nQuestions? Reply in the chat.\n\n{BRAND} Claims Team")
        chat = f"Hi {name}, your claim {ref} has been settled. Payout: {eur(pay)}. Details are in the letter."
    return CustomerLetter(chat_message=chat, letter=letter)


def write_letter(claude: ClaudeClient, *, language: str, record: dict[str, Any]) -> tuple[CustomerLetter, ModelCall | None, list[str]]:
    """Returns (letter, last model call or None if the template was used, warnings)."""
    warnings: list[str] = []
    feedback = None
    call = None
    for _attempt in range(2):
        call = _call(claude, language, record, feedback)
        bad = unknown_amounts(call.output.letter + "\n" + call.output.chat_message, record)
        if not bad:
            return call.output, call, warnings
        warnings.append(f"LETTER_AMOUNT_NOT_IN_RECORD: {', '.join(bad)}")
        feedback = ", ".join(bad)
    warnings.append("LETTER_TEMPLATE_FALLBACK")
    return template_letter(language, record), None, warnings
