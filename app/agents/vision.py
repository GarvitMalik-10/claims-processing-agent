"""Damage evidence extraction from photos (Sonnet vision). One call per image, story NOT included, so
the description cannot be anchored to what the customer claims. Extracts; never judges consistency."""

from __future__ import annotations

from app.llm.claude import ClaudeClient, ModelCall, image_block
from app.models.assessment import ImageObservation

PROMPT_VERSION = "vision_extract_v1"

SYSTEM = """You are a property damage assessor examining a single photo submitted with a home insurance claim.
Describe only what is visible. You are deliberately not told the customer's story - do not guess one.

- room_type: the room or part of the building shown. Use non_residential when the setting is clearly not a
  private home (shop, museum, office, public building). Use unknown when only a ceiling/wall/detail is visible.
- image_quality: not_a_damage_photo when the photo shows no damage at all.
- damage_types: choose every type that is visible; active_leak for water visibly dripping or running
  from a pipe, hose or fitting; use other only when nothing else fits.
- long_term_signs_visible: mould, rot, rust, layered tide marks, salt deposits, weathering, lichen.
- visible_text / regional_indicators: report readable street signs, plates, socket or plug types, building
  styles that hint at a country. These are recorded as observations, not accusations.
- confidence is your own estimate and is never used for decisions."""


def observe(claude: ClaudeClient, image_bytes: bytes) -> ModelCall[ImageObservation]:
    content = [image_block(image_bytes), {"type": "text", "text": "Describe this photo."}]
    return claude.structured(system=SYSTEM, content=content, output_model=ImageObservation,
                             prompt_version=PROMPT_VERSION, effort="low")
