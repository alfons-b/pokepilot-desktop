"""Location presets: validation and coordinate parsing."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

_PAIR_RE = re.compile(r"^\s*\(?\s*(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)\s*\)?\s*$")
MAX_NAME = 100


class LocationError(ValueError):
    pass


def validate_lat_lon(lat: float, lon: float) -> tuple[float, float]:
    for v, name in ((lat, "Latitude"), (lon, "Longitude")):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v):
            raise LocationError(f"{name} must be a number.")
    if not -90 <= lat <= 90:
        raise LocationError(f"Latitude {lat} is out of range (-90 to 90).")
    if not -180 <= lon <= 180:
        raise LocationError(f"Longitude {lon} is out of range (-180 to 180).")
    return round(float(lat), 7), round(float(lon), 7)


def parse_coordinates(text: str) -> tuple[float, float]:
    """Parse '-6.2088, 106.8456' (also with spaces, semicolons or parentheses)."""
    m = _PAIR_RE.match(text or "")
    if not m:
        raise LocationError("Enter coordinates as 'latitude, longitude', e.g. -6.2088, 106.8456")
    return validate_lat_lon(float(m.group(1)), float(m.group(2)))


def format_coordinates(lat: float, lon: float) -> str:
    return f"{lat:.6f}, {lon:.6f}"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class LocationPreset:
    name: str
    latitude: float
    longitude: float
    notes: str = ""
    favorite: bool = False
    id: int | None = None

    def validate(self) -> None:
        name = self.name.strip()
        if not name:
            raise LocationError("Name is required.")
        if len(name) > MAX_NAME:
            raise LocationError(f"Name is longer than {MAX_NAME} characters.")
        self.name = name
        self.latitude, self.longitude = validate_lat_lon(self.latitude, self.longitude)

    @property
    def coordinates(self) -> str:
        return format_coordinates(self.latitude, self.longitude)
