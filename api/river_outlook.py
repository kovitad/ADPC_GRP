"""GEOGLOWS river outlook for the district summary (ADR-0059).

The Product Owner chose on 4 October 2026 to show planners the River Watch forecast for their
district, labelled exploratory. River Watch (ADR-0036) stays the source:

- **Bangkok districts:** the district's main river, chosen by rule (the reach that drains the
  most land inside it), not confirmed by a hydrologist;
- **Nonthaburi:** Bang Bua Thong uses its exploratory canal reach, and the districts on the Chao
  Phraya (Mueang Nonthaburi, Bang Kruai, Pak Kret) use the exploratory Chao Phraya reach near
  Nonthaburi. Bang Yai and Sai Noi have none yet.

The forecast is fetched through River Watch's own cache, so a summary never adds load beyond
River Watch's. The chart is drawn with numpy alone (no plotting library in the image): the band
where most forecasts fall, the median line and a zero baseline. It has no thresholds, no
warnings and no water levels.
"""

from __future__ import annotations

import asyncio
import struct
import zlib
from datetime import datetime
from typing import Any

import numpy as np

from api.river_watch import _current, _view
from core.river_watch import bangkok_district

# Nonthaburi districts and their exploratory reaches (River Watch REACHES).
# The summary translates the reason ("why") key into the download's language.
NONTHABURI_REACHES = {
    "1204": (430392813, "canal_bang_bua_thong"),
    "1201": (430537201, "chao_phraya_nonthaburi"),
    "1202": (430537201, "chao_phraya_nonthaburi"),
    "1206": (430537201, "chao_phraya_nonthaburi"),
}
CHART_SIZE = (720, 260)
BAND = (198, 222, 240)
LINE = (31, 78, 121)
AXIS = (120, 130, 140)


def reach_for(admin_code: str) -> dict[str, Any] | None:
    """Which reach a district's summary shows, and why; None when there is none."""

    code = str(admin_code or "")[:4]
    district = bangkok_district(code)
    if district is not None:
        if not district["main_reach"]:
            return None
        main = next((r for r in district["reaches"] if r["reach_id"] == district["main_reach"]),
                    None)
        likely = (main or {}).get("likely") or {}
        return {
            "reach_id": district["main_reach"],
            "why": "main_by_rule",
            "likely_name_en": likely.get("name_en"), "likely_name_th": likely.get("name_th"),
            "size": (main or {}).get("size"),
            "inland": district["inland"],
        }
    if code in NONTHABURI_REACHES:
        reach_id, why = NONTHABURI_REACHES[code]
        return {"reach_id": reach_id, "why": why,
                "likely_name_en": "Chao Phraya River" if reach_id == 430537201 else None,
                "likely_name_th": "แม่น้ำเจ้าพระยา" if reach_id == 430537201 else None,
                "size": None, "inland": reach_id != 430537201}
    return None


def _png(pixels: np.ndarray) -> bytes:
    height, width, _ = pixels.shape
    raw = b"".join(b"\x00" + pixels[row].tobytes() for row in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def chart(series: list[dict[str, Any]]) -> bytes | None:
    """A small 7-day flow chart. The y axis starts at zero; the x axis is real time."""

    points = [(datetime.fromisoformat(s["valid_at_utc"].replace("Z", "+00:00")).timestamp(),
               s["median_m3s"], s.get("p25_m3s"), s.get("p75_m3s")) for s in series
              if s.get("median_m3s") is not None]
    if len(points) < 2:
        return None
    width, height = CHART_SIZE
    pad_l, pad_r, pad_t, pad_b = 14, 14, 12, 18
    t0, t1 = points[0][0], points[-1][0]
    top = max(max(p[1], p[3] or 0) for p in points) * 1.1 or 1.0
    img = np.full((height, width, 3), 255, dtype=np.uint8)

    def x_of(t: float) -> int:
        return int(pad_l + (t - t0) / ((t1 - t0) or 1) * (width - pad_l - pad_r))

    def y_of(v: float) -> int:
        return int(height - pad_b - max(v, 0) / top * (height - pad_t - pad_b))

    # The band where most forecasts fall (P25 to P75), filled column by column.
    for (ta, _ma, la, ha), (tb, _mb, lb, hb) in zip(points, points[1:], strict=False):
        if None in (la, ha, lb, hb):
            continue
        xa, xb = x_of(ta), x_of(tb)
        for x in range(xa, max(xb, xa + 1)):
            f = (x - xa) / ((xb - xa) or 1)
            y_hi = y_of(ha + (hb - ha) * f)
            y_lo = y_of(la + (lb - la) * f)
            img[min(y_hi, y_lo):max(y_hi, y_lo) + 1, x] = BAND
    img[height - pad_b, pad_l:width - pad_r] = AXIS  # zero baseline
    # The median line, two pixels thick.
    for (ta, ma, _la, _ha), (tb, mb, _lb, _hb) in zip(points, points[1:], strict=False):
        xa, ya, xb, yb = x_of(ta), y_of(ma), x_of(tb), y_of(mb)
        steps = max(abs(xb - xa), abs(yb - ya), 1)
        for i in range(steps + 1):
            x = round(xa + (xb - xa) * i / steps)
            y = round(ya + (yb - ya) * i / steps)
            img[max(y - 1, 0):y + 1, x:x + 2] = LINE
    # Day ticks on the baseline.
    day = 86400
    tick = (int(t0 // day) + 1) * day
    while tick < t1:
        x = x_of(tick)
        img[height - pad_b:height - pad_b + 5, x] = AXIS
        tick += day
    return _png(img)


async def _fetch(reach_id: int) -> dict[str, Any]:
    fetched, problem = await _current(reach_id)
    return _view(reach_id, fetched, problem)


def outlook(admin_code: str) -> dict[str, Any]:
    """The summary's river section for one area. Never raises: a failure is a stated gap."""

    reach = reach_for(admin_code)
    if reach is None:
        return {"available": False, "reason": "no_reach"}
    try:
        view = asyncio.run(_fetch(reach["reach_id"]))
    except Exception as error:  # GEOGLOWS down or slow: the summary says so and carries on
        return {"available": False, "reason": "unavailable", "reach": reach,
                "problem": type(error).__name__}
    if not view.get("available"):
        return {"available": False, "reason": "unavailable", "reach": reach,
                "problem": view.get("problem")}
    return {
        "available": True,
        "reach": reach,
        "summary": view["summary"],
        "chart": chart(view["series"]),
        "source": view["source"],
        "problem": view.get("problem"),
    }
