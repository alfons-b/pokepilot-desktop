import json

import pytest

from app.database.db import Database
from app.locations.gpx import GpxError, parse_gpx_bytes, parse_gpx_file
from app.locations.models import (
    LocationError,
    LocationPreset,
    haversine_m,
    parse_coordinates,
    validate_lat_lon,
)
from app.locations.repository import GpxRepository, LocationRepository

GPX11 = b"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <metadata><name>Park loop</name></metadata>
  <wpt lat="-6.2" lon="106.8"><name>Start</name></wpt>
  <trk><name>Track</name><trkseg>
    <trkpt lat="0" lon="0"/><trkpt lat="0" lon="0.001"/><trkpt lat="0" lon="0.002"/>
  </trkseg></trk>
  <rte><rtept lat="1" lon="1"/><rtept lat="1" lon="1.001"/></rte>
</gpx>"""


def test_coordinates_parsing_and_validation():
    assert parse_coordinates("-6.2088, 106.8456") == (-6.2088, 106.8456)
    assert parse_coordinates("(51.5;-0.12)") == (51.5, -0.12)
    assert parse_coordinates("40.7 -74.0") == (40.7, -74.0)
    for bad in ["", "abc", "91, 0", "0, 181", "1,2,3"]:
        with pytest.raises(LocationError):
            parse_coordinates(bad)
    with pytest.raises(LocationError):
        validate_lat_lon(float("nan"), 0)
    with pytest.raises(LocationError):
        validate_lat_lon(True, 0)


def test_haversine():
    assert abs(haversine_m(0, 0, 0, 1) - 111_195) < 50


def test_preset_validation():
    with pytest.raises(LocationError):
        LocationPreset("  ", 0, 0).validate()
    with pytest.raises(LocationError):
        LocationPreset("x" * 101, 0, 0).validate()
    p = LocationPreset(" Home ", 1.123456789, 2, "n")
    p.validate()
    assert p.name == "Home" and p.latitude == 1.1234568


def test_gpx_parse_stats():
    info = parse_gpx_bytes(GPX11)
    assert info.name == "Park loop"
    assert (info.tracks, info.routes, info.waypoints, info.points) == (1, 1, 1, 5)
    assert 330 < info.distance_m < 335  # 2 x 111 m + 111 m route
    assert info.min_lat == -6.2 and info.max_lon == 106.8


def test_gpx10_namespace_and_fallback_name():
    data = b'<gpx version="1.0" xmlns="http://www.topografix.com/GPX/1/0"><wpt lat="1" lon="2"/></gpx>'
    info = parse_gpx_bytes(data, "file_stem")
    assert info.name == "file_stem" and info.waypoints == 1


@pytest.mark.parametrize(
    "data,msg",
    [
        (b"<gpx><trk>", "well-formed"),
        (b"<kml></kml>", "expected <gpx>"),
        (b"<gpx version='1.1'></gpx>", "no track points"),
        (b"<gpx><wpt lat='95' lon='0'/></gpx>", "Invalid point"),
        (b"<gpx><wpt lat='x' lon='0'/></gpx>", "Invalid point"),
        (b"<gpx><wpt lon='0'/></gpx>", "Invalid point"),
        (b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]><gpx>&lol;</gpx>', "DOCTYPE"),
        (b'<?xml version="1.0"?><!DOCTYPE gpx SYSTEM "file:///etc/passwd"><gpx/>', "DOCTYPE"),
    ],
)
def test_gpx_rejects_invalid(data, msg):
    with pytest.raises(GpxError, match=msg):
        parse_gpx_bytes(data)


def test_gpx_size_limit(tmp_path, monkeypatch):
    from app.locations import gpx

    monkeypatch.setattr(gpx, "MAX_GPX_BYTES", 10)
    f = tmp_path / "big.gpx"
    f.write_bytes(GPX11)
    with pytest.raises(GpxError, match="larger"):
        parse_gpx_file(f)


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "db.sqlite")
    yield d
    d.close()


def test_location_repository_crud_search(db):
    repo = LocationRepository(db)
    a = repo.add(LocationPreset("Central Park", 40.785, -73.968, "NYC"))
    repo.add(LocationPreset("Shibuya", 35.659, 139.700, "Tokyo crossing", favorite=True))
    repo.add(LocationPreset("100%_odd", 1, 1))
    assert [x.name for x in repo.search()][0] == "Shibuya"  # favorites first
    assert [x.name for x in repo.search("tokyo")] == ["Shibuya"]
    assert [x.name for x in repo.search("%")] == ["100%_odd"]  # LIKE wildcards escaped
    assert [x.name for x in repo.search(favorites_only=True)] == ["Shibuya"]
    loc = repo.get(a)
    loc.latitude = 41.0
    repo.update(loc)
    assert repo.get(a).latitude == 41.0
    repo.set_favorite(a, True)
    assert repo.get(a).favorite
    repo.delete(a)
    with pytest.raises(LocationError):
        repo.get(a)
    with pytest.raises(LocationError):
        repo.add(LocationPreset("bad", 100, 0))


def test_location_import_export(db):
    repo = LocationRepository(db)
    repo.add(LocationPreset("A", 1, 2, favorite=True))
    text = repo.export_json()
    assert json.loads(text)["format"] == "pokepilot-locations"
    report = repo.import_json(text)
    assert report.added == 1 and not report.skipped
    plain = json.dumps([{"name": "B", "lat": 3, "lng": 4}, {"name": "", "lat": 0, "lon": 0},
                        {"name": "C", "latitude": 200, "longitude": 0}, "junk"])
    report = repo.import_json(plain)
    assert report.added == 1 and len(report.skipped) == 3
    with pytest.raises(LocationError):
        repo.import_json("{}")
    with pytest.raises(LocationError):
        repo.import_json("not json")


def test_gpx_repository(db, tmp_path):
    store = tmp_path / "store"
    repo = GpxRepository(db, store)
    src = tmp_path / "my route.gpx"
    src.write_bytes(GPX11)
    gid, info = repo.import_file(src)
    gid2, _ = repo.import_file(src)
    recs = repo.list()
    assert len(recs) == 2 and recs[0].exists
    assert {r.file_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] for r in recs} == {"my_route.gpx", "my_route_2.gpx"}
    repo.rename(gid, "Renamed")
    assert repo.get(gid).name == "Renamed"
    out = tmp_path / "out.gpx"
    repo.export_copy(gid, out)
    assert out.read_bytes() == GPX11
    assert repo.revalidate(gid).points == 5
    path = repo.get(gid).file_path
    repo.delete(gid)
    assert not (store / path.rsplit("/", 1)[-1]).exists()
    bad = tmp_path / "bad.gpx"
    bad.write_bytes(b"<gpx/>")
    with pytest.raises(GpxError):
        repo.import_file(bad)
    assert len(repo.list()) == 1  # nothing copied or inserted for invalid files
    assert len(list(store.iterdir())) == 1
