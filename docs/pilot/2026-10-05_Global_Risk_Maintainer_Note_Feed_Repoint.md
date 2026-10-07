# Draft note to the Global Risk maintainers: re-point or remove a test feed

Status: draft, 5 October 2026. For the owner to send. Not sent.

---

**Subject:** Test feed `bangkok_flood_districts_live` landed by auto-approve: please re-point or remove it

Hello,

On 5 October 2026 (02:08 UTC) we submitted a live feed through `contribute_submit`, expecting it
to be staged for review:

- dataset: `bangkok_flood_districts_live`;
- contribution: `47b51ee65c4659f9`.

The deployment has `GRP_AUTO_APPROVE` on, so it was approved at once, and
`conf/feeds/bangkok_flood_districts_live.yml` was written with a **temporary test address**
(`https://areas-barry-beyond-res.trycloudflare.com/feed.json`). That address is now closed, so
the feed will serve a stale copy, then decline.

`contribute_status(action="withdraw")` refuses it ("approved, not pending"). Could you please do
one of these?

1. **Remove the feed** and free the name, so we can submit it again from a permanent host. This
   is our preference.
2. **Or keep it, and change its `fetch.url`** to our permanent address once we send it.

**About the feed:**
- one record per district of Bangkok and Nonthaburi (56);
- active and receding flood incidents, the worst confidence word, and counts of OpenStreetMap
  schools, hospitals and clinics with flooding reported nearby;
- built from Floodboard (CC BY 4.0) by the ADPC GRP Bangkok flood pilot;
- no personal data.

It worked well in the test: `feeds_query` sorted it by `as_of`, and `assemble_pack(risk, Bangkok,
flood)` cited it as a pulled source (receipt `25e8f83c33fa518f`).

Three questions came out of the test:

1. **Auto-approve.** Is auto-approve meant to stay on for this deployment? If so, could the
   `contribute_submit` reply say so before landing, or offer a dry run?
2. **Cache length.** Could a contributed feed declare its own cache time? `generic_json` caches
   for six hours, which is long for a feed that changes every 10 minutes.
3. **Empty lists.** Could an empty `records` list be accepted as a valid answer ("no incidents
   now"), for our incidents feed?

Thank you,
[name], ADPC
