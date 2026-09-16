import json
from hashlib import sha256
from pathlib import Path


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Calculate the immutable fingerprint used to pin an input or generated file."""

    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    """Fingerprint of JSON-like data, independent of key order."""

    text = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(text.encode("utf-8")).hexdigest()


def centers_sha256(rows: list[dict[str, object]]) -> str:
    """Fingerprint of an evacuation-center set, independent of row order."""

    ordered = sorted(
        ({"name": r["name"], "lon": r["lon"], "lat": r["lat"]} for r in rows),
        key=lambda r: (str(r["name"]), float(r["lon"]), float(r["lat"])),
    )
    return canonical_sha256(ordered)
