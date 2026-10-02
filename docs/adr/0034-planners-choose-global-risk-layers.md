# ADR-0034: Planners choose which Global Risk layers a question uses

## Status

Accepted on 29 September 2026 at the Product Owner's request: "have one drop down with checkbox
for them everytime they want to ask Platform they want to use which layer and name then we can
generate prompt to be precise what they pick for planning assession for each discrict or sub
districk".

## Context

A Global Risk layer name is the key to a dataset: answers count and cite by it, and contributions
never overwrite (ADR-0032, amendment 9). A planner asking about a district gets whatever the risk
pack holds: OpenStreetMap schools, hospitals, buildings and roads, plus every contributed point
layer, including test uploads. Several things constrain a picker:
- `assemble_pack` takes only `pack`, `place`, `hazard` and `focus`; it has no layer filter.
- `platform_capabilities` lists hazards and sources but not contributed point layers. Even
  `evacuation_centres_th_test` is missing.
- A pack's `stats.counts` names every layer Global Risk actually counted.
- The Global Risk groundedness check and receipt work on the pack exactly as Global Risk returned
  it.

## Decision

1. **A layer list per person and Hub.** `GET /api/v1/planning/global-risk-layers`
   (`protected`) offers:
   - Global Risk's four OpenStreetMap layers;
   - this Hub's approved or staged point layers and population grids;
   - every layer counted in the person's own recent evidence (30 days).

   Each entry has its exact name, a planner's label, and whether it is GRP's own data. It returns
   404 where the planning chat is off, like the conversation routes.
2. **The picker.** Above the Planning message box, a dropdown with a checkbox per layer. It holds
   at most 12 layers. "Write the question" puts an editable question in the box, naming the area
   and every chosen layer by label and exact name. A sub-district is asked as the district that
   contains it, because Global Risk evidence is district-wide (`_sig_context_boundary`), and the
   question says so. A question the picker wrote is sent with its area confirmed.
3. **The request.** `PlanningChat.layers` carries the chosen names on every Global Risk question
   while any are chosen. The server accepts only names the list offers this person, because they
   go into a model prompt; anything else is refused with `UNKNOWN_LAYER` before any call.
4. **How the choice takes effect, without touching the pack:**
   - the `focus` sent to `assemble_pack` ends "Layers chosen: …";
   - the draft prompt carries `chosen_layers`, and the instructions (`planning-draft-v5`) report
     those layers only and say plainly when one has no count;
   - the evidence stores `selected_layers`. The evidence card and section 5 of the Word summary
     show only those counts, add a "no count returned" row for a chosen layer the pack lacks, and
     note "Layers chosen for this question".

   Citations are never filtered or renumbered.
5. **The hazard stays `flood`.** A hazard picker would need pack-reuse and cache keys by hazard,
   and summary wording per return period. It is not part of this decision.
6. **Caching.** The answer cache key includes the sorted layer choice. The stored pack is keyed by
   place only, so a new choice for the same district re-slices the stored pack with one new
   draft, and no new Global Risk lookup.

## Consequences

- Planners get answers about exactly the layers they chose. A test layer can be left out of a
  question.
- A layer submitted from Claude Desktop appears in the list only after a Planning lookup has
  counted it.
- Global Risk still gathers everything; the choice narrows what is drafted and shown.
- `api/global_risk_layers.py` is the one place for layer names. The Word summary's labels, this
  picker and the repeated-name guard (ADR-0032) all read it.

## Verification

- `tests/fast/test_planning_chat.py`:
  - the list offers Global Risk's layers and this Hub's own, and never a declined one;
  - chosen layers reach the focus and the draft prompt, and are stored with the evidence while the
    citations stay untouched;
  - a name not offered is refused before any call, on the chat route and on the lookup route;
  - no choice behaves as before;
  - another choice is answered again from the stored pack.
- `tests/fast/test_planning_summary.py`: only the chosen layers are listed, and a missing one says
  so.
- `tests/contract/test_permission_matrix.py`: the list route is `(401, 200, 200, 200, 403)`.
