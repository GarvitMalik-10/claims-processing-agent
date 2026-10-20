"""Outbound customer messages. The conversation layer never decides anything (README 7.3): it only
phrases requests produced by the graph. Fixed situations use templates; the missing-info question is
written by Sonnet so it reads naturally and asks only for what is missing."""

from __future__ import annotations

from app.llm.claude import ClaudeClient, ModelCall
from app.models.fnol import InfoRequestMessage

PROMPT_VERSION = "info_request_v1"
BRAND = "Tecto"

FIELD_HINTS = {
    "loss_date": "the date the damage happened",
    "peril": "what caused the damage",
    "location": "which room or part of the home is damaged",
    "source": "where the water (or fire) came from",
    "source_stopped": "whether the cause has been stopped (for example tap closed or leak repaired)",
    "damage_photo": "a photo that clearly shows the damage",
    "fire_brigade_report": "the fire brigade report number",
    "police_report_ref_if_theft": "the police report number for the theft",
}

SYSTEM = f"""You are the {BRAND} claims assistant on WhatsApp. Write ONE short, friendly message asking the
customer for the missing information listed. Rules:
- Write in the requested language (nl = Dutch, informal 'je'; en = English).
- Ask only for the listed items; a short bulleted list is fine when there is more than one.
- Do not promise or hint at coverage, payment or amounts. Do not mention internal codes.
- Maximum about 60 words. No sign-off with a name. At most one emoji."""


def field_hint(field: str, item_labels: dict[str, str]) -> str:
    kind, _, arg = field.partition(":")
    if kind == "item_age":
        return f"how old the {item_labels.get(arg, arg)} is (or the year it was bought)"
    if kind == "photo_of":
        return f"a photo that clearly shows the damaged {item_labels.get(arg, arg)}"
    if kind == "ask":  # free-text question from a human reviewer
        return arg
    return FIELD_HINTS.get(field, field)


def write_info_request(claude: ClaudeClient, *, language: str, customer_first_name: str, missing: list[str],
                       item_labels: dict[str, str], round_no: int) -> ModelCall[InfoRequestMessage]:
    asks = "\n".join(f"- {field_hint(f, item_labels)}" for f in missing)
    prompt = (f"Language: {language}\nCustomer first name: {customer_first_name}\n"
              f"This is follow-up question number {round_no}.\nMissing information:\n{asks}")
    return claude.structured(system=SYSTEM, content=[{"type": "text", "text": prompt}],
                             output_model=InfoRequestMessage, prompt_version=PROMPT_VERSION, effort="low")


TEMPLATES = {
    "registered": {
        "nl": "Dank je, {name}. Je schademelding is geregistreerd onder nummer {claim_ref}. We beoordelen hem nu en laten je snel weten hoe het verder gaat.",
        "en": "Thanks, {name}. Your claim is registered under number {claim_ref}. We're assessing it now and will update you shortly.",
    },
    "incident_recorded": {
        "nl": "Dank je voor je melding, {name}. We hebben dit vastgelegd onder {claim_ref}, zonder schadeclaim. Merk je later toch schade op? Laat het ons dan gewoon weten in dit gesprek.",
        "en": "Thanks for letting us know, {name}. We've recorded this under {claim_ref}, without a claim. If you notice any damage later, just tell us in this chat.",
    },
    "handover": {
        "nl": "Dank je, {name}. Een collega van {brand} bekijkt je melding persoonlijk en neemt contact met je op.",
        "en": "Thanks, {name}. A colleague at {brand} will look at your notification personally and get back to you.",
    },
}


def template(key: str, language: str, **kw: str) -> str:
    lang = language if language in ("nl", "en") else "nl"
    return TEMPLATES[key][lang].format(brand=BRAND, **kw)
