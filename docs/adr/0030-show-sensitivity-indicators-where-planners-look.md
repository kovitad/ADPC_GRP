# ADR-0030: Show the sensitivity indicators where planners look, without turning them into counts

## Status

Accepted on 25 September 2026 by the Product Owner ("Full map treatment" and "Prepare, you approve
submit"). Implements display only. **Does not amend ADR-0015 or DEP-07:** no GRP calculation,
classification, score or count is derived from these layers.

## Context

The ADPC delivery holds three national rasters at 12.5 m in EPSG:32647, imported as display-only
layers under ADR-0015 (`docs/vulnerable-people-data-proof.md`):

| Layer | Cell value | Measured |
| --- | --- | --- |
| Child sensitivity | continuous 0-1 index, NaN outside | 59% of cells exactly 0 nationally |
| Older-person sensitivity | continuous 0-1 index, NaN outside | 59% of cells exactly 0 nationally |
| Disability support indicator | ordinal class 1-4, nodata 255 | 40,950,041 sampled cells class 1; 1,101 class 2; 119 class 3; 14 class 4 |

They were reachable only as unlabelled toggles under Layers, off by default, with no legend. The
disability preview's stretch is 1.0-1.000005, so it draws as one flat colour.

The Product Owner asked for the layers to be used. Before deciding whether a centre could show its
own value, every current evacuation centre (10,303) was sampled on 25 September:

| Layer | NaN at centre | Exactly 0 | Non-zero quartiles (25/50/75/95) | 250 m mean agrees? |
| --- | --- | --- | --- | --- |
| Child | 0.4% | 3.3% | 0.143 / 0.31 / 0.476 / 0.786 | yes, quartiles within 0.02 |
| Older-person | 0.4% | 1.5% | 0.325 / 0.508 / 0.71 / 1.0 | yes, quartiles within 0.02 |

Centres sit in settled areas, so the national share of zeros does not carry over to them, and a
point value is representative of its 250 m neighbourhood. No radius or smoothing method is needed.

## Decision

1. **Child and older-person sensitivity are shown as relative indicators.**
   - Legend: "Lower to higher, relative index. Not a number of people. About 1.4 km per pixel."
   - A mask dims everything outside the selected district. The mask sits above sensitivity and below
     flood and the centre markers, each in its own Leaflet pane.
2. **Each centre shows the source value at its location, as context only.** The values come from
   `python -m grpcli.sensitivity build`, which samples outside the request path into
   `centre_indicator_value`. They are shown as the source-native value, labelled as a relative
   index. NaN is shown as "outside the indicator's coverage". An exact 0 is shown as "0 (lowest in
   the source)" with the same relative-index caveat, never as "no children".
3. **These values never enter** an assessment, a centre status or classification, sorting,
   filtering, a risk score, or any AI prompt. A test checks that the explain and chat paths do not
   read `centre_indicator_value`.
4. **The disability layer is withheld from planners on the server.** `/maps/layers` marks it
   `planner_status: "withheld"` with a reason, and the Planning page shows the reason instead of a
   toggle. It stays visible to Admins in the data library.
5. **The assistant is told the indicators exist, without numbers.** When a question mentions
   children, older people, disability or vulnerability, one GRP citation states which relative
   indicators are on the map and that no count of vulnerable people exists. The citation carries no
   digits, so `cited_local_numbers` cannot turn it into a withheld receipt.
6. **Contribution to Global Risk is prepared, not submitted.** Child and older-person sensitivity
   are converted to EPSG:4326 GeoTIFFs with nodata declared, averaged to a stated coarser
   resolution, with a manifest that says GRP derived them. Submission waits for the Product Owner to
   host the files at a public URL and say go. Disability is not prepared.

## Consequences

- Planners can see where sensitivity is relatively higher and read it at a centre, but nothing tells
  them how many vulnerable people are there, because nothing can.
- A future method under DEP-07 would replace decision 3, and would need its own ADR.
- The preview stays at about 1.4 km per pixel. A sharper per-district render is a separate
  worker-side job if planners need it.
