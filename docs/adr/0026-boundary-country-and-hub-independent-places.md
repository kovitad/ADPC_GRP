# ADR-0026: The country of a place comes from the boundary delivery, never from a constant

**Status:** Accepted on 24 September 2026, as a correctness fix to the place string introduced by `5f4b8cd`. No product-owner decision was needed; it changes no scientific boundary and no planner-visible result.

**Date:** 2026-09-24

**Deciders:** Technical Lead to review; no data-owner dependency

## Context

`5f4b8cd` fixed a real defect: Add SIG context sent the short UI label `KANTHARAROM`, SIG's geocoder
resolved it to a different place, and GRP's exact-area gate correctly refused the answer. The fix
enriches the label from the managed boundary catalogue into
`KANTHARAROM District, SI SA KET, Thailand`.

That fix appended the country as a literal in `_canonical_sig_place` (`api/planning.py`). `Boundary`
(`core/assessment_models.py`) already carries `name_th`, `province_name` and `province_name_th` but
had no country, so there was nothing to read. The function is not Hub-scoped and runs for any
selected boundary, so a second Hub's district would have been sent to SIG labelled `Thailand`.
`AGENTS.md` requires failing closed on unknown Hubs and areas. Only the Thailand Hub holds real data
today, so this was a latent defect rather than a live one, and it is much cheaper to close before a
second Hub is onboarded than after.

A related silent fallback was found in the same commit. `_sig_context_boundary` promotes a selected
sub-district to its parent district, because SIG evidence is district-wide, and returned the
sub-district unchanged when no parent was loaded — with no signal that the hierarchy was incomplete.

## Decision

- **`Boundary.country_name` records the country the delivery covers** (migration
  `20260924_0015_boundary_country.py`), nullable, symmetric with the existing province columns. Both
  importers set it from a named `COUNTRY_NAME` constant in their own module
  (`core/boundary_import.py`, `core/thailand_full_import.py`).
- **`NULL` means unknown, and nothing may guess.** `_canonical_sig_place` returns `None` for a
  boundary with no recorded country. The caller then sends the label it already had, unenriched.
- **The exact-area gate remains the safety guard.** Declining to enrich is not a fail-open, because
  `_same_area` still has to accept whatever SIG resolves before any evidence is shown. This is why
  the unknown case degrades to "no enrichment" rather than refusing outright.
- **The synthetic test district keeps no country** (`grpcli/seed.py`). It is not a real place and
  must not be enriched into one.
- **A missing parent district is logged, not hidden.** `_sig_context_boundary` warns on
  `grp.planning` with both admin codes and still returns the sub-district, because refusing would
  change planner-visible behaviour beyond the defect.
- **`country_name` is pinned into the assessment area record** (`core/assessment_jobs.py`) and
  returned in `area_detail` (`api/assessments.py`). The existing key guard keeps assessments pinned
  before this change readable.
- **`hub_dataset_selection` stays reserved and unused.** It is declared in
  `core/data_library_models.py` and migrated, and no code reads or writes it; MVP 1 activates one
  release for every Hub through `is_current` and `is_supported` in `core/baseline_activation.py`.
  Dropping it would contradict ADR-0019 and the approved data-library design, and using it means
  building the per-Hub override feature. It keeps a docstring saying so. Changing either way needs
  its own ADR.

## Options considered

| Option | Benefit | Main risk |
|---|---|---|
| Keep the literal `Thailand` | No migration | Wrong place sent for every future Hub; contradicts fail-closed on unknown Hubs |
| Derive the country from the Hub record | No boundary change | `Hub` has only a code and a name, and a Hub may cover more than one country |
| Record it on the boundary delivery (chosen) | The country travels with the data that asserts it; nothing is Hub-scoped in code | One nullable column and a backfill for rows already imported |
| Refuse SIG enrichment when no country is recorded | Strictest reading of fail closed | Breaks the synthetic planning path, and the area gate already prevents a wrong result |

## Consequences

- **Rows imported before this change are backfilled in the migration, by exact source string only:**
  `ADPC Data Science delivery` and `ADPC Data Science Thailand hierarchy delivery`. On the local
  stack that is 1,856 + 8,442 boundaries set to `Thailand`, with the one synthetic row left `NULL`.
  Without it the current release would have lost the Kanthararom enrichment until a re-import.
- **A fresh deployment never uses the backfill.** It upgrades an empty database and then imports, so
  correctness rests on the importers. Both of the two `Boundary` construction sites outside the
  synthetic seed set the column.
- The API image must be **rebuilt** before Add SIG context reflects the fix; the schema change alone
  does not change the running code.
- A future non-Thai delivery must set its own `COUNTRY_NAME`. A delivery that does not is not
  silently mislabelled — it simply sends the unenriched label, which the area gate will usually
  refuse, and that is the intended outcome.
