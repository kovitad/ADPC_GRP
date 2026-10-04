# Questions for the Global Risk maintainers: a contributed live flood feed

**Date:** 4 October 2026
**From:** the GRP Bangkok flood pilot team, ADPC
**Status:** draft for the Product Owner to send. Nothing has been sent or submitted.

## Context

We want to contribute a live feed of Bangkok flood incidents. It follows the pattern of
`usgs_quakes_m45_month`: `adapter: generic_json`, `residency: external call-out`. Our server
serves `feed.json`, and Global Risk keeps only the manifest. Drafts are in
`docs/pilot/global_risk_manifests/`. The data is fetched live; we upload no data.

## Questions

1. **The feed kind.** Does `contribute_submit(kind="feed")` accept a `generic_json` manifest
   with an external `fetch.url`? Which fields are required beyond those in the USGS entry?
2. **Staging.** The tool says a clean submission is staged and visible only to the contributor
   and reviewers until approved. Can we test a staged feed with `feeds_query` before review? Can
   we withdraw it and resubmit under the **same** dataset name, or is a name spent once
   submitted?
3. **Two lists from one document.** Our `feed.json` has `records` (incidents) and `districts`
   (one summary per district). May two manifests point at the same URL with different
   `records_path` values?
4. **Fields.** Does `fields` accept list values (such as `source_families`) and nested objects
   (such as `facilities_nearby`)? Or should we flatten them to strings and numbers?
5. **Freshness.** Our feed carries `valid_until`. Does Global Risk show staleness from
   `as_of_field`, or can it also respect a `valid_until` field?
6. **Call-out behaviour.** How often does Global Risk fetch an external call-out, and with what
   timeout? Is the response cached? What happens when the fetch fails: last good copy, or a
   declared gap?
7. **Receipts.** When a brief cites a live feed, does the receipt keep the fetched bytes or their
   hash, so the answer can be replayed after the feed has changed?
8. **Access.** Must the URL be anonymous, or can Global Risk send a fixed header or token? We
   would rather keep the route behind a token if that is supported.
9. **Validation label.** Is `validation: unvalidated` right for derived crowd and agency
   reports? Does a later move to `single-agency`, once BMA confirms, need a new submission?
10. **Hazards.** Is `hazards: [flood, flashflood]` right for urban road flooding, or is there a
    better tag?
