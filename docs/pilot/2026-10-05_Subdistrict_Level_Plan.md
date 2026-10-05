# Sub-district level across Planning, Assessments and Live: findings and plan

Status: completed on 6 October 2026 (ADR-0063), with the recommended answer to every question:

- a map click selects the sub-district and its district;
- the default scope is this sub-district;
- the live layer counts what is inside the sub-district, with the district total alongside;
- the order is Planning, then Live, then Assessments.

All seven steps are complete. Browser checks covered Planning, Assessments and Live at desktop
and phone widths; the Live cards and Check first count show the parent-district total alongside
the selected sub-district.

The owner's words: "District is kind of the default map boundary; however, our requirement is to
make it work down to sub-district level, based on our current foundation data. When I select a
sub-district inside a district, the map layers do not seem to work. The planner is supposed to ask
for assessment and planning in a sub-district boundary. Inspect the current boundary data and the
possible map integration for every page: Planning, Assessments and Live."

## 1. What the foundation data has (measured 5 October 2026)

| Data | District | Sub-district | Notes |
| --- | --- | --- | --- |
| Boundaries (ADPC hierarchy delivery, 2025-10) | 928 supported | **7,436, all supported, all with shapes** | 6-digit codes start with their district's 4 digits (`103005` is in `1030`). Thai and English names. |
| Bangkok | 50 | **180 khwaeng** | |
| Nonthaburi | 6 | **52 tambon** | |
| Registered population (village delivery) | 878 areas | **7,255 areas** | Nothing for Bangkok: the delivery has no villages there. |
| Modelled flood exposure (people and villages in the RP extent) | 878 | **7,255** | Same village basis. |
| Vulnerability (sensitivity) layers | n/a | **one value per sub-district** | Already drawn per sub-district in Planning. |
| Evacuation centres (DDPM) | by district | by **point in the sub-district shape** | `api/maps.py` already filters by the sub-district polygon. |
| Assessments | 49 run | **2 run, both succeeded** | The engine works on any supported boundary. Its step text still says "district". |
| Live flood evidence | incidents carry `district_codes` | **not computed** | Sub-districts roll up to their district (ADR-0056 rule). Facilities and cameras are points, so they can be placed in a sub-district directly. |
| Global Risk evidence | per district | **promoted to the parent district** | `api/planning.py` `_sig_context_boundary`. Global Risk does not answer below district. |

**Answer to the owner's question:** yes. The foundation data supports sub-district planning
everywhere except Bangkok population. Global Risk is district-only, and the live layer needs one
small computation.

## 2. What goes wrong today

### Planning (`planning.html`)

1. **Hidden.** To reach a sub-district you must select a district, then open Layers → Base map
   and boundaries → "Planning boundary level" and choose Sub-district. Nothing on the map suggests
   it.
2. **A dead end.** At sub-district level, `state.boundaries` holds only the chosen district's
   sub-districts. The district outline disappears, and clicking or searching outside it selects
   nothing. You have to switch the level back in Layers first.
3. **Search** looks only in the loaded list, so you cannot type a sub-district name from another
   district.
4. **The live layer** for a sub-district shows the whole district's incidents, facilities and
   cameras, with no sign that it rolled up.
5. **Global Risk evidence** moves to the parent district (correct), but the screen does not say so
   clearly.
6. **Wording** in the run steps and some cards says "district" for any level.

### Assessments (`assessments.html`)

- **Works:** a district picker, then an optional sub-district picker. The map draws the chosen
  area and its centres.
- **Gaps:** the result map does not show the parent district for context, and the step wording
  says "district".

### Live (`flood.html`)

- **Districts only:** the area picker lists the 56 districts, or all. There is no way to narrow
  to a sub-district.

## 3. Proposed design

### 3.1 One area model on every page: district, then sub-district

```text
Bangkok › Chatuchak › Lat Yao          [ Whole district | This sub-district ]
```

- **A breadcrumb** at the top of the map shows province › district › sub-district. Clicking a
  crumb goes back up a level.
- **Clicking the map** at any zoom selects the **sub-district under the click and its district
  together**, found from the shapes. There is no level switch to find first. The
  "Planning boundary level" dropdown is removed from Layers.
- **The scope switch.** "Whole district" or "This sub-district" decides what the summary, the
  assessment and the live counts cover. It defaults to the sub-district when one is selected.
- **The map shows:**
  - the selected district's outline, as the navy cased line;
  - its sub-districts as thin lines with name labels from zoom 13;
  - the selected sub-district emphasised, with the outside dimmed.

  Neighbouring districts stay clickable.

### 3.2 Search

- **A new server route,** `GET /api/v1/catalog/areas/search?q=`, searches all 7,436 sub-districts
  and 928 districts by Thai or English name, prefix and contains.
- **Results show their parent:** "Lat Yao · sub-district · Chatuchak, Bangkok".
- **Places and points of interest** (OpenStreetMap, later Longdo) still work. Picking one selects
  the sub-district it sits in.

### 3.3 Planning

- **The People tab** uses the sub-district's population and exposure, which already exist. In
  Bangkok it says population is not in the delivery.
- **Centres:** the existing sub-district polygon filter.
- **Run:** an assessment on the selected scope. The engine already supports it; only the step
  text changes to say "area" or "sub-district".
- **Live:**
  - incidents get `subdistrict_codes`, computed in the worker as `district_codes` are today;
  - facilities and cameras are placed by point;
  - the live card and the "Live now" list say "in Lat Yao sub-district", with "N more elsewhere
    in Chatuchak district" when there are more.
- **Global Risk:** stays district-level, with a fixed line: "Global Risk evidence is for
  Chatuchak district (it has no sub-district evidence)."
- **The district summary (Word)** for a sub-district: titled "Lat Yao sub-district, Chatuchak",
  with sub-district population, centres and live data, and Global Risk for the district, labelled.

### 3.4 Assessments

- The same breadcrumb.
- The result map shows the parent district's outline for context.
- Step and result wording use the area's level.

### 3.5 Live (`flood.html`)

- The area picker gets a second level: a district, then its sub-districts, or the whole district.
- Incidents, reports, facilities and cameras filter by the sub-district shape. Incidents use the
  new `subdistrict_codes`.
- Counts and the "Check first" list follow the chosen area.

### 3.6 What stays the same

- No new data is needed.
- Assessment and exposure methods and results are unchanged; only their scope selection changes.
- The ADR-0056 rule changes: a sub-district no longer silently rolls up. It is shown with its
  district context.

## 4. Steps (each one tested and committed separately)

1. **Area model and search API:** the areas search route, a containing-area lookup by point
   (server side, from the stored shapes), and tests.
2. **Planning area picker:**
   - the breadcrumb;
   - click to select a sub-district and its district;
   - sub-district lines and labels;
   - the scope switch;
   - the dropdown removed;
   - the dead end fixed.
3. **Planning content by scope:** People, centres, run wording and summary titles.
4. **Live by sub-district:** `subdistrict_codes` in the worker, Planner live cards and the list,
   with district context.
5. **Assessments page:** the breadcrumb, the parent outline and wording.
6. **Live page:** the two-level area picker and filters.
7. Browser checks at desktop and phone widths, ADR-0063 and the handover.

## 5. Questions for the owner

1. **Clicking the map:** select the sub-district and its district together (recommended), or keep
   district first, then sub-district?
2. **The default scope** once a sub-district is selected: this sub-district (recommended), or the
   whole district?
3. **The live layer for a sub-district:** count only what is inside it, with the district total
   alongside (recommended), or keep the district roll-up?
4. **Order:** Planning first, then Live, then Assessments (recommended), or all three together?
