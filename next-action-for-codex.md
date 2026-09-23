# Next action for Codex

**Written:** 23 September 2026, from branch `claude/vibrant-tesla-5iarzt` at `768751c`.

**Read first:** `AGENTS.md`, then `handovers.md`. Then [`docs/sig-platform-gaps.md`](docs/sig-platform-gaps.md), which holds the measurements the work below rests on.

**Do first:** Slice 1, the shelter re-import. It needs no external party, it proves the change the product owner approved, and everything a planner sees depends on it.

---

## 1. What is already on this branch

All of it passes: **444 tests, 2 skipped** (PostgreSQL only), `ruff check .` clean.

| Landed | Where |
|---|---|
| SIG access token renews itself instead of forcing a sign-in | `api/sig_connection.py`, ADR-0017 |
| Evacuation centres carry their real names and capacity | `core/shelter_import.py`, `core/shelter_labels.py`, ADR-0020 |
| A fresh sandbox reaches a working baseline in one command | `grpcli/baseline.py`, `scripts/docker-desktop.ps1 -Reset` |
| A SIG lookup survives a six-minute gather | `api/sig_jobs.py`, ADR-0021 |
| First real recordings of the SIG contract | `tests/fixtures/sig/`, `tests/contract/test_sig_recorded_contract.py` |
| A tool that profiles any delivery or contribution candidate | `tools/show_shelter_record.py` |

Nothing here has been run against the live Docker Desktop stack. That is Slice 1.

---

## 2. Slice 1 — re-import the shelters and see the names

The product owner confirmed on 23 September that `สถ_1` is the centre name and `รอง` is its capacity (ADR-0020). The importer now reads both, and composes a label that is unique inside each district. **No existing row changes**: dataset versions are immutable, so this takes effect through a new version.

This is a sandbox, so the fastest route is a full reset:

```powershell
.\scripts\docker-desktop.ps1 -Reset -AdminEmail <you> -HubAdminEmail <you>
```

`-Reset` asks for confirmation, removes the database and object volumes, rebuilds, and then runs `grpcli.baseline load`, which queues boundaries, centres and RP100 in order, waits on the worker, prints each report and activates the baseline.

**Done when.** The Planning centres list shows real Thai names, not `Evacuation centre 1..10303`; two centres called `ศาลาหมู่บ้าน` in one district are told apart by their village; capacity appears where the source has it and reads as unknown where it does not. The import report should say roughly: 10,303 labels from the source name, about 2,447 qualified by village, about 942 needing a source number, and 1,688 records with no capacity.

If the numbers differ materially from those, stop and say so — the delivered file may not be the one profiled.

---

## 3. Slice 2 — finish the two SIG tests nobody has run

### `ui_embed` with a real receipt

The only untested link in the chain. Pack `53b0ea5fd81baa6b` already exists from the 23 September Phitsanulok run. Publish a receipt from an answer and confirm the `hazard_map` iframe resolves and renders. Record what it draws — we expect buildings, per Gap 2 in the gaps document.

### `contribute_submit` with a table

The submit path was reached and correctly declined a bad manifest, so the gate works. One clean submission has not been made. A table needs **no hosting**: `csv_text` carries the data inline.

Submit ADPC's own flood depth bands. They are real, ours to publish, and once landed they make the divergence from SIG's severity classes visible on SIG's platform:

```yaml
kind: table
dataset: adpc_grp_flood_depth_bands
title: ADPC GRP flood depth display bands (Thailand)
description: >
  The five depth bands the ADPC Global Risk Platform uses to colour and describe a modelled
  flood depth raster for Thai planners. A display and communication classification, NOT a
  scientific product and not a damage function. Published to make the classification explicit,
  because it differs from this platform's own severity classes at the top of the scale: GRP's
  band 4 ends at 2.0 m where the platform's class 4 ends at 2.5 m.
source: ADPC Global Risk Platform, Thailand Hub
validation: unvalidated
license: CC-BY-4.0
vintage: "2026-09"
cadence: irregular
units: metres of flood depth
pack: risk
columns: {band: band, lower_m: lower_m, upper_m: upper_m, label: label}
usage_notes: >
  Use only to interpret an ADPC GRP flood map for Thailand. Do not cross these bands with this
  platform's severity classes without restating both: they diverge above 1.5 m.
csv_text: |
  band,lower_m,upper_m,label
  1,0,0.5,0 to 0.5 m
  2,0.5,1,0.5 to 1 m
  3,1,1.5,1 to 1.5 m
  4,1.5,2,1.5 to 2 m
  5,2,,over 2 m
```

Values come from `core/hazard_overlay.py:18-22`. Do **not** add a `countries` field — a table manifest rejects it; that is the decline we already collected.

**Warn the owner before submitting.** `contribute_status` can withdraw only a **pending** contribution. If auto-approve is on, it lands immediately and may not be removable by us.

---

## 4. Explicitly not in this slice

- **Do not submit the evacuation-centre vector layer.** It needs a public direct-download URL, and the delivery still carries the corrections in Section 6. At 5.5 MB a per-file Google Drive link is enough; object storage is not required.
- **Do not fabricate a JRC depth-damage table.** The numbers in the SERVIR runbook are illustrative. Publishing them under JRC's name would put an unverified figure on a shared platform with someone else's authority on it.
- **Do not chase the six-minute gather.** ADR-0021 survives it. Making it faster is SERVIR's.

---

## 5. What comes after, in order

| # | Slice | Size | Blocked by |
|---|---|---|---|
| 3 | Reconcile GRP and SIG district counts, or show both with their source. SIG's Mueang Nan is 1,095 km² from OpenStreetMap; ours is the delivered file | 1–2 days | Nothing |
| 4 | A `weights` contribution adding `F/M_above60` and `F/M_infant` to the flood recipe — vulnerable-weighted risk with no raster upload | 1 day | A product-owner decision on the weights and a rationale |
| 5 | Host the privacy-reduced GeoJSON and make one real `contribute_submit(kind="vector")` | 1 day | Section 6 |
| 6 | Move the token store, answer cache and lookup store to shared storage | 2–3 days | Needed before a second API instance or `--workers` |

---

## 6. Corrections owed by the data owner before anything is published

Found by profiling all 10,303 delivered records (`tools/show_shelter_record.py`). None blocks Slice 1; all of them affect what a public contribution would publish.

- **Province wrong on about 22 records.** `DDPM-SHELTER-119` to `-140` record `จันทบุรี` while their districts (เมืองชลบุรี, พนัสนิคม, พานทอง, เกาะจันทร์) are in **ชลบุรี**.
- **`#REF!` appears as a centre name** — an Excel error in the delivery. Six more names begin with `.`, `,` or `(`.
- **A coordinate is about 100 km out.** `DDPM-SHELTER-164` sits at 100.86°E with its neighbours near 99.9°E.
- **1,599 records share a coordinate** with another record, across 961 groups, 70 of which span districts.

---

## 7. Working rules

- Follow `AGENTS.md`. Commit subjects are `feat:`, `fix:`, `docs:` or `test:`, imperative and scoped.
- Run `python -m pytest` and `python -m ruff check .` before every push. The baseline here is 444 passed, 2 skipped.
- Bump the `planning.js` asset query string whenever that file changes; `tests/fast/test_auth_entry.py` pins it.
- Adding a protected route without a permission-matrix entry fails the coverage ratchet. That is the ratchet working; add the entry rather than the exemption where a test really covers it.
- Never commit `.env`, keys, tokens, `.local/`, captures with secrets, raw uploads, or the specification `.docx`.
