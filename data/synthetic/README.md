# Synthetic demo data

The grounding data for the claims STP demo. Every file is JSON (Pydantic-loadable) and cross-referenced by ID.

| File | What | Keys |
|---|---|---|
| `media/images/` | 20 real, openly licensed damage photos (see `CREDITS.md`) | `IMG-01` … `IMG-20` |
| `image_observations.json` | Reference observations per image: scene, quality, damage types, damaged parts, materials, severity, sudden vs gradual, long-term signs, visible text, per-element confidence, NL/EN summary, warnings | `image_id` |
| `customers.json` | 8 demo personas (persona picker) | `customer_id` → `policy_id` |
| `policies.json` | 4 products, 8 policies, policy tables (sublimits, depreciation, authority) and clause wording NL/EN with machine conditions | `policy_id`, `clause_id`, `row_id` |
| `price_benchmark.json` | NL supplier price benchmark p25/p50/p75 per repair code | `code` |
| `claims.json` | 20 storylines: customer messages (NL/EN), contractor estimate, golden outcome | `scenario_id` → `customer_id`, `images` |
| `history.json` | Past claims for frequency and duplicate-photo checks | `claim_id` |

## Scenario matrix

| # | Image | Persona | Story | Expected route | Shows |
|---|---|---|---|---|---|
| S01 | 01 pipe leak | Sanne | Kitchen trap leak; photo only shows the source | info_request → STP €552.40 | Missing-info loop, depreciation |
| S02 | 02 ceiling peeling | Pieter | Washing machine hose burst upstairs | **STP €296.00** | High deductible |
| S03 | 03 ceiling stain | James (tenant) | Neighbour's leak, wants ceiling repaired | human (not covered) | Tenant ≠ building cover |
| S04 | 04 buckled floor | Lotte | Living room floor buckled | human | **Image mismatch: museum** |
| S05 | 05 flood kitchen | Henk | Street flooding into kitchen | human (not covered) | Flood exclusion, frequency |
| S06 | 06 bathroom tile | Sanne | "Kitchen plaster ceiling" | human | **Wrong room + material** |
| S07 | 07 shower mould | Fatima | "Mould appeared suddenly" | human (not covered) | Gradual exclusion, new policy |
| S08 | 08 ceiling mould | Henk | "Storm last night" + 2024 EXIF | **SIU** | Old photo, inconsistent story |
| S09 | 09 rusted wall | Pieter | "Burst yesterday" | human (not covered) | Gradual, honest customer |
| S10 | 10 socket | Sanne | Socket fire while charging | **STP €735.50** | Fire vs scorching, depreciation cap |
| S11 | 11 roof fire | Lotte | House fire, roof gone | human (senior) | Authority limit |
| S12 | 12 burned room | Fatima | Room burned out, 19 days into policy | info_request → human | Soft risk signals |
| S13 | 13 + 14 chimney | Pieter | Storm chimney collapse | **SIU** | **Duplicate photo (hard flag)** |
| S14 | 14 chimney | Sanne | Storm chimney collapse | **STP €4,129.08** | Flagship STP: storm, emergency cover, depreciation |
| S15 | 15 pantiles | Ahmed | Farmhouse roof after storm | human | Jev uncertain band |
| S16 | 16 tree on house | Emma | Tree on house in storm | human (handler) €8,962 | Price trimming |
| S17 | 17 tree in garden | Ahmed | "Just reporting" | incident_only | Claim vs incident |
| S18 | 18 cracked glass | Emma | Football through window | **STP €312.00** | Glass cover, no deductible |
| S19 | 19 forced door | James (tenant) | Burglary, laptop stolen | **STP €1,409.15** | Tenant burglary cover, contents depreciation |
| S20 | 20 intact room | Fatima | "Leak damage" with a normal room photo | info_request | Not a damage photo |

Totals: 5 STP, 2 STP after info, 9 human review, 2 SIU, 1 incident only, 1 info request.

## Rules the golden numbers follow

- `validated = min(claimed unit price, p75 × 1.10) × qty`
- Source-repair lines (`source_repair: true`) are 0 (clause C-2.3).
- Depreciation: `validated × min(max, rate × max(0, age − new_value_years))` (C-9.1, table rows `DEP-*`)
- Cap at sublimits and sum insured, then subtract the deductible (C-9.2). The glass deductible is €0.
- Every golden payout has been recomputed from these rules and matches.

## Known caveats

1. **The images are not Dutch.** Several photos show UK or US clues: street signs in IMG-11 and IMG-13, US sockets, siding and asphalt shingles. In the demo config, `VISIBLE_TEXT_LOCATION_MISMATCH` and `regional_indicators` should be **warnings only** (low weight), except in S13, where they reinforce the duplicate flag.
2. **No photo of a water-damaged kitchen cabinet or laminate floor.** S01's "after the info request" step needs one. Options: take your own photo, use an AI-generated one, or let the prospect answer by text.
3. **EXIF:** Commons images carry little or no camera metadata. Scenarios with `exif_override` (S08, S14) need a build step that writes synthetic EXIF into **copies** of the images. Under CC BY-SA, those copies must keep the same license.
4. **pHash values** in `history.json` are computed at build time, not stored by hand.
5. Observation confidences are annotator certainty, not measured probabilities. Routing must never use them (README principle 9).
