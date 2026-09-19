# Data proof: what the Thailand files do on real districts

**Run:** 18 September 2026 with `python -m tools.prove_dataset --district "<name>"`.
**Scope:** a read-only check of the delivered files. No database, no GRP result, nothing approved. It exists to show whether the data behaves and to give the Scientific and Data Authority real numbers for the decisions in [`thailand-dataset-inventory.md`](thailand-dataset-inventory.md).

## 1. What the proof does

1. Finds one district in the boundary shapefile (Thai or English name).
2. Loads all 10,303 shelters and keeps those **inside that boundary**, by geometry.
3. Samples the RP100 flood depth at each shelter, reading one pixel per point.
4. Prints the counts twice: once reading "no value" as **not flooded**, once as **unknown** (what GRP does today).

## 2. Results

| District | Shelters inside | Depth found | No value | Reading A: not exposed | Reading B: unable to assess |
|---|---|---|---|---|---|
| Mueang Nonthaburi | 38 | 36 | 2 | 2 | 2 |
| Pua, Nan | 29 | 0 | 29 | 29 | **29** |
| Bang Bua Thong | 1 | 1 | 0 | 0 | 0 |

Deepest samples in Mueang Nonthaburi: 7.07 m, 7.03 m, 4.24 m, 3.79 m, 3.43 m.

## 3. What this proves

1. **The three datasets line up.** Boundaries, shelters and flood tiles share EPSG:4326, and a point-in-district check plus a one-pixel raster read works for real districts in seconds. The existing GRP method needs no change to consume them.
2. **The no-data decision is real, not theoretical.** In Pua every shelter sits where the raster holds no value. Today GRP would report **29 unable to assess** and zero useful answers. If absent data means "not flooded" inside the modelled area, the same district reports **29 not exposed under this scenario**. Same data, opposite message to a planner. This is the blocking question for DEP-05.
3. **Depths look plausible where flooding is modelled.** Nonthaburi's 3 to 7 m sits in the top legend classes; nothing sampled hit the extreme values seen elsewhere in the tiles, so the permanent-water question stays open but is not blocking this district.

## 4. Data-quality problems found

1. **Shelter district names cannot be joined.** Many rows carry only `เมือง`, and Bang Bua Thong appears nowhere, although Nonthaburi has 68 shelters. **Membership must be decided by geometry**, which is what GRP's method does anyway; name fields are display-only.
2. **At least one shelter is in the wrong place.** The single point inside Bang Bua Thong is named `อบต.ลาดตะเคียน`, which belongs to Prachinburi. A district with 68 shelters in its province having one mislocated point suggests coordinate errors across the file. **An ingest-time check is needed**: does each point fall inside the district its own attributes name? Report the mismatches rather than silently accepting them.
3. **Coverage is uneven.** 38 shelters in one district and 1 in a neighbouring one is a completeness question for the Hub, not a software problem, but a planner must be told what "in scope" covered.
4. **Truncated Thai columns** (`สถา`, `รอง`, `ละต`, `ลอง`) still need confirming before they are shown to anyone.

## 5. What to prove next

| # | Question | How | Blocks |
|---|---|---|---|
| 1 | Does the modelled area have a mask? | Ask the Authority; if yes, re-run the proof with it and compare Reading A against the mask | Any real result |
| 2 | How many shelters nationwide fall outside the district their attributes name? | Extend the proof to all 928 districts and count mismatches | Loading centres |
| 3 | Do permanent water bodies explain depths over 10 m? | Sample those cells against a water mask or satellite imagery | Believable numbers |
| 4 | Does a district-clipped flood picture look right? | Render one district (Option A) and compare with the sampled points | Map work |
| 5 | Do the vulnerability rasters line up after reprojection? | Reproject a district-sized window to EPSG:4326 and sample the same shelters | Increment 6 |
| 6 | Does the golden case reproduce? | Run the proof on Chiang Yuen when DEP-04 arrives and compare with the signed result | Increment 1 acceptance |

## 6. Running it again

It needs two things that are not in Git:

1. The delivered files unpacked under `.local/data-in/` (ignored by Git; they live on the product owner's PC and on the ADPC Drive).
2. The GIS extras installed: `pip install -e ".[dev,gis]"` in the virtual environment, for `rasterio`, `pyogrio` and `shapely`.

Then, from the repository root:

```
python -m tools.prove_dataset --district "Bang Bua Thong"
python -m tools.prove_dataset --district "ปัว"
```

Either the Thai or the English district name works.

## 7. Rules for this tool

- It lives in `tools/`, outside the product, and writes nothing.
- Its numbers must never be shown to a planner or put in a brief: the accepted source delivery is still unpinned and no approved assessment method has been applied.
- When the real loaders exist, this tool stays useful as a quick independent check against them.
