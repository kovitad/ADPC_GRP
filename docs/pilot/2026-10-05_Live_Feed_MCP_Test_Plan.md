# Live flood feed on Global Risk: the tunnel test and the MCP calls

Status: **run on 5 October 2026 with the owner's yes. The feed was auto-approved and is live** (see
"What happened").

## Why a tunnel

Global Risk's server fetches a contributed feed itself (`contrib/fetch_policy.py`):
- `http` or `https` is accepted, and so is a port;
- the address must be public (`is_global`) and anonymous;
- it is fetched once at submission, and again on reads, with a six-hour cache.

The laptop is `192.168.2.125` behind a router (public `58.137.55.90`), and Docker publishes the
API on `127.0.0.1` only. A temporary tunnel gives a public `https` address with no router or
firewall change. For a permanent feed, use a host with a static IP, such as Lightsail with 2 GB.

## What is exposed, and what is not

```text
Global Risk ──https──▶ tunnel ──▶ grpcli.feed_relay :8090 ──▶ API :8000 /api/v1/public/flood/bangkok/feed.json
                                   (answers /feed.json only)    (404 unless FLOOD_FEED_PUBLIC=true)
```

- **Exposed:** only `/feed.json`. Sign-in, Admin, the Planner and every other route stay on
  `127.0.0.1`.
- **The feed holds:** aggregated incidents and districts. It has no names, text, report IDs,
  officer checks, camera data or DDPM records.

## Steps

| # | Step | Command or call | Needs the owner's yes |
| --- | --- | --- | --- |
| 1 | Feed builder and routes | built and tested (ADR-0052) | no |
| 2 | Check against Global Risk's own validator and reader | done: both manifests pass, sorted by our timestamps | no |
| 3 | Install the tunnel tool | `winget install Cloudflare.cloudflared` | **yes** (download) |
| 4 | Switch the public feed on | `$env:FLOOD_FEED_PUBLIC="true"; .\scripts\docker-desktop.ps1` | **yes** |
| 5 | Start the relay | `python -m grpcli.feed_relay --port 8090` | no (local) |
| 6 | Open the tunnel | `cloudflared tunnel --url http://127.0.0.1:8090`, which prints `https://<random>.trycloudflare.com` | **yes** (publishes) |
| 7 | Put the URL in the districts manifest, remove `_status` | edit `bangkok_flood_districts_live.json` | no |
| 8 | Stage the districts feed | `contribute_submit(kind="feed", manifest=…)` | **yes** (submits) |
| 9 | Try it (only we and the reviewers see it) | the MCP calls below | no |
| 10 | Withdraw and close | `contribute_status(action="withdraw", contribution_id=…)`, then stop the tunnel and the relay, and switch the feed off | no |

A quick tunnel's address changes every time it starts, so this is a staged test only. Approval
needs a permanent host (Step 5 of the feed plan).

## The MCP calls, and what each one shows

1. **`contribute_submit(kind="feed", manifest=<districts manifest>)`**
   - Global Risk fetches our URL once, through `generic_json`.
   - A clean answer is staged and returns a sample: the count, `as_of` and the last record (the
     most concerning district).
2. **`contribute_status()`**: our contribution, with its `pending` state and ID.
3. **`feeds_query("bangkok_flood_districts_live")`**: the 12 most concerning districts, newest
   last, with the source, `as_of`, `record_order` ("sorted newest-last by … as_of") and
   `stale_data`.
4. **`feeds_query("bangkok_flood_districts_live", {"limit": 56})`**: every district. Districts
   with no incident say 0; they are never missing.
5. **`assemble_pack(pack="risk", place="Bangkok", hazard="flood")`**
   - The risk pack cites every feed whose `hazards` include `flood`, so our staged feed should
     appear as a numbered citation beside the static flood layers.
   - This is the "awesome" test: a planner anywhere asks a flood question and gets today's
     Bangkok situation, with its source and age.
6. **Draft, then `publish_answer(pack_id, draft)`**
   - This gates the draft against the pack and mints a receipt with an evidence view.
   - An example question: "Which Bangkok districts have reported flooding now, and which have
     schools or hospitals nearby?"
7. **`contribute_status(action="withdraw", contribution_id=…)`**: removes the staged feed. The
   name is not used up until it is approved.

The incidents feed is submitted only on a day with flooding, because an empty list is refused.
It is submitted after the districts feed.

## What to watch

- **Six-hour cache.** A second `feeds_query` within six hours may serve the same copy. Each
  record's `valid_until` shows its age.
- **Not filtered by place.** Risk briefs pick feeds by hazard only, so a flood question about
  another country could cite us. `usage_notes` starts "Bangkok and Nonthaburi only"
  (maintainer question 4).
- **Laptop uptime.** If the laptop, Docker or the tunnel stops, the next fetch fails and Global
  Risk serves the cached copy marked stale, or declines.

## What happened (5 October 2026)

- **The tunnel** `https://areas-barry-beyond-res.trycloudflare.com/feed.json` served only the
  feed; `/api/v1/me` through the tunnel answered 404.
- **`contribute_submit`** returned contribution `47b51ee65c4659f9`, but **auto-approved**:
  "this deployment lands contributions without review" (`GRP_AUTO_APPROVE` on). The feed was
  live for every caller at once, and `conf/feeds/bangkok_flood_districts_live.yml` was written
  with the temporary tunnel URL. The plan had assumed staging with review.
- **`feeds_query`** returned the 12 most concerning districts, sorted by `as_of`, not from cache.
  Lat Krabang (11 active, high) and Prawet (6 active, high) were last.
- **`assemble_pack(pack="risk", place="Bangkok", hazard="flood")`** cited the live feed as [4],
  "pulled at pack time", beside the JRC 100-year flood exposure for 173 hospitals and 684
  schools.
- **`publish_answer`** passed. Receipt `25e8f83c33fa518f`:
  <https://servirplatform.sig-gis.com/api/resolve/receipt/25e8f83c33fa518f>.
- **Withdraw was refused:** "approved, not pending". Only a Global Risk maintainer can retire
  the feed or re-point it at a permanent host. The name `bangkok_flood_districts_live` is now
  taken.
- **Lesson:** before submitting to this deployment, check whether it auto-approves. Submit only
  a URL that will stay up.
