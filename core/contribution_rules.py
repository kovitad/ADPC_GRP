"""What GRP checks before it sends a contribution to Global Risk (ADR-0032).

The required fields mirror what Global Risk's own gate returned on 28 September 2026 when asked
with an empty manifest (kinds document, table, raster, vector), and the runbook for weights.
Checking here saves a round trip and marks the right form field; Global Risk's gate still has
the last word, and whatever it says is shown to the person verbatim.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

KINDS = ("vector", "raster", "table", "document", "weights", "feed")

REQUIRED: dict[str, tuple[str, ...]] = {
    "vector": ("layer", "url", "title", "description", "source", "license", "vintage"),
    "raster": (
        "layer", "url", "title", "description", "source", "license", "vintage", "legend",
        "declared",
    ),
    "table": (
        "dataset", "title", "description", "source", "validation", "license", "vintage",
        "cadence", "columns", "units",
    ),
    "document": ("pack", "url", "source", "title", "pub_date", "temporal", "validation"),
    "weights": ("hazard", "weights", "rationale"),
    # A live JSON feed Global Risk fetches itself through generic_json (ADR-0052, Share data).
    "feed": (
        "dataset", "title", "description", "source", "validation", "cadence", "url",
        "records_path", "fields",
    ),
}
OPTIONAL: dict[str, tuple[str, ...]] = {
    "vector": ("countries", "name_field", "usage_notes"),
    "raster": ("usage_notes",),
    "table": ("csv_text", "url", "as_of_field", "usage_notes", "pack"),
    "document": ("usage_notes", "doc_type", "event", "countries", "crops", "filename"),
    "weights": (),
    "feed": ("as_of_field", "pack", "hazards", "countries", "license", "usage_notes",
             "residency"),
}
# The field Global Risk knows the contribution by, used to match it in contribute_status.
NAME_FIELD = {
    "vector": "layer", "raster": "layer", "table": "dataset", "document": "title",
    "weights": "hazard", "feed": "dataset",
}

VALIDATION = {
    "multi-agency-consensus", "peer-reviewed", "single-agency", "official-statistic",
    "unvalidated",
}
CADENCE = {"monthly", "daily", "annual", "irregular"}
TEMPORAL = {"forecast", "retrospective"}
PACKS = {"risk", "food-security"}
RASTER_PREFIXES = ("hazard_", "risk_", "vulnerability_", "population_")
# A feed URL must stay up: Global Risk re-reads it, and an approved feed cannot be withdrawn.
TEMPORARY_HOSTS = ("trycloudflare.com", "ngrok.io", "ngrok-free.app", "ngrok.app", "loca.lt",
                   "localhost.run", "serveo.net", "localtunnel.me")
FEED_FETCH_KEYS = ("url", "records_path", "as_of_field", "fields")
# Owner's choice (5 Oct 2026): a test may go through a temporary tunnel, but only under a test
# name, so the real name stays free. The test feed is left behind when the tunnel closes.
TEST_FEED_NAME = re.compile(r"^[a-z][a-z0-9_]*_test\d+$")
SNAKE = re.compile(r"^[a-z][a-z0-9_]{1,79}$")
# Global Risk's gate (30 Sep 2026): "layer must be snake_case: lowercase letters, digits,
# underscores, 3-40 chars". A longer name is declined after the whole submit round trip.
LAYER_NAME = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
YEAR_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])(-\d{2})?$")
DRIVE_FILE = re.compile(r"^/file/d/([A-Za-z0-9_-]{10,})")
CONTACT_FIELD = re.compile(
    r"(^|_|\b)(tel|telephone|phone|mobile|fax|e[-_]?mail|contact|line_?id)(\b|_|$)|โทร|อีเมล|แฟกซ์",
    re.IGNORECASE,
)


@dataclass
class Checked:
    manifest: dict[str, Any]
    problems: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def drive_download_url(url: str) -> tuple[str, str | None]:
    """A Google Drive share link, turned into the direct-download form Global Risk needs.

    Global Risk fetches the file itself, so a share page or a folder returns HTML (runbook
    section 02). Returns (url, problem); anything that is not a Drive link comes back unchanged.
    """

    text = (url or "").strip()
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if host not in {"drive.google.com", "docs.google.com"}:
        return text, None
    if "/folders/" in parsed.path:
        return text, (
            "That is a Google Drive folder. Share the file itself: open it, choose Share, set "
            "'Anyone with the link', and copy that link."
        )
    match = DRIVE_FILE.match(parsed.path) or re.match(r"^/(?:[a-z]+/)?d/([A-Za-z0-9_-]{10,})",
                                                      parsed.path)
    file_id = match.group(1) if match else (parse_qs(parsed.query).get("id") or [None])[0]
    if not file_id:
        return text, "GRP could not find the file ID in that Google Drive link."
    return f"https://drive.google.com/uc?export=download&id={file_id}", None


def _as_mapping(value: Any) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def check_manifest(kind: str, manifest: dict[str, Any], test: bool = False) -> Checked:
    """Clean the manifest and name every problem GRP can see before sending it.

    ``test`` is a live-feed test: a temporary tunnel address is allowed, under a test name only.
    """

    if kind not in KINDS:
        return Checked({}, {"kind": f"Choose one of: {', '.join(KINDS)}."})
    if kind == "feed" and isinstance(manifest.get("fetch"), dict):
        # A checked feed comes back nested; flatten it so the same checks run again on send.
        fetch = manifest["fetch"]
        manifest = {**{k: v for k, v in manifest.items() if k not in {"fetch", "adapter"}},
                    **{k: fetch.get(k) for k in FEED_FETCH_KEYS if k in fetch}}
    allowed = set(REQUIRED[kind]) | set(OPTIONAL[kind])
    cleaned: dict[str, Any] = {}
    for key, value in manifest.items():
        if key not in allowed:
            continue
        if isinstance(value, str):
            value = value.strip()
        if value in ("", None, [], {}):
            continue
        cleaned[key] = value
    checked = Checked(cleaned)
    problems = checked.problems

    for key in REQUIRED[kind]:
        if key not in cleaned:
            problems[key] = "Required."
    if kind == "table" and "csv_text" not in cleaned and "url" not in cleaned:
        problems["csv_text"] = "Paste the CSV or give a link to it."

    if kind == "feed" and "url" in cleaned:
        problem = feed_url_problem(str(cleaned["url"]), allow_temporary=test)
        if problem:
            problems["url"] = problem
    elif "url" in cleaned:
        url, problem = drive_download_url(str(cleaned["url"]))
        if problem:
            problems["url"] = problem
        elif urlparse(url).scheme != "https":
            problems["url"] = "Use an https link that anyone can open without signing in."
        else:
            if url != cleaned["url"]:
                checked.notes.append(
                    "The Google Drive link was changed to its direct-download form."
                )
            cleaned["url"] = url

    name_key = NAME_FIELD[kind]
    if kind in {"vector", "raster", "table"} and name_key in cleaned:
        name = str(cleaned[name_key])
        if not SNAKE.fullmatch(name):
            problems[name_key] = (
                "Lower-case letters, digits and underscores, starting with a letter."
            )
        elif name_key == "layer" and not LAYER_NAME.fullmatch(name):
            problems[name_key] = (
                f"Global Risk accepts 3 to 40 characters; this name has {len(name)}."
            )
        elif kind == "raster" and not str(cleaned[name_key]).startswith(RASTER_PREFIXES):
            problems[name_key] = "Start with hazard_, risk_, vulnerability_ or population_."

    for key in ("vintage", "pub_date"):
        if key in cleaned and not YEAR_MONTH.fullmatch(str(cleaned[key])):
            problems[key] = "Write the date as YYYY-MM (or YYYY-MM-DD)."
    if "validation" in cleaned and cleaned["validation"] not in VALIDATION:
        problems["validation"] = f"One of: {', '.join(sorted(VALIDATION))}."
    if kind != "feed" and "cadence" in cleaned and cleaned["cadence"] not in CADENCE:
        problems["cadence"] = f"One of: {', '.join(sorted(CADENCE))}."
    if "temporal" in cleaned and cleaned["temporal"] not in TEMPORAL:
        problems["temporal"] = "forecast or retrospective."
    if "pack" in cleaned and cleaned["pack"] not in PACKS:
        problems["pack"] = "risk or food-security."
    for key in ("usage_notes",):
        if key in cleaned and len(str(cleaned[key])) > 500:
            problems[key] = "At most 500 characters."
    for key in ("countries", "crops", "hazards"):
        if key in cleaned and isinstance(cleaned[key], str):
            cleaned[key] = [part.strip() for part in cleaned[key].split(",") if part.strip()]

    # A population count grid needs no legend (Global Risk's own field note).
    if kind == "raster" and str(cleaned.get("layer", "")).startswith("population_"):
        problems.pop("legend", None)
    for key in ("legend", "declared", "columns", "fields"):
        if key in cleaned:
            mapping = _as_mapping(cleaned[key])
            if mapping is None:
                problems[key] = "Give this as a mapping, for example {\"1\": \"Very low\"}."
            else:
                cleaned[key] = mapping
    if kind == "raster" and isinstance(cleaned.get("declared"), dict):
        declared = cleaned["declared"]
        for key in ("dtype", "valid_min", "valid_max"):
            if key not in declared:
                problems["declared"] = "Needs dtype, valid_min and valid_max (and nodata if any)."

    if kind == "weights":
        weights = _as_mapping(cleaned.get("weights"))
        if weights is None and "weights" in cleaned:
            problems["weights"] = "Give the weights as layer: number pairs."
        elif weights is not None:
            try:
                numbers = {str(k): float(v) for k, v in weights.items()}
            except (TypeError, ValueError):
                problems["weights"] = "Every weight must be a number."
            else:
                if any(value < 0 for value in numbers.values()):
                    problems["weights"] = "Weights cannot be negative."
                elif abs(sum(numbers.values()) - 1.0) > 0.001:
                    total = sum(numbers.values())
                    problems["weights"] = (
                        f"The weights add up to {total:.3f}; they must add up to 1.0."
                    )
                elif any(name.startswith("population_") for name in numbers):
                    problems["weights"] = "A population count grid cannot be weighted."
                cleaned["weights"] = numbers

    if kind == "feed":
        if test and "dataset" in cleaned and not TEST_FEED_NAME.fullmatch(str(cleaned["dataset"])):
            problems["dataset"] = (
                "A test feed's name ends with _test and a number, e.g. "
                "sea_pm25_province_forecast_test1, so the real name stays free."
            )
        if "dataset" in cleaned and not SNAKE.fullmatch(str(cleaned["dataset"])):
            problems["dataset"] = (
                "Lower-case letters, digits and underscores, starting with a letter."
            )
        fields = cleaned.get("fields")
        if isinstance(fields, dict) and not all(isinstance(v, str) and v for v in fields.values()):
            problems["fields"] = "Each output field maps to a path in the record, such as \"name\"."
        as_of = cleaned.get("as_of_field")
        if as_of and isinstance(fields, dict) and as_of not in fields:
            # Global Risk sorts on the mapped output field, not the raw record (seen 5 Oct 2026).
            problems["as_of_field"] = (
                "Use one of the output field names above, so records sort by it."
            )
        cleaned.setdefault("pack", "risk")
        checked.manifest = {
            **{k: v for k, v in cleaned.items() if k not in FEED_FETCH_KEYS},
            "adapter": "generic_json",
            "fetch": {k: cleaned[k] for k in FEED_FETCH_KEYS if k in cleaned},
        }
    return checked


def feed_url_problem(url: str, allow_temporary: bool = False) -> str | None:
    """Why Global Risk could not, or should not, fetch this feed URL. None when it looks fine."""

    import ipaddress

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        return "Use an http or https link."
    if parsed.username or parsed.password:
        return "The link cannot carry a user name or password: Global Risk fetches it anonymously."
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return "Global Risk cannot reach this computer. Use a public address."
    try:
        if not ipaddress.ip_address(host).is_global:
            return "Global Risk cannot reach a private address. Use a public one."
    except ValueError:
        pass
    if host.endswith(TEMPORARY_HOSTS) and not allow_temporary:
        return ("This is a temporary tunnel address. An approved feed cannot be withdrawn, so use "
                "an address that will stay up.")
    return None


def contact_fields(properties: set[str]) -> list[str]:
    """Property names that look like contact details, which GRP never sends out."""

    return sorted(name for name in properties if CONTACT_FIELD.search(name))


@dataclass
class PointFileCheck:
    feature_count: int
    properties: list[str]
    problem: str | None


def check_point_file(body: bytes) -> PointFileCheck:
    """A GeoJSON FeatureCollection of Points, lon/lat, with no contact fields."""

    head = body[:512].lstrip().lower()
    if head.startswith((b"<!doctype", b"<html")):
        return PointFileCheck(0, [], (
            "The link returned a web page, not the file. Set sharing to 'Anyone with the link'. "
            "Google Drive also shows a virus-scan page for files over about 100 MB; host those "
            "elsewhere."
        ))
    try:
        document = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return PointFileCheck(0, [], "The file is not GeoJSON.")
    if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
        return PointFileCheck(0, [], "The file is not a GeoJSON FeatureCollection.")
    features = document.get("features") or []
    properties: set[str] = set()
    for feature in features:
        geometry = (feature or {}).get("geometry") or {}
        if geometry.get("type") != "Point":
            return PointFileCheck(len(features), [], "Every feature must be a Point.")
        coordinates = geometry.get("coordinates") or []
        if (
            len(coordinates) < 2
            or not all(isinstance(c, int | float) for c in coordinates[:2])
            or not (-180 <= coordinates[0] <= 180 and -90 <= coordinates[1] <= 90)
        ):
            return PointFileCheck(len(features), [], "Coordinates must be longitude, latitude.")
        properties.update((feature.get("properties") or {}).keys())
    if not features:
        return PointFileCheck(0, [], "The file has no features.")
    blocked = contact_fields(properties)
    if blocked:
        return PointFileCheck(len(features), sorted(properties), (
            "The file has contact fields GRP never sends to Global Risk: "
            f"{', '.join(blocked)}. Remove them and share the file again."
        ))
    return PointFileCheck(len(features), sorted(properties), None)
