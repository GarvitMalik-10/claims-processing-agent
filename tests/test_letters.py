"""Letters: the LLM may phrase, never calculate. Every euro amount must come from the decision record."""

from __future__ import annotations

from app.agents.letters import CustomerLetter, unknown_amounts, write_letter
from app.store.blobs import LocalBlobStore
from tests.stubs import StubClaude

RECORD = {"claim_ref": "CLM-1", "customer_first_name": "Emma", "lines": [
    {"item": "Roof", "claimed": 4760.0, "covered": 3542.0}, {"item": "Window", "claimed": 1150.0, "covered": 690.0}],
    "total_covered": 9062.0, "deductible": 100.0, "payout": 8962.0}


def test_amounts_in_record_pass_in_both_number_formats():
    assert unknown_amounts("We pay €8,962.00 after €100.00 deductible (€ 4.760,00 claimed).", RECORD) == []
    assert unknown_amounts("Uitkering € 8.962,00, eigen risico € 100,00.", RECORD) == []


def test_invented_total_is_caught():  # the real slip seen in the S16 letter
    assert unknown_amounts("The total covered amount is €8,062.00.", RECORD) == ["€8,062.00"]


def test_bad_draft_is_regenerated_then_accepted(tmp_path):
    claude = StubClaude(LocalBlobStore(tmp_path))
    claude.push(CustomerLetter(chat_message="Paid €8,962.00", letter="Total €8,062.00"))
    claude.push(CustomerLetter(chat_message="Paid €8,962.00", letter="Total €9,062.00, payout €8,962.00"))
    letter, call, warnings = write_letter(claude, language="en", record=RECORD)
    assert call is not None and "9,062.00" in letter.letter
    assert warnings == ["LETTER_AMOUNT_NOT_IN_RECORD: €8,062.00"]
    assert "not in the record" in claude.calls[1]["content"][0]["text"]


def test_persistent_errors_fall_back_to_template(tmp_path):
    claude = StubClaude(LocalBlobStore(tmp_path))
    for _ in range(2):
        claude.push(CustomerLetter(chat_message="Paid €1.00", letter="Total €2.00"))
    letter, call, warnings = write_letter(claude, language="nl", record=RECORD)
    assert call is None and warnings[-1] == "LETTER_TEMPLATE_FALLBACK"
    assert unknown_amounts(letter.letter + letter.chat_message, RECORD) == []
    assert "8.962,00" in letter.letter
