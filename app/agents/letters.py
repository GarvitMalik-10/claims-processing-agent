"""Customer letter / WhatsApp message (README 9.6), written by Sonnet from the decision record ONLY.
The model gets structured facts and reason codes - never other agents' prose - and decides nothing."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.llm.claude import ClaudeClient, ModelCall

PROMPT_VERSION = "letter_v1"
BRAND = "Tecto"


class CustomerLetter(BaseModel):
    chat_message: str = Field(description="Short WhatsApp message (max ~80 words)")
    letter: str = Field(description="Formal decision letter in Markdown, explaining each amount and reason")


SYSTEM = f"""You write the outcome message for a {BRAND} home insurance claim, in the requested language
(nl = Dutch with informal 'je', en = English). You receive the decision record as structured data.
Rules:
- State only what is in the record. Never add amounts, reasons, promises or advice that are not in it.
- Explain each deduction in plain words using the given reason (benchmark price, depreciation, deductible,
  excluded item with its clause title).
- For a refusal or partial refusal, be clear and kind, cite the clause title, and mention that the customer
  can reply in the chat with questions or new information.
- Amounts in euros with two decimals. No internal codes like PAY-BENCH-01 in the text.
- Sign the letter as "{BRAND} Schadeservice" (nl) or "{BRAND} Claims Team" (en)."""


def write_letter(claude: ClaudeClient, *, language: str, record: dict[str, Any]) -> ModelCall[CustomerLetter]:
    import json

    text = f"Language: {language}\nDecision record:\n{json.dumps(record, ensure_ascii=False, indent=2)}"
    return claude.structured(system=SYSTEM, content=[{"type": "text", "text": text}], output_model=CustomerLetter,
                             prompt_version=PROMPT_VERSION, effort="low")
