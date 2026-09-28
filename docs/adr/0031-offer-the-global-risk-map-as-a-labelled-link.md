# ADR-0031: Offer Global Risk's receipt map as a labelled link, and let planners download it

## Status

Accepted on 28 September 2026 by the Product Owner ("Link, labelled unverified"). **Amends
ADR-0014 decision 4-5 only for an outside link.** The in-page embed is still withheld unless
Global Risk names exactly one supported flood-hazard layer.

## Context

After a public receipt, GRP calls `ui_embed(component="hazard_map", receipt_id=...)`. A live call
on 28 September 2026 returned:

```json
{
  "status": "ok",
  "component": "hazard_map",
  "binds": "receipt_id",
  "renders": "AOI, severity-tagged assets and the clipped hazard layer from the receipt's recorded evidence pack",
  "src": "https://servirplatform.sig-gis.com/?embed=hazard_map&receipt_id={receipt_id}"
}
```

Two things follow:

1. The link form is `/?embed=hazard_map&receipt_id=<id>`, not the `/embed/hazard_map/<id>` that
   `api/sig_evidence.py` accepted. GRP therefore rejected every real map link.
2. The answer names no displayed layer. Under ADR-0014 the map is withheld, because Global Risk
   changed the meaning of `severity` from water-depth class to vulnerability-weighted risk (G-17).
   The map may colour assets by an unapproved risk recipe without GRP knowing.

The owner asked for the map to be usable: planners should be able to open it and download it.

## Decision

1. GRP accepts both link forms on the configured Global Risk host. The live query form must name
   exactly the receipt GRP just published; an unfilled `{receipt_id}` template is rejected.
2. The publish response carries `map_link` (the verified embed URL, or else the receipt-bound
   link) and `map_link_verified`. `map_url`, which the page embeds, is unchanged: it is set only
   when ADR-0014's layer check passes.
3. An unverified link is shown as "Open Global Risk map ↗" in the chat answer and the evidence
   panel. It opens on Global Risk in a new tab, never inside GRP. It carries the caveat that GRP
   could not confirm whether its colours show flood depth or vulnerability-weighted risk.
4. Planners can copy the link with the receipt and caveat, and download:
   - **Global Risk map link (.html):** a small page that opens the live map. It holds the place,
     receipt, pack ID, date and caveat, and no verdict, so the map still resolves from Global Risk
     each time it opens (`ui_embed`'s own guarantee).
   - **Evidence table (.csv):** the exposed-of-total figures the panel shows, the citations and the
     declared gaps. It excludes `at_risk`, `by_risk` and `severity` fields. Cells beginning with
     `= + - @` are prefixed so a spreadsheet does not run them as formulas.
5. A map image is not offered. A browser cannot capture another site's map; that needs an export
   from Global Risk.

## Consequences

- Planners can reach Global Risk's map for every published receipt, but GRP does not vouch for
  what it colours. The trace records "withheld: displayed layer not verified; link offered
  unverified".
- If Global Risk adds a typed displayed-layer field, the existing check embeds the map in the page
  with no further change.
- Ask Global Risk for: a typed `displayed_layer` in `ui_embed`, and a PNG or GeoTIFF export for a
  receipt.

## Verification

- `test_embed_url_accepts_the_live_query_form_bound_to_the_receipt` covers the live form, a
  different receipt, the unfilled template, another component and another host.
- `test_the_live_embed_is_offered_as_an_unverified_link_not_embedded` proves `map_url` stays empty
  while `map_link` is offered.
- Not yet seen with a real receipt in a browser: no receipt has been published from the desktop
  stack.
