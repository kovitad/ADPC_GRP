# What the shared SERVIR SIG platform does, and where it stops

**Measured:** 23 September 2026, against `https://servirplatform.sig-gis.com/mcp` and the public source at `SERVIR-AI/global-platform` commit `6479521` (the tip of `main`; every other branch is older).

This is evidence, not opinion. Each claim below is either a response we captured or a line of their source. Secret-free captures are in `tests/fixtures/sig/` and pinned by `tests/contract/test_sig_recorded_contract.py`.

## What works

Eleven tools were called. Ten returned.

| Tool | What it gave back |
|---|---|
| `platform_capabilities` | 19 tools, 2 packs, the hazard list, and every gap declared |
| `resolve_place_time` | Mueang Nan as a real admin boundary, 1,095 km² |
| `risk_weights` | The live flood recipe and 14 vulnerability layers |
| `corpus_search` / `corpus_document` | One passage with a full provenance passport; the risk library holds 1 document |
| `feeds_query` | 502 live USGS records with a staleness block |
| `contribute_status` | The whole platform holds 1 approved contribution, and it is a PDF |
| `context_get` | An honest refusal: no crop calendar for Thailand rice |
| `ui_catalog` / `ui_component` / `ui_embed` | Component inventory, real markup, a live iframe template |
| `contribute_submit` | Reached the gate and declined a bad manifest with the full field list |

Two behaviours are worth copying rather than just noting. Every feed value carries a `stale_data` block saying when it was fetched and whether it is being served stale. And a lookup with no answer returns `status: ok` with a citable statement of absence — `context_get` refuses to invent a Thai rice calendar and says any timing claim must come from a dated source instead.

## Gap 1 — a district lookup takes about six minutes

Measured end to end on 23 September for Mueang Phitsanulok District (728 km²), from GRP:

| Step | Time |
|---|---|
| Understanding the question | 2 s |
| **`assemble_pack` gather** | **347 s** |
| Writing the brief | 12 s |
| Whole answer | 367 s |

It completes and the answer is good. Four earlier attempts from a different client appeared to fail only because that client gave up at 60 s.

Nothing tells a caller how long it will take or how far along it is. GRP's side is handled (ADR-0021: the lookup runs as a background task and the browser polls it). What we cannot supply is progress.

**Ask:** is six minutes expected for a district of this size, and can a caller see progress while it runs?

## Gap 2 — a contributed layer is counted but can never be drawn

`apps/api/src/app/risk/synthesis.py:33` makes counting dynamic:

```python
def _asset_layers() -> tuple:
    """Built-in point assets plus every contributed point layer the caller may see."""
    return _ASSETS + tuple(l for l in vectors.visible() if l not in _ASSETS)
```

`:802` leaves drawing fixed:

```python
def _headline_layer(counts, risk_key):
    for layer in ("hospitals", "schools", "buildings"):
        if (c.get(key) or 0) > 0:
            return layer
    return "hospitals"
```

`build_payload` takes one `layer`, and it always comes from `_headline_layer`, so a contributed layer is counted and cited but never appears on the `hazard_map` embed. Confirmed on the Phitsanulok trace: `exposure[buildings] 4077/9939`, so buildings were drawn.

The commit that introduced contributed layers, `91df38e` (22 September), is titled *"a hub's own point layer becomes a **countable** asset"* and changed the counting loops without touching `_headline_layer`.

**This may be deliberate.** The docstring above `_headline_layer` is a considered editorial rule — lead with the most consequential class, and do not switch classes for no reason — and the published runbook only ever promises counting and citation, never drawing.

**Ask:** is the fixed list deliberate? If yes we draw our own and stop asking. If not, one function decides it.

## Gap 3 — map geometry is withheld from the pack, by design

`apps/api/src/app/mcp/assemble.py:104`:

> The viz payload is PERSISTED for the embed resolver, never returned inline: 850 KB of hazard polygons in a tool result is 850 KB in the consumer LLM's context, paying tokens to carry pixels it cannot see.

`assemble_pack` returns `viz_recorded`, a note. `publish_answer` returns a coarsened copy (`_panel_map`, simplified to about 1 km and capped at 34 KB), and `ui_embed` renders the full-fidelity version live.

The reasoning is sound and we are not contesting it. The consequence is worth planning for: **drawing data arrives only through a published receipt**, and the copy that rides the tool result is panel-scale, not decision-scale.

## What this means for GRP

- GRP draws its own map from its own database. At full precision, with Thai facility names and capacity, it is better than the panel copy for deciding which centre is flooded. That does not change if Gap 2 is closed.
- SIG's boundary for a district is OpenStreetMap's, not the delivered 928-district file. Mueang Nan is 1,095 km² to SIG. Counts must be reconciled or shown with their source; they will not match.
- SIG already publishes `vulnerability_F_above60`, `M_above60`, `F_infant` and `M_infant`, and the live flood recipe weights none of them. A vulnerable-weighted flood risk for Thailand is a `weights` contribution, not a raster upload — no reprojection, no new data.

## Still untested

- `contribute_submit` with `kind: vector` — needs the GeoJSON on a public direct-download URL.
- `ui_embed` with a real `receipt_id` — needs a published receipt. Pack `53b0ea5fd81baa6b` is available for this.
- `publish_answer`, `record_receipt`, `verify_groundedness`, `compose_run` — all downstream of a completed pack.
