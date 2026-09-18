# SIG flood hazard and exposure embed design

## Purpose

This design applies the evidence-first workflow taught in *Vulnerability Platform Training
Presentation.pptx* (especially slides 19–30 and 35–45) to the GRP Planning workspace. The deck is
training material, not an approved scientific method. Its central rule is valid here: the language
model may route and explain, but deterministic GIS produces the numbers; unsupported evidence must
stop safely.

## What the map means

Use these terms precisely in the UI, training and acceptance tests:

| Term | Meaning in this increment |
|---|---|
| Flood hazard | A raster class representing mapped flood depth/intensity for a stated scenario. |
| Exposure | A school, hospital, building or road intersects a mapped hazard class. |
| Vulnerability | Susceptibility and coping capacity. SIG Risk v0 does not provide this weighting. |
| Risk | Consequence derived from hazard, exposure and vulnerability under an approved method. Not yet produced by this flow. |

Therefore the component is labelled **Flood hazard and asset exposure**. “Not exposed under this
scenario” never means safe, and an exposed asset is not automatically damaged or unusable.

## Governed request flow

1. The person names or confirms a unique Thailand administrative district. A model-proposed or
   approximate area cannot start the lookup.
2. GRP calls `assemble_pack(pack="risk", place=..., hazard="flood")` using the person’s in-memory
   SERVIR token. SIG performs the GIS overlay and returns evidence, gaps and a trace.
3. GRP verifies `aoi[...] via admin boundary` and the requested district name before showing numbers.
4. The GRP AI gateway drafts only from the returned citations. Until publication it is visibly an
   unverified draft and no SIG map is displayed.
5. After a separate two-step public-record confirmation, GRP calls `publish_answer`. Only
   `status="ok"` with a `receipt_id` can continue.
6. GRP calls `ui_embed(component="hazard_map", receipt_id=...)`. The browser loads the returned live
   SIG component; GRP does not redraw, copy or modify the hazard cells.
7. If the embed is absent or invalid, retain the cited answer and receipt but disable the map. Never
   substitute an illustrative layer.

## Interface and trust cues

The embedded map occupies the map canvas while the evidence drawer remains available. Its header
shows the confirmed area, receipt ID and the education note above. The evidence drawer exposes source
cards, declared gaps and both SIG and GRP execution traces. Severity labels must come from SIG’s
receipt-bound component or evidence; GRP must not hard-code a different scientific legend.

SIG declares four meaningful outcomes: `ok`, `declined`, `empty` and `blocked`. Only `ok` can produce
the map. For all other outcomes, show SIG’s plain-language note and no figures, receipt or iframe.

## Security boundary

- Accept only HTTPS URLs on the configured SIG host whose path is
  `/embed/hazard_map/{receipt-bound-id}`. Treat all MCP output as untrusted.
- Render with `sandbox="allow-scripts allow-same-origin"`, `referrerpolicy="no-referrer"` and a
  descriptive iframe title. Do not put access tokens, private Hub data or coordinates in the URL.
- Keep public receipt creation off by default and explain its permanence before publication.
- Before staging, set an explicit Content Security Policy `frame-src` for the contracted SIG origin;
  do not use a wildcard.

## Verification and rollout

Fast tests cover the gate sequence, exact host/path allow-list, iframe restrictions, area mismatch and
blocked publication. Add a sanitized real `ui_embed` fixture to contract tests once DEP-01 supplies
the supported service client. Browser acceptance must cover `ok`, missing embed, blocked gate and
session reauthentication. This remains local-only under ADR-0004 until the Technical Lead approves
the MCP contract, CSP, data lineage and scientific terminology for staging.
