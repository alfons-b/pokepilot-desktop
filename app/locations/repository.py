"""Location presets and managed GPX files (SQLite + data/gpx folder)."""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.database.db import Database, now_iso
from app.locations.gpx import GpxError, GpxInfo, parse_gpx_file
from app.locations.models import LocationError, LocationPreset

logger = logging.getLogger(__name__)
LOCATIONS_FORMAT = "pokepilot-locations"


@dataclass(frozen=True)
class ImportReport:
    added: int
    skipped: list[str]


class LocationRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, loc: LocationPreset) -> int:
        loc.validate()
        ts = now_iso()
        loc.id = self.db.execute(
            "INSERT INTO location_presets (name, latitude, longitude, notes, favorite, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (loc.name, loc.latitude, loc.longitude, loc.notes, int(loc.favorite), ts, ts),
        )
        return loc.id

    def update(self, loc: LocationPreset) -> None:
        if loc.id is None:
            raise LocationError("Location has no id.")
        loc.validate()
        with self.db.transaction() as conn:
            cur = conn.execute(
                "UPDATE location_presets SET name=?, latitude=?, longitude=?, notes=?, favorite=?, updated_at=? "
                "WHERE id=?",
                (loc.name, loc.latitude, loc.longitude, loc.notes, int(loc.favorite), now_iso(), loc.id),
            )
            if cur.rowcount == 0:
                raise LocationError(f"Location {loc.id} no longer exists.")

    def delete(self, loc_id: int) -> None:
        self.db.execute("DELETE FROM location_presets WHERE id = ?", (loc_id,))

    def set_favorite(self, loc_id: int, favorite: bool) -> None:
        self.db.execute(
            "UPDATE location_presets SET favorite=?, updated_at=? WHERE id=?", (int(favorite), now_iso(), loc_id)
        )

    def get(self, loc_id: int) -> LocationPreset:
        r = self.db.query_one("SELECT * FROM location_presets WHERE id = ?", (loc_id,))
        if r is None:
            raise LocationError(f"Location {loc_id} does not exist.")
        return self._row(r)

    def search(self, text: str = "", favorites_only: bool = False) -> list[LocationPreset]:
        sql = "SELECT * FROM location_presets WHERE 1=1"
        params: list = []
        if text.strip():
            sql += " AND (name LIKE ? ESCAPE '\\' COLLATE NOCASE OR notes LIKE ? ESCAPE '\\' COLLATE NOCASE)"
            like = "%" + re.sub(r"([%_\\])", r"\\\1", text.strip()) + "%"
            params += [like, like]
        if favorites_only:
            sql += " AND favorite = 1"
        sql += " ORDER BY favorite DESC, name COLLATE NOCASE"
        return [self._row(r) for r in self.db.query(sql, tuple(params))]

    @staticmethod
    def _row(r) -> LocationPreset:  # noqa: ANN001
        return LocationPreset(r["name"], r["latitude"], r["longitude"], r["notes"], bool(r["favorite"]), r["id"])

    # ------------------------------------------------------------- JSON I/O
    def export_json(self, items: list[LocationPreset] | None = None) -> str:
        items = self.search() if items is None else items
        return json.dumps(
            {
                "format": LOCATIONS_FORMAT,
                "version": 1,
                "locations": [
                    {"name": i.name, "latitude": i.latitude, "longitude": i.longitude, "notes": i.notes,
                     "favorite": i.favorite}
                    for i in items
                ],
            },
            indent=2,
            ensure_ascii=False,
        )

    def import_json(self, text: str) -> ImportReport:
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise LocationError(f"Not valid JSON: {exc}") from exc
        if isinstance(data, dict) and data.get("format") == LOCATIONS_FORMAT:
            items = data.get("locations", [])
        elif isinstance(data, list):
            items = data  # plain list of {name, latitude, longitude}
        else:
            raise LocationError("Not a PokePilot locations file.")
        valid: list[LocationPreset] = []
        skipped: list[str] = []
        for n, item in enumerate(items, 1):
            try:
                if not isinstance(item, dict):
                    raise LocationError("entry is not an object")
                loc = LocationPreset(
                    str(item.get("name", "")), item.get("latitude", item.get("lat")),
                    item.get("longitude", item.get("lon", item.get("lng"))), str(item.get("notes", "")),
                    bool(item.get("favorite", False)),
                )
                loc.validate()
                valid.append(loc)
            except (LocationError, TypeError) as exc:
                skipped.append(f"Entry {n}: {exc}")
        ts = now_iso()
        with self.db.transaction() as conn:
            conn.executemany(
                "INSERT INTO location_presets (name, latitude, longitude, notes, favorite, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                [(v.name, v.latitude, v.longitude, v.notes, int(v.favorite), ts, ts) for v in valid],
            )
        return ImportReport(len(valid), skipped)


@dataclass(frozen=True)
class GpxRecord:
    id: int
    name: str
    file_path: str
    point_count: int
    track_count: int
    distance_m: float

    @property
    def exists(self) -> bool:
        return Path(self.file_path).is_file()


class GpxRepository:
    """Imported GPX files are validated, then copied into a managed folder."""

    def __init__(self, db: Database, store_dir: Path) -> None:
        self.db = db
        self.store_dir = Path(store_dir)

    def import_file(self, src: Path, name: str = "") -> tuple[int, GpxInfo]:
        src = Path(src)
        info = parse_gpx_file(src)  # raises GpxError before anything is copied
        self.store_dir.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", src.stem)[:60] or "route"
        dest = self.store_dir / f"{stem}.gpx"
        n = 2
        while dest.exists():
            dest = self.store_dir / f"{stem}_{n}.gpx"
            n += 1
        shutil.copyfile(src, dest)
        ts = now_iso()
        try:
            gid = self.db.execute(
                "INSERT INTO gpx_files (name, file_path, point_count, track_count, distance_m, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?)",
                ((name or info.name or src.stem).strip(), str(dest), info.points + info.waypoints,
                 info.tracks + info.routes, info.distance_m, ts, ts),
            )
        except Exception:
            dest.unlink(missing_ok=True)
            raise
        logger.info("Imported GPX %s (%d points, %.0f m)", dest.name, info.points, info.distance_m)
        return gid, info

    def list(self) -> list[GpxRecord]:
        return [
            GpxRecord(r["id"], r["name"], r["file_path"], r["point_count"], r["track_count"], r["distance_m"])
            for r in self.db.query("SELECT * FROM gpx_files ORDER BY name COLLATE NOCASE")
        ]

    def get(self, gid: int) -> GpxRecord:
        rec = next((g for g in self.list() if g.id == gid), None)
        if rec is None:
            raise GpxError(f"GPX file {gid} does not exist.")
        return rec

    def rename(self, gid: int, name: str) -> None:
        if not name.strip():
            raise GpxError("Name is required.")
        self.db.execute("UPDATE gpx_files SET name=?, updated_at=? WHERE id=?", (name.strip(), now_iso(), gid))

    def revalidate(self, gid: int) -> GpxInfo:
        return parse_gpx_file(Path(self.get(gid).file_path))

    def delete(self, gid: int, delete_file: bool = True) -> None:
        rec = self.get(gid)
        self.db.execute("DELETE FROM gpx_files WHERE id=?", (gid,))
        path = Path(rec.file_path)
        if delete_file and path.parent.resolve() == self.store_dir.resolve():
            path.unlink(missing_ok=True)  # only files PokePilot copied are deleted

    def export_copy(self, gid: int, dest: Path) -> None:
        rec = self.get(gid)
        if not rec.exists:
            raise GpxError(f"The stored file is missing: {rec.file_path}")
        shutil.copyfile(rec.file_path, dest)
