# ADR-0059: the district summary shows the GEOGLOWS river outlook, labelled exploratory

## Status

Accepted on 4 October 2026 by the Product Owner ("show now, labelled exploratory"), answering
question 3 of
[`docs/pilot/2026-10-04_Planner_Live_Layer_Switches_and_River_Outlook_Plan.md`](../pilot/2026-10-04_Planner_Live_Layer_Switches_and_River_Outlook_Plan.md).

It widens ADR-0036 for the summary only: River Watch had been for Hub Admins and Platform Admins.
It goes ahead of decision D3 (reaches confirmed by a hydrologist), so every line says the reach
is not confirmed.

## Decision

1. **Section 7, "River outlook (GEOGLOWS, exploratory)"** in the Word summary, in English and
   Thai, after "Live reported flooding". "What this cannot tell you" becomes 8, and "Sources and
   versions" becomes 9.
2. **Which reach** (`api/river_outlook.py`, `reach_for`):
   - **Bangkok:** the district's main reach from River Watch (the reach that drains the most
     land inside the district, chosen by rule). 28 of 50 districts have one. The others get one
     line saying that GEOGLOWS does not model their canals.
   - **Nonthaburi:** Bang Bua Thong (1204) uses its exploratory canal reach 430392813. Mueang
     Nonthaburi, Bang Kruai and Pak Kret (1201, 1202, 1206) use the Chao Phraya reach 430537201.
     Bang Yai and Sai Noi have none yet.
3. **What it shows:**
   - the reach, and why it was chosen;
   - the probable river name, marked "not confirmed";
   - a line when the waterway is small;
   - the 7-day trend in words (rising, steady or falling);
   - the flow at the start, the median peak, the band where most forecasts fall, the peak time
     and the run time in Bangkok time;
   - forecast freshness;
   - a chart, drawn with numpy and zlib because the image has no plotting library. The chart
     has a band, a median line and a zero baseline, with ticks for each day.
4. **Fixed caveat:** river flow only. It is not a water level, a flood depth, street flooding or a
   warning, and GEOGLOWS has no "high" threshold here.
5. **Fetching:** through River Watch's own cache (`_current`, `_view`), so a summary adds no load
   beyond River Watch's. `outlook()` never raises. A failure becomes a stated gap ("could not be
   read for this download"), and the rest of the document is unaffected.
6. **Sources:** an available outlook adds a "river outlook (exploratory)" row with the reach and
   the run.

## Consequences

- Checked on 4 October 2026 with real GEOGLOWS data:
  - Bang Phlat: falling, peak about 8,312 m³/s;
  - Bang Bua Thong: rising, peak about 1.2 m³/s, band 0.3 to 2.5. Small flows are shown with one
    decimal.
- Both languages were rendered through Word and inspected.
- Planners now see River Watch content. When D3 confirms or replaces reaches, only `reach_for`
  and River Watch's district data change.
- Not yet checked through a signed-in download.
