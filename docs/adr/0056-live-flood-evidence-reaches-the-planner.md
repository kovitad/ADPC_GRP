# ADR-0056: live flood evidence reaches the Planner for Bangkok

## Status

Steps 1-4 accepted and built on 4 October 2026 at the Product Owner's request ("go ahead with
step 1/2/3/4"). The owner decided D7 (rain may appear, labelled as context) and D8 (the fixed
no-warnings wording) on 4 October 2026. The plan is
[`docs/pilot/2026-10-04_Planner_Live_Flood_Integration_Plan.md`](../pilot/2026-10-04_Planner_Live_Flood_Integration_Plan.md).
Decision D2 (officer checks for Planners) is still open.

## Context

- The Planner works on GRP boundaries: districts such as `1030` and sub-districts such as
  `103005`. The flood pilot uses the same district codes.
- Incidents carried no district. The research archive approximated districts from each incident's
  box. The feed plan would have computed them per request, which is spatial work in a web request.

## Decision

1. **District codes are computed once, in the worker.**
   - `update_incidents` stores `district_codes` in each incident's summary. These are every demo
     district that any vertex of the incident's roads falls in, checked box-first
     (`geo.district_codes`).
   - The Planner filter, the feed and the archive read them. None of them computes geometry in a
     request.
   - Incidents processed before this change get codes at their next snapshot. Until then the
     archive marks its box approximation with `district_codes_basis: box_approx`.
2. **The live layer on the Planner map** (step 2).
   - `GET /api/v1/maps/live-flood?boundary_id=&hub_code=` is `protected` and needs a planning
     role (`planner_membership`). It reads `core/flood_evidence/planner_layer.py`.
   - It returns the stored open incidents whose `district_codes` include the area's district,
     their roads from the latest snapshot, the snapshot time, a note and the Floodboard credit.
   - It does no spatial work.
   - It answers `available: false` with a plain reason outside Bangkok, for a Hub the pilot does
     not include, or for a district outside the demo area.
   - A sub-district rolls up to its district (`rolled_up_from`). Officer checks and verification
     fields are never returned (D2 is open).
   - On the page, the switch "Reported flooding on roads (live, not a flood map)" appears only
     for Bangkok areas. Roads are coloured by confidence word, receding ones are dashed, and the
     legend is separate from the flood scenario. It refreshes every five minutes while on.
3. **Live facts in Planner answers** (step 3).
   - The router has a `live_flood` mode for questions about flooding now, reported flooding or
     early warning, for a Bangkok area. Before this, "current conditions" went to `cannot`.
   - The area is the selected Bangkok boundary, or a Bangkok district named in the message.
     Anything else gets `live_flood_unavailable` with a plain reason.
   - Facts come from the pilot's own bundle (`build_facts`) for the district, through
     `core/flood_evidence/planner_answer.py`. Officer checks, officer-confirmed access and the
     officer-check count are removed (D2). Rain stays, labelled as context (D7).
   - AI wording uses the pilot's instructions and gate (ADR-0043). If it fails the gate, the
     computed answer is shown.
   - Every answer, computed or AI, ends with the fixed D8 text. It is appended after the gate and
     never written by the model:
     - EN: "GRP does not issue flood warnings. For official warnings, follow the Thai
       Meteorological Department (TMD), the Department of Disaster Prevention and Mitigation
       (DDPM) and the Bangkok Metropolitan Administration (BMA)."
     - TH: the same in Thai (`NO_WARNINGS["th"]`). Thai questions get Thai text.
   - **Live answers are never cached**, so a repeat question always uses the newest snapshot.
   - A "Show live reported flooding on the map" button turns on the step 2 layer for the same
     district.
   - Known limit: incidents in the "check first" list keep the pilot's order, which ranks
     incidents an officer saw as dry first. The check itself is not shown.
4. **DDPM evacuation centres in the facility check** (step 4).
   - `core/flood_evidence/ddpm_shelters.py` adds the current platform-baseline shelter version
     (`evacuation_centers`, `is_current`, no Hub) for the demo districts. They are read from the
     database at check time and never copied into the repository (ADR-0022).
   - They are typed `evacuation_centre`, with IDs `ddpm:<feature id>` and a source naming the
     data library version.
   - `pilot_assets` (OSM plus DDPM) replaces the OSM-only registry in exposure, the briefing,
     facility reviews and the archive.
   - The same rules apply (ADR-0040): "flooding reported nearby", never "flooded", and access is
     never assumed. Answers label a shelter's source as DDPM.
   - 8 centres on 4 October 2026, in districts 1003 (3), 1022, 1023, 1028, 1035 and 1044, which
     makes 1,075 facilities in all. A centre is "not assessed" until the next roads snapshot
     after deployment.
5. **Live section in the district summary, in Thai or English** (4 October 2026, the Product
   Owner's request).
   - `core/flood_evidence/summary_live.py` builds section 6 "Live reported flooding (not part of
     this assessment)", placed after the Global Risk evidence. It holds:
     - the snapshot time, with a warning if it is over 2 hours old;
     - counts by confidence word and what changed in the last hour;
     - the incidents, the facilities and DDPM centres with flooding reported nearby, and rain
       where tracked;
     - the nearest camera to each listed incident;
     - the Floodboard credit, and the D8 text in English and Thai.
   - It uses `live_facts`, the same facts as the live answers, with officer fields removed.
     Outside Bangkok it is one plain line.
   - **Camera pictures.** Up to 4 pictures come from bmatraffic cameras through the relay. Each
     is credited "BMA traffic camera (bmatraffic.com)" with its time. GRP keeps no copy; the
     picture lives only in the downloaded document.
     - The owner chose pictures in every summary, not only the local demo.
     - The owner reported on 4 October 2026 that **BMA confirmed the camera pictures are public
       data anyone may use**. A written confirmation should be kept on file.
     - This widens ADR-0051's "local demo only" scope for the summary. A camera that does not
       answer is listed without a picture.
   - **Language.** `POST /api/v1/planning/summary.docx` takes `lang` (`en` or `th`). Every fixed
     text in `core/summary_docx.py` is translated with the same wording rules: never "safe"
     (ปลอดภัย is used only in the "does not certify that any place is safe" line). Texts from data
     sources and Global Risk stay as written, and the Thai document says so. The page has a
     "ดาวน์โหลดสรุป (ไทย)" button.
   - The assessment section, its result and its receipt are unchanged.
6. **Facilities and cameras on the live map (W7b)**, built 4 October 2026 to
   `docs/pilot/2026-10-04_Planner_Live_Map_UX_Design.md`, with the recommended answers: both on
   by default, cameras grouped at district zoom, and the "Live now" list included.
   - **API.** `GET /api/v1/maps/live-flood` adds `facilities` and `cameras`.
     - `facilities`: `potentially_exposed` in the district, DDPM centres first. Officer-confirmed
       access is replaced by the computed state (D2).
     - `cameras`: within 400 m of the district's incident roads, deduplicated, at most 40.
       `picture_url` uses the relay route, only when `BMATRAFFIC_RELAY_ENABLED` is on and the
       camera is a bmatraffic camera.
     - On real data each response took about 1.3 s and was under 90 KB.
   - **Map.** A "Live (Bangkok)" group shows the snapshot time (amber after 2 hours) and two
     remembered sub-switches with counts.
     - DDPM centres get an orange ring and badge over their existing pin, not a second pin.
       Other facilities get ringed letters.
     - Cameras show a green dot when GRP can show a picture. They are grouped per incident below
       zoom 15.
     - Opening an incident fades unrelated items.
   - **Cards.** One pattern, built from DOM nodes only.
     - The incident card gives the confidence and its reasons in plain words, and buttons for the
       nearby facilities and cameras.
     - The facility card gives the distance and access "not confirmed"; the DDPM card also links
       to the centre's assessment details.
     - The camera card shows a picture every 10 s, with a pause; it stops on close or after
       10 minutes.
     - On phones (600 px or narrower) cards open in a bottom sheet outside the map.
   - **"Live now" list** under the switches, usable with a keyboard.
7. **Rules for the later steps** (from the plan):
   - live data never enters a stored assessment or its receipt;
   - the map layer is "Reported flooding on roads (live, not a flood map)";
   - a sub-district shows its parent district's live facts, and says so;
   - answers never issue warnings;
   - a cached Planner answer that includes live facts is keyed by the incident run's
     `snapshot_at`.

## Consequences

- Each roads snapshot does one more box-first vertex check per incident, which is small next to
  grouping (0.8 s for 44 incidents across the city).
- An incident that crosses a district border appears in both districts' counts. District sums
  can therefore exceed the city total, and reports must say so.
