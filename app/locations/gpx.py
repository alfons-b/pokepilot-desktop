"""GPX validation and statistics (stdlib only, hardened against XML attacks)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from app.locations.models import LocationError, haversine_m, validate_lat_lon

MAX_GPX_BYTES = 20 * 1024 * 1024


class GpxError(ValueError):
    pass


@dataclass(frozen=True)
class GpxInfo:
    name: str
    tracks: int
    routes: int
    waypoints: int
    points: int  # track + route points
    distance_m: float
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_gpx_bytes(data: bytes, fallback_name: str = "") -> GpxInfo:
    if len(data) > MAX_GPX_BYTES:
        raise GpxError(f"File is larger than {MAX_GPX_BYTES // (1024 * 1024)} MB.")
    head = data[:4096].lower()
    # Entity declarations enable XXE / "billion laughs"; GPX files never need them.
    if b"<!doctype" in head or b"<!entity" in data.lower():
        raise GpxError("GPX files with DOCTYPE/ENTITY declarations are not accepted.")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise GpxError(f"Not well-formed XML: {exc}") from exc
    if _local(root.tag) != "gpx":
        raise GpxError(f"Root element is <{_local(root.tag)}>, expected <gpx>.")

    name = ""
    tracks = routes = waypoints = points = 0
    distance = 0.0
    lats: list[float] = []
    lons: list[float] = []

    def point(el: ET.Element) -> tuple[float, float]:
        try:
            lat, lon = float(el.attrib["lat"]), float(el.attrib["lon"])
            return validate_lat_lon(lat, lon)
        except (KeyError, ValueError, LocationError) as exc:
            line = f" ({_local(el.tag)})"
            raise GpxError(f"Invalid point{line}: {exc}") from exc

    def walk(seq: list[ET.Element]) -> None:
        nonlocal points, distance
        prev: tuple[float, float] | None = None
        for el in seq:
            lat, lon = point(el)
            lats.append(lat)
            lons.append(lon)
            points += 1
            if prev is not None:
                distance += haversine_m(prev[0], prev[1], lat, lon)
            prev = (lat, lon)

    for child in root:
        tag = _local(child.tag)
        if tag == "metadata" and not name:
            name = next((c.text or "" for c in child if _local(c.tag) == "name"), "").strip()
        elif tag == "wpt":
            lat, lon = point(child)
            lats.append(lat)
            lons.append(lon)
            waypoints += 1
        elif tag == "trk":
            tracks += 1
            if not name:
                name = next((c.text or "" for c in child if _local(c.tag) == "name"), "").strip()
            for seg in child:
                if _local(seg.tag) == "trkseg":
                    walk([p for p in seg if _local(p.tag) == "trkpt"])
        elif tag == "rte":
            routes += 1
            walk([p for p in child if _local(p.tag) == "rtept"])
    if points == 0 and waypoints == 0:
        raise GpxError("GPX contains no track points, route points or waypoints.")
    return GpxInfo(
        name or fallback_name, tracks, routes, waypoints, points, round(distance, 1),
        min(lats), min(lons), max(lats), max(lons),
    )


def parse_gpx_file(path: Path) -> GpxInfo:
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise GpxError(f"Cannot read {path.name}: {exc}") from exc
    if size > MAX_GPX_BYTES:
        raise GpxError(f"File is larger than {MAX_GPX_BYTES // (1024 * 1024)} MB.")
    return parse_gpx_bytes(path.read_bytes(), path.stem)
