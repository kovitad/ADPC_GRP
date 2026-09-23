"""Show the delivered DDPM evacuation-centre records exactly as the importer reads them.

Reads `.local/data-in/evacuation_centers/shelters` directly through the same reader as
`core/shelter_import.py`, so the field names, the text encoding and the values are the ones
the importer would see. Nothing is written and no database is touched.

    python -m tools.show_shelter_record                  # profile every field, show record 0
    python -m tools.show_shelter_record --index 5000 --count 3
    python -m tools.show_shelter_record --profile-only   # no record values, only the profile

`--file` reads any vector file instead, so the same profile can be run over the prepared
contribution candidate to see exactly what would be published:

    python -m tools.show_shelter_record \
        --file .local/data-out/sig/ddpm_shelters_upload_candidate.geojson

The profile is what settles a field's meaning: a capacity column is numeric with a wide
range, a name column is text and nearly all distinct.

**The records may contain contact names and telephone numbers.** They are the data owner's
to see, not to paste into a chat or a ticket. `--profile-only` output is safe to share.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from shapely import from_wkb

from core.dataset_scan import read_vector_explicit
from core.shelter_import import REQUIRED_SUFFIXES, SHELTER_SOURCE_REF, SHELTER_STEM

SAMPLE_VALUES = 5
PHONE_LIKE = "0123456789-+() "


def _shapefile(root: Path) -> Path:
    folder = root / SHELTER_SOURCE_REF
    path = folder / f"{SHELTER_STEM}.shp"
    if not path.is_file():
        raise SystemExit(f"No shelter shapefile at {path}")
    missing = [s for s in REQUIRED_SUFFIXES if not (folder / f"{SHELTER_STEM}{s}").is_file()]
    if missing:
        raise SystemExit(f"Incomplete delivery at {folder}; missing {', '.join(missing)}")
    return path


def _text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    # A missing number arrives as NaN; without this it counts as a filled value.
    return "" if text.lower() in {"nan", "none"} else text


def _looks_numeric(values: list[str]) -> bool:
    filled = [v for v in values if v]
    if not filled:
        return False
    try:
        for value in filled[:200]:
            float(value)
    except ValueError:
        return False
    return True


def _profile(name: str, values: list[str]) -> dict:
    filled = [value for value in values if value]
    distinct = {value for value in filled}
    report = {
        "field": name,
        "filled": len(filled),
        "empty": len(values) - len(filled),
        "distinct": len(distinct),
        "numeric": _looks_numeric(values),
        "samples": sorted(distinct)[:SAMPLE_VALUES],
    }
    if report["numeric"]:
        numbers = [float(value) for value in filled]
        report["min"] = min(numbers)
        report["max"] = max(numbers)
    # A column that is almost entirely distinct text is a name; one with few distinct values
    # is a category; a numeric one with a wide range is a count or a capacity.
    if filled and not report["numeric"]:
        report["distinct_share"] = round(len(distinct) / len(filled), 3)
    if any(set(value) <= set(PHONE_LIKE) and len(value) >= 8 for value in filled[:200]):
        report["warning"] = "values look like telephone numbers; treat as contact data"
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(".local/data-in"))
    parser.add_argument("--file", type=Path, help="read this vector file instead of the delivery")
    parser.add_argument("--index", type=int, default=0, help="first record to show")
    parser.add_argument("--count", type=int, default=1, help="how many records to show")
    parser.add_argument("--profile-only", action="store_true")
    arguments = parser.parse_args()

    path = arguments.file if arguments.file else _shapefile(arguments.root)
    if arguments.file and not path.is_file():
        raise SystemExit(f"No such file: {path}")
    (meta, _, geometries, columns), encoding, encoding_source, tried = read_vector_explicit(
        path, read_geometry=True
    )
    names = [str(name) for name in meta.get("fields", [])]
    values = {name: [_text(v) for v in column] for name, column in zip(names, columns, strict=True)}
    total = len(geometries) if geometries is not None else 0

    output = {
        "source": {
            "path": str(path),
            "crs": meta.get("crs"),
            "features": total,
            "encoding": encoding,
            "encoding_from": encoding_source,
            "encodings_tried": tried,
        },
        "fields": names,
        "field_profile": [_profile(name, values[name]) for name in names],
    }

    if not arguments.profile_only:
        records = []
        for index in range(arguments.index, min(arguments.index + arguments.count, total)):
            point = from_wkb(geometries[index])
            records.append(
                {
                    "source_index": index,
                    **{name: values[name][index] for name in names},
                    "geometry_lon": round(point.x, 6),
                    "geometry_lat": round(point.y, 6),
                }
            )
        output["records"] = records
        output["_note"] = "records may contain contact details; do not paste them into a chat"

    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
