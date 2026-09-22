"""Display-only flood overlay: a coloured PNG plus its bounds, made next to the data.

The picture is drawn once when a hazard version is accepted (seed or worker side), stored
through the storage interface, and served as a file. The API never reads rasters (AD-03).
It is for orientation only; assessment numbers come from the locked result.
"""

from __future__ import annotations

import tempfile
import warnings
from pathlib import Path
from typing import Any

# Sequential red depth tones make the hazard visually distinct from SERVIR blue navigation and
# from the green/orange/grey assessment-center statuses. Colour never changes classification.
DEPTH_CLASSES = [
    {"label": "0–0.5 m", "min": 0.0, "max": 0.5, "rgba": [254, 224, 210, 150]},
    {"label": "0.5–1 m", "min": 0.5, "max": 1.0, "rgba": [252, 146, 114, 170]},
    {"label": "1–1.5 m", "min": 1.0, "max": 1.5, "rgba": [251, 106, 74, 185]},
    {"label": "1.5–2 m", "min": 1.5, "max": 2.0, "rgba": [203, 24, 29, 195]},
    {"label": "> 2 m", "min": 2.0, "max": None, "rgba": [103, 0, 13, 215]},
]
NO_DATA_RGBA = [120, 120, 120, 110]


def legend() -> dict[str, Any]:
    return {
        "classes": [{"label": c["label"], "rgba": c["rgba"]} for c in DEPTH_CLASSES],
        "no_data": {"label": "No flood data", "rgba": NO_DATA_RGBA},
        "dry": "0 m is transparent",
    }


def colourise(depth, nodata_mask):
    """Return an RGBA (4, rows, cols) uint8 array."""

    import numpy as np

    rgba = np.zeros((4, *depth.shape), dtype="uint8")
    for depth_class in DEPTH_CLASSES:
        upper = depth_class["max"]
        mask = (depth > depth_class["min"]) & (~nodata_mask)
        if upper is not None:
            mask &= depth <= upper
        for band in range(4):
            rgba[band][mask] = depth_class["rgba"][band]
    for band in range(4):
        rgba[band][nodata_mask] = NO_DATA_RGBA[band]
    return rgba


def render_overlay(storage, raster_key: str, overlay_key: str) -> dict[str, Any]:
    """Draw the overlay PNG for a stored raster; return metadata to keep with the version."""

    import numpy as np
    import rasterio

    with storage.open_window(raster_key) as raster:
        if raster.crs is None or raster.crs.to_epsg() != 4326:
            raise ValueError("Overlay needs an EPSG:4326 raster")
        band = raster.read(1, masked=True)
        west, south, east, north = raster.bounds
    depth = np.asarray(band.filled(0), dtype="float64")
    nodata_mask = np.ma.getmaskarray(band) | ~np.isfinite(depth)
    rgba = colourise(depth, nodata_mask)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "overlay.png"
        with warnings.catch_warnings():
            # A PNG has no georeferencing; the bounds travel separately with the metadata.
            warnings.simplefilter("ignore", rasterio.errors.NotGeoreferencedWarning)
            image = rasterio.open(
                path,
                "w",
                driver="PNG",
                height=rgba.shape[1],
                width=rgba.shape[2],
                count=4,
                dtype="uint8",
            )
            with image:
                image.write(rgba)
        sha = storage.put(overlay_key, path)
    return {
        "overlay_key": overlay_key,
        "overlay_sha256": sha,
        "overlay_bounds": [[south, west], [north, east]],
    }
