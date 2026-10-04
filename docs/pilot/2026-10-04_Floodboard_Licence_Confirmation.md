# Note to Floodboard: confirming credit for derived flood incidents

**Date:** 4 October 2026
**From:** the SERVIR Global Risk Platform (GRP) pilot team, ADPC
**Status:** draft for the Product Owner to send. Nothing has been sent from GRP.

## Message

Hello Floodboard team,

ADPC's Global Risk Platform (GRP) runs a flood pilot for Bangkok, using your open exports
(`roads.geojson` and reports) under CC BY 4.0. Thank you for publishing them.

We plan to publish a small live feed of **flood incidents derived from your data** to the SERVIR
Global Risk Platform, so planners can read it through its tools. Each incident groups nearby
flooded roads and gives:

- a confidence word with reasons, and the source types behind it (for example "traffy",
  "crowd" or "bma");
- public road names, the district, a centre point and a box;
- the deepest reported depth, when one was given, and a report count.

The feed does **not** include report text, links, photos, usernames or your per-vehicle verdicts.

We would credit you in every copy as:

> Derived from Floodboard (floodboard.org), CC BY 4.0. Grouped and rated by the ADPC GRP Bangkok
> flood pilot; not a Floodboard product.

Could you confirm three things?

1. Is this credit wording right, or would you like different wording or a link?
2. Is CC BY 4.0 still the licence for the roads and reports exports?
3. Is there a polling interval you would like us to stay above? We fetch about every 20 minutes.

Kind regards,
[Product Owner name], ADPC

## Notes for the Product Owner

- The pilot config already records the exports as CC BY 4.0 with redistribution allowed with
  attribution. This note confirms the wording and does not ask for permission.
- Floodboard's `robots.txt` disallows `/api/cam/`. GRP does not use that path.
