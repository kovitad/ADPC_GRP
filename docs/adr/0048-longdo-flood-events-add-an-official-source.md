# ADR-0048: Longdo flood events add the Department of Highways as an independent source

## Status

Accepted on 3 October 2026 for the Gate A local demo. The Product Owner asked to check the Longdo
APIs and chose three integrations: flood events, rain and forecast, and facility access by
routing. This ADR covers flood events. Weather and routing are separate decisions.

## Context

- **The feed.** `https://event.longdo.com/feed/json` is public and needs no key. On 3 October it
  held 219 events: 197 floods (`icon: "flood"`, `type: "6"`), of which 159 were contributed by
  "DOH Admin" (the Department of Highways), with passability in the title. 25 flood events were
  in Bangkok.
- **What the events carry:**
  - `start` and `stop` times with no time zone; they are Bangkok time;
  - events from 2022 onwards;
  - national coverage;
  - contributor usernames.
- **Floodboard already relays some Longdo events** under the same ID format, `longdo:<eid>`,
  with source `longdo`.

## Decision

1. **A new pilot source,** `longdo_events`, pulled every 15 minutes through the usual ingest. The
   parser (`core/flood_evidence/longdo_events.py`):
   - keeps flood events only;
   - reads times as +07:00;
   - drops events past `stop`;
   - skips points outside the pilot region rather than refusing the file, while still refusing
     the file when its shape changes.
2. **Passability.** "(ผ่านไม่ได้)" (not passable) sets `closed_all`. "(ผ่านได้)" (passable) is
   stored as `passable_stated`, meaning flooded but passable. Nothing in the feed is ever
   `cleared` or used as evidence of dry ground.
3. **Families.** "DOH Admin" becomes `doh`, `itic*` becomes `itic`, and any other contributor
   becomes `longdo_user`. Raw contributor names are never stored, and descriptions are kept only
   as a hash.
4. **Independence and confidence.** `doh`, `itic` and `longdo_user` are separate source
   families. DOH joins BMA as **official**: an official family plus another family makes an
   incident `high`, and the reason "doh_report" is shown.
5. **One report, counted once.** A Longdo event relayed by Floodboard and the same event read
   directly share a record key. The direct copy always wins, because it names the real family;
   Floodboard's `longdo` source is not counted as a family.
6. **Freshness comes from `start`.** An event that stays listed is not treated as re-confirmed.
   Many DOH statuses start early in the day and last until the next day, so by the afternoon
   they fall outside the 6-hour report window. This is deliberate and conservative. The page and
   AI will still describe them once DOH re-dates an update. Revisit this if DOH statuses should
   count until `stop`.

## Consequences

- **On deploy:** 178 regional events were stored. No open incident had a DOH or iTIC report
  within the window yet, because the morning DOH statuses were older than 6 hours.
- **Tests:**
  - only active flood events inside the region are kept;
  - Bangkok time, and expiry;
  - passable versus not passable, and never "dry";
  - families, with no usernames or text kept;
  - a changed feed shape is refused;
  - a DOH report next to a Floodboard road makes an incident `high`;
  - a relayed event counts once, as the direct copy.
- **Terms are not stated.** Credit Longdo Traffic, DOH and iTIC, and use the feed in the local
  demo only until terms are confirmed.
