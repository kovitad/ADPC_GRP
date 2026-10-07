# Questions for the Global Risk maintainers: a contributed live flood feed

**Date:** 4 October 2026 (revised the same day after reading the platform source)
**From:** the GRP Bangkok flood pilot team, ADPC
**Status:** draft for the Product Owner to send. Nothing has been sent or submitted.

## Context

We want to contribute two live feeds for Bangkok flooding:

- `bangkok_flood_districts_live`, one record per district (always 50);
- `bangkok_flood_incidents_live`, one record per open incident.

Both use `adapter: generic_json` and `residency: external call-out`, like
`usgs_quakes_m45_month`. The drafts are in `docs/pilot/global_risk_manifests/`. We read
`global-platform` at commit `a8a43c2` first, so these questions are only the points the code does
not settle.

## Questions

1. **Cache time for a live feed (blocking).** `_adapt_generic_json` goes through
   `climate_indices.cached`, whose TTL is 6 hours. That suits monthly indices, but our data
   changes every 10 to 20 minutes.
   - Could a feed declare its own cache time, for example an optional `cache_seconds` (minimum
     60), or one derived from `cadence`?
   - Unknown manifest fields are refused today, so we cannot add it ourselves.
2. **An empty list is a valid answer.** On a dry day our incidents list is empty. Today
   `generic_json` treats an empty list as "upstream unavailable": it serves the last good copy
   marked stale, so readers see old incidents instead of "no flooding". The submission test also
   refuses it.
   - Could a manifest declare `empty_ok: true`, so an empty list is answered as zero records and
     not as a failure?
3. **Two feeds from one URL.** Both manifests point at the same `feed.json`, with
   `records_path` set to `districts` and `records` respectively. We see nothing against this. Is
   it acceptable? Note that the cache is keyed per contribution, so the URL would be fetched
   twice.
4. **Place filtering in risk briefs.** `_pack_feeds` filters feeds by `hazards` only, so a flood
   brief for any country would cite our Bangkok feed. Could `countries` (or a bounding box)
   filter risk briefs as well? Until then, our `usage_notes` begin "Bangkok only".
5. **Replaying a live citation.** A receipt keeps `query_receipt` ("records via URL"), not the
   fetched rows or their hash. Is it planned to keep the rows, or a hash with `retrieved_at`, so
   an answer can be replayed after the feed has changed?
6. **Validation label.** Is `validation: unvalidated` right for derived crowd and agency reports?
   If BMA later confirms the data, does moving to `single-agency` need a new submission, given
   that contributions never overwrite?
7. **Cadence wording.** The field help lists `monthly | daily | annual | irregular`, but the USGS
   row uses `continuous`. Which word should we use for data that updates every 10 to 20 minutes?
8. **Review timing.** Roughly how long does review take? Can a reviewer test a staged feed on a
   flooding day, so the incidents feed is reviewed with real records?

## Already answered by the code (no need to ask)

- **The URL must be anonymous:** the fetch sends no custom headers. It must not resolve to a
  private address and must not embed credentials. `http` is accepted, but we will use `https`.
- **Name reuse:** withdrawing a staged feed frees its name; approval spends it.
- **Field values:** `fields` values are dot paths into each record; lists and nested objects pass
  through.
- **Ordering:** records are sorted by `as_of_field`, the newest `limit` are returned (12 by
  default), and a risk brief asks for 3.
- **Submission test:** the URL is fetched once at submission; a dead URL or an empty list is
  refused.
