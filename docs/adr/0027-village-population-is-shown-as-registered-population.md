# ADR-0027: Village population is shown as registered population, never as vulnerability

**Status:** Accepted by the product owner on 24 September 2026, who directed that the counts be shown after reading the proof below. The source columns remain **unconfirmed by the data owner**; this ADR records what that obliges.

**Date:** 2026-09-24

**Deciders:** Product owner (Kovitad); Technical Lead to review; DDPM / ADPC Data Science as data owner for the confirmation still owed

## Context

A planner asked for a table of how many vulnerable people live in a district, and a map layer of
where they live. [`docs/vulnerable-people-data-proof.md`](../vulnerable-people-data-proof.md) proves
that cannot be answered from the delivery:

- `childSensitivity_01.tif` and `elderlySensitivity_01.tif` are continuous 0–1 **indices**.
- `disability_total.tif` holds four ordinal **classes**, despite `total` in its name.
- SIG's `vulnerability_F_infant`, `M_infant`, `F_above60` and `M_above60` are weight-picker layers
  and none is in the flood recipe. That is DEP-07, still unanswered.

What the delivery does hold, in `administrative_boundary/village/village.shp`, is four undocumented
`oct_side*` columns. The evidence that they are male, female, total population and households:
`male + female == total` on **79,762 of 80,147** rows carrying all three (**99.52%**); the national
total is 56.7 million, right for a village layer against a registered population near 66 million;
and Kanthararom reconciles at **175 villages and 85,568 people**, matching the real district.

Two defects blocked using the layer at all. Its Thai text was stored as mojibake, because the `.dbf`
declares UTF-8 but holds a few truncated byte sequences, so `read_vector_explicit` fell through to
TIS-620 — which decoded every row, silently and wrongly. And the population columns were never
imported.

## Decision

- **The counts are shown, labelled as registered village population**, with the edition and an
  explicit caveat naming the source columns as unconfirmed. They are **never** labelled as
  vulnerability, vulnerable people, or an age or disability breakdown.
- **A declared encoding is recovered, not abandoned** (`core/dataset_scan.py`). Candidate order is
  declared → **declared, byte-recovered** → assumed UTF-8 → assumed TIS-620 → assumed CP874. The
  recovery reads byte-preserving (`ISO-8859-1`) and re-decodes with the declared encoding, replacing
  only the values that cannot decode and counting them. Recovery is offered **only** where a `.cpg`
  declares an encoding; without one, guessing is all there is. Of 80,397 village rows, 308 values
  fail to decode and **all of them are in unused `oct_side*` columns** — every name field decodes
  cleanly.
- **A village row is counted only when it is self-consistent.** All four values present and whole,
  `male + female == total`, and `0 < total <= 100,000`. Everything else is **excluded and counted**,
  never coerced to zero. On the delivery this excludes 1,024 of 80,397 rows.
- **Aggregation happens at import time**, into `area_population_summary`, one row per area per
  village dataset version, for district and sub-district alike. A web request must never scan 80,397
  points, so the planner click is one indexed read.
- **An area with no summary reports `null`, not zero.** Absence of a record is not absence of people.
- **The village importer gets its own version**, `grp-village-population/1`, so this re-imports the
  village layer alone and leaves the volunteer-centre and early-warning imports untouched.
- **`GET /api/v1/catalog/areas/{boundary_id}/profile`** serves it, `x-grp-access: protected`,
  restricted to planning roles and covered in the permission matrix.

## Options considered

| Option | Benefit | Main risk |
|---|---|---|
| Show nothing until the data owner confirms | No unconfirmed number reaches a planner | A planner sees a district with no population at all, while the data sits in the delivery |
| Sum the sensitivity rasters into a "vulnerable people" count | Answers the question as asked | Scientifically false: an index has no denominator. Rejected outright |
| Show the counts labelled as registered population, caveated (chosen) | Real, reconcilable numbers a planner can use now | The column semantics are inferred, so a data-owner correction may change them |
| Import the columns but keep them out of the UI | Data ready, no claim made | The work is invisible and the question stays unanswered |

## Consequences

- **This is a re-import**, and it took effect on the local stack: village version
  `b3105413-6808-57cc-9816-a537053e4338`, 8,133 summary rows (878 districts, 7,255 sub-districts),
  79,373 of 80,397 villages carrying population. Kanthararom reads 175 villages, 85,568 people,
  43,309 male, 42,259 female, 23,594 households — identical to the offline proof.
- **The encoding change affects every importer and the inspector**, because they share
  `read_vector_explicit`. The seven other delivered shapefiles decode on their first candidate and
  are unchanged; only `village.shp` takes the recovery path.
- `encoding_source` gains the value `cpg-recovered`, which the inspector surfaces.
- **The confirmation is still owed.** The data owner must confirm the four columns, and be shown the
  385 identity violations and the fifteen rows recording more people than the largest Thai city. If
  they contradict the inference, the label and the numbers change together, under a new version.
- **DEP-07 is not closed by this.** A vulnerable-person count remains unobtainable from this source.
  The three rasters stay display-only under ADR-0015.

## Action items

- [x] Recover the declared encoding; village Thai names now read correctly
- [x] Import the four columns, aggregate at import time, serve one indexed read
- [x] Show district and sub-district counts on click, caveated
- [ ] Data owner to confirm the four columns and the quality corrections
- [ ] Technical Lead review
