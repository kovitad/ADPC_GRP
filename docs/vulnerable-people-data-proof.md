# Data proof: can we say how many vulnerable people live in a district?

**Run:** 24 September 2026, read-only, against `.local/data-in` and the running desktop database.
**Question asked:** show a table of how many vulnerable people live in a district, and if possible a map layer of where they live.
**Short answer:** **no, not from the data we hold.** Nothing in the delivery counts children, older people or people with disabilities. What the delivery *does* contain, unimported and unlabelled, is **total, male, female and household counts per village**, which would make a population table per district. That is a different claim and must never be presented as a vulnerable-people count.

## 1. The three vulnerability rasters cannot be counted

Read directly from the delivered files.

| File | Type | Values found | What it is |
|---|---|---|---|
| `childSensitivity_01.tif` | float32, 12.5 m, EPSG:32647 | continuous `0.0`–`1.0`, 2,090 distinct in a national sample, `NaN` outside | normalised **index** |
| `elderlySensitivity_01.tif` | float32, 12.5 m, EPSG:32647 | continuous `0.0`–`1.0`, `NaN` outside | normalised **index** |
| `disability_total.tif` | uint8, 12.5 m, EPSG:32647, nodata 255 | exactly **four** values: `1, 2, 3, 4` | ordinal **class**, despite `total` in the filename |

In a Kanthararom-sized window the two sensitivity rasters hold 16 distinct values and the disability
raster holds 2. A sum over a district therefore produces a number with **no denominator** — an index
total, not people. `disability_total` is a four-class ranking, so summing it is meaningless in a
different way.

Two secondary observations, both worth fixing whatever is decided:

- **Neither float raster declares a nodata value** (`nodata: None`) while using `NaN` for "outside".
  Any consumer that does not special-case `NaN` will produce `NaN` totals rather than an error.
- **All three are in UTM 47N, not EPSG:4326** like every other layer. Already on the backlog at
  `core/dataset_scan.py:301`.

## 2. SIG has age-disaggregated layers, but not counts either

SIG's weight picker advertises `vulnerability_F_infant`, `vulnerability_M_infant`,
`vulnerability_F_above60` and `vulnerability_M_above60` alongside `vulnerability_pop_all_total`.
**None of them is in the flood recipe**, which is `vulnerability_pop_all_total` 0.40,
`vulnerability_reclass_blddensity` 0.35, `vulnerability_reclass_road` 0.25. They are reclassified
weight layers feeding a risk class, not population tables.
`tests/contract/test_sig_recorded_contract.py:52` already records this as the open DEP-07 question:
*which layer means "vulnerable people"*. It is not answered.

## 3. What the delivery does contain: village population

`administrative_boundary/village/village.shp` has 80,397 points and **67 undocumented
`oct_side*` columns** that the importer ignores. Four of them are population:

| Column | Meaning inferred | National sum |
|---|---|---|
| `oct_side_9` | male | 32,085,158 |
| `oct_side10` | female | 27,871,045 |
| `oct_side11` | total population | 56,658,544 over usable rows |
| `oct_side12` | households | 21,192,948 |

**The evidence that these are population, not something else:**

1. **The identity holds.** `male + female == total` for **79,762 of 80,147** rows that carry all
   three — **99.52%**.
2. **The national total is plausible.** 56.7 million against a registered population near 66
   million, which is what a village-point layer should give: it excludes purely municipal areas.
3. **A district matches reality.** Kanthararom, Si Sa Ket (`acode` 3303): **175 villages, 85,568
   people, 43,309 male, 42,259 female, 23,594 households**, with the identity holding on all 175
   rows. The real district population is close to this. The same 175 villages are what the Planning
   panel already reports as village locations.

**Data-quality problems in those columns:**

- **385 rows violate the identity** and are excluded above.
- **Absurd maxima.** A single "village" records 3,045,168 male and another 16,921,692 total.
  Fifteen rows exceed 100,000 people. These look like misplaced cells, not villages.
- Two further columns, `oct_side15` and `oct_side_1`, hold values up to 1.9e16 and are clearly
  corrupt; nothing should read them.

## 4. Why no table can be shipped today

1. **The columns are not imported.** `POINT_PROFILES["village_locations"]["safe_fields"]` is
   `("pcode", "pname", "tname", "acode", "aname", "tcode", "mcode")`
   (`core/thailand_full_import.py`). Confirmed against the running database: village feature
   attributes carry codes and names only, no population. Showing the table is an **importer change
   and a re-import of 80,397 features**, not a UI change.
2. **The semantics are inferred, not documented.** `oct_side_9`..`oct_side12` is spreadsheet-merge
   debris. Section 3 is a strong statistical argument, not a data dictionary. This is the same shape
   as DEP-06 for the shelter columns, and it needs the data owner to confirm before any number
   reaches a planner.
3. **It would not answer the question asked.** Total population is not a vulnerable-person count.
   Publishing it in a panel labelled anywhere near "vulnerable" would assert something the data does
   not support.

## 5. What is possible on the map today

The three rasters are **already** shown as display-only context in the People tab under ADR-0015,
which is the correct treatment and needs no change. What cannot be built is a "where the vulnerable
people live" layer: the rasters give a relative index per 12.5 m cell, so a planner can see *where
sensitivity is higher*, never *how many people are there*. That distinction is the whole finding.

## 6. Separate confirmed bug: village Thai names are stored as mojibake

Found while reading the imported attributes. For the same district, from the same delivery, through
the same reader:

```text
boundary.name_th            เมืองสมุทรปราการ        correct
village feature aname       เนเธกเธทเธญเธ...        UTF-8 bytes decoded as TIS-620
```

`read_vector_explicit` reports `TIS-620` as *assumed* for `village.shp` from candidates
`['UTF-8', 'TIS-620']`; the boundary shapefiles are decoded correctly. Every planner-facing Thai
string from the village layer — village, sub-district, district and province name — is currently
unreadable. This is independent of the population question and should be fixed before the village
layer is used for anything a planner reads.

## 7. Recommended next steps, in order

1. **Fix the village encoding** (Section 6). Small, provable, blocks nothing else.
2. **Take the four population columns to the data owner** for confirmation, together with the
   385 identity violations and the 15 absurd rows. Ask explicitly whether an age or disability
   breakdown exists at village or sub-district level anywhere in the delivery; if it does not, a
   vulnerable-people count is not obtainable from this source and DEP-07 has to be answered another
   way.
3. **Only then** import the confirmed columns under a new importer version and show a per-district
   **population** table, labelled as registered village population with its edition, never as
   vulnerability.
4. Keep the three rasters display-only until DEP-07 names the layer and a method is approved.
