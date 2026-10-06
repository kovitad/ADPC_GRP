# ADR-0067: Planning offers an optional perspective scenario view

## Status

Accepted on 6 October 2026 for managed flood-depth display in Planning.

This decision does not create a 3D flood model, infer water volume or height, change an assessment,
or approve any live observation or warning use.

## Context

Planning already draws the managed colour-coded flood-depth preview as a georeferenced image in a
Leaflet map. A perspective view can help a planner orient that same scenario among streets and
buildings, but extruding the raster would falsely imply modelled water volume and could make visual
height look like depth.

The normal 2D map must remain usable when WebGL or the perspective basemap is unavailable. The
scenario image is protected and must still be obtained from GRP with the signed-in browser rather
than exposed through a new public URL.

## Decision

1. Keep the Leaflet map as the default and add an explicit **3D scenario** option only after a
   managed flood-depth image has loaded and the browser reports WebGL support.
2. Lazily create a MapLibre view. Use OpenFreeMap's Liberty style for orientation and its available
   building extrusions. This external context is not assessment evidence.
3. Add the exact same GRP PNG and bounds to MapLibre as a flat image source with the same opacity.
   Never extrude, interpolate or otherwise turn raster colour into geometry.
4. Fit the selected district or sub-district when one exists; otherwise fit the scenario extent.
   Provide perspective, top-down and reset controls.
5. Label the view as a modelled planning scenario, not live flooding. State that building height is
   context, flood depth remains draped on the ground and no location is certified safe.
6. If MapLibre, WebGL or the external style is unavailable, retain the 2D map. The perspective mode
   adds no API, storage, assessment or worker behavior.

## Consequences

- Planners can inspect the approved display raster in perspective without changing its scientific
  meaning or lineage.
- Building completeness and height depend on OpenStreetMap/OpenFreeMap and may be absent or
  approximate. They must not be treated as GRP-managed evidence.
- The view needs browser access to the pinned MapLibre asset and OpenFreeMap services. A deployment
  that disallows those dependencies still has the existing 2D workflow.
- A future production hardening slice may self-host the JavaScript/style/vector dependencies and
  align the deployment content-security policy. That does not justify changing scenario semantics.
