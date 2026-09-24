# ADR-0024: The delivered shelter name and capacity columns are confirmed, and labels are composed

**Status:** Accepted by the product owner on 23 September 2026. Closes the shelter half of DEP-06.

**Date:** 2026-09-23

**Deciders:** Product owner (Kovitad); Technical Lead (Kwan) to review; DDPM as data owner for the corrections listed below

## Context

The DDPM delivery carries five truncated Thai columns (`สถา`, `สถ_1`, `รอง`, `ละต`, `ลอง`). DEP-06 had not confirmed what any of them meant, so `core/shelter_import.py` wrote `Evacuation centre 1..10303` as the planner-facing name and excluded the rest. Every centre on the map was therefore indistinguishable from every other, and the prepared SIG contribution had no `name_field` to declare.

The real delivery, the previously proven `grp-shelters/4` import and planner screenshots confirm
`สถา` as the centre name, `สถ_1` as the responsible/supporting unit, and `รอง` as the number of
people the centre can take. An earlier draft of this ADR reversed the first two columns; the
resulting `grp-shelters/3` version showed broad values such as `ส่วนราชการ` instead of facility
names and was immediately superseded without altering assessments that had already pinned it.

A second candidate was considered and rejected on evidence. The prepared contribution candidate also carries a supporting-unit column, and it was proposed as the name. Profiling all 10,303 delivered records settled it:

| candidate | blank | ambiguous inside its district | distinct |
|---|---|---|---|
| facility name (`สถา`) | 41 | 2,504 require a village qualifier | 8,148 |
| supporting unit (`สถ_1`) | 792 | broad repeated categories | 3,017 |

The supporting unit names the organisation responsible for a centre, not the centre. Eleven separate temples and schools in นายายอาม all record `อบต.นายายอาม`; ten in หนองตาคง all record `ทต.หนองตาคง`. Using it as the label would collapse those into repeated, indistinguishable rows.

## Decision

- **`สถา` is the centre name, `สถ_1` is the supporting unit and `รอง` is capacity.** The name column is required; missing values fall back as described below.
- **A capacity is a positive whole number of people.** Anything else is recorded as absent, never as zero. 1,688 of the delivered records have no capacity, and the import reports that count.
- **The planner-facing label is composed, not taken raw** (`core/shelter_labels.py`). The name is used as-is where it is unique inside the district; where it repeats the village is appended; where that is still not enough the source number is. On the delivery this makes every label unique within its district: 2,447 need a village and 942 need a number.
- **Uniqueness is sought within a district only**, because two districts may each legitimately have a `ศาลาหมู่บ้าน` and a planner works inside one district.
- **Nothing is invented.** A record with no name falls back to the supporting unit, and one with neither keeps a numbered label. Both are counted in the import report.
- **The district used is the one the geometry falls in**, not the one the record claims, so a centre that claims the wrong district is still labelled where a planner will look for it.
- **The supporting unit, subdistrict, village and raw source name are kept as attributes** and returned by the map API beside the label. They are context, not identity.

## Options considered

| Option | Benefit | Main risk |
|---|---|---|
| Keep numbered labels | No unconfirmed field is shown | Every centre reads alike; the SIG manifest has no name field; planners cannot act |
| Use the supporting unit as the name | One column, no composition | 792 blanks and 8,344 records sharing a label; eleven temples become one repeated row |
| Use the name and compose where it repeats (chosen) | Every label unique in its district, nothing invented, ambiguity counted | A composed label is not the literal source string, so the raw name is kept as an attribute |

## Consequences

- Dataset versions are immutable, so this takes effect through a **re-import**: a new version, accepted and activated. Assessments locked to the earlier version keep their numbered labels, which is correct, and the Data Library must not present the two versions as interchangeable.
- `IMPORTER_VERSION` moves to `grp-shelters/5`; v3 is retained only for pinned historical assessments and v4 remains a valid previous proof version.
- The SIG contribution manifest can now declare `name_field` and a capacity, which was the blocker recorded in `docs/shared-sig-contribution-e2e-plan.md`.
- The village and subdistrict columns are located by name hints, as the district column already is. A delivery without them still imports; its labels simply fall back to numbering, and the report says how often.

## Data corrections owed by the data owner

Found while profiling the delivery. None blocks this decision; all of them affect what a public contribution would publish.

- **Province is wrong on about 22 records.** `DDPM-SHELTER-119` to `-140` record `จันทบุรี` while their districts (เมืองชลบุรี, พนัสนิคม, พานทอง, เกาะจันทร์) are in **ชลบุรี**.
- **`#REF!` appears as a centre name**, an Excel error that reached the delivery. Six further names begin with `.`, `,` or `(`.
- **A coordinate is about 100 km out.** `DDPM-SHELTER-164` is in กุดจอก, หนองมะโมง, ชัยนาท with its neighbours near 99.9°E but sits at 100.86°E.
- **1,599 records share a coordinate with another record**, across 961 groups, 70 of which span districts.

## Action items

- [x] Confirmed field mapping, composed labels, capacity, and the attributes the map returns
- [x] Re-imported and activated `grp-shelters/5`; a fresh Chiang Yuen assessment returned all nine source names, including `อบต.นาทอง`
- [ ] Send the four corrections above to DDPM before any public contribution
- [ ] Technical Lead review
