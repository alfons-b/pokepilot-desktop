import json

import pytest
from PySide6.QtGui import QImage

from app.pgsharp import vision
from app.pgsharp.features import FEATURE_CATALOG
from app.pgsharp.layout import Availability, FeatureMapping, LayoutError, LayoutStore, PgsharpLayout, slugify
from tests.fakes.fake_device import HOME, MENU


def img(png: bytes) -> QImage:
    return QImage.fromData(png, "PNG")


def test_new_layout_has_all_features_unverified():
    lay = PgsharpLayout()
    assert set(lay.features) == {f.id for f in FEATURE_CATALOG}
    assert all(f.availability is Availability.UNVERIFIED for f in lay.features.values())


def test_slugify():
    assert slugify(" Teleport Button! ") == "teleport_button"
    with pytest.raises(LayoutError):
        slugify("!!!")


def test_elements_unique_ids_and_bounds():
    lay = PgsharpLayout()
    a = lay.add_element("Menu", 0.1, 0.2)
    b = lay.add_element("menu", 0.3, 0.4)
    assert (a.id, b.id) == ("menu", "menu_2")
    with pytest.raises(LayoutError):
        lay.add_element("bad", 1.5, 0.1)
    lay.move_element("menu", 0.5, 0.5)
    assert lay.elements["menu"].x == 0.5


def test_remove_element_clears_feature_references():
    lay = PgsharpLayout()
    lay.add_element("menu", 0.1, 0.1)
    lay.add_element("tp", 0.2, 0.2)
    lay.update_feature(FeatureMapping("teleport", open_steps=["menu", "tp"], toggle_element="tp"))
    touched = lay.remove_element("tp")
    assert touched == ["teleport"]
    assert lay.features["teleport"].open_steps == ["menu"]
    assert lay.features["teleport"].toggle_element is None


def test_update_feature_validation():
    lay = PgsharpLayout()
    with pytest.raises(LayoutError):
        lay.update_feature(FeatureMapping("teleport", open_steps=["missing"]))
    with pytest.raises(LayoutError):
        lay.update_feature(FeatureMapping("teleport", verify_state="missing"))
    with pytest.raises(LayoutError):
        lay.update_feature(FeatureMapping("not_a_feature"))


def test_remove_state_clears_verify():
    lay = PgsharpLayout()
    st = lay.add_state("Menu open")
    lay.update_feature(FeatureMapping("teleport", verify_state=st.id))
    lay.remove_state(st.id)
    assert lay.features["teleport"].verify_state is None


def test_roundtrip_and_store(tmp_path):
    lay = PgsharpLayout()
    lay.set_reference(540, 1200)
    lay.add_element("menu", 0.1, 0.05)
    st = lay.add_state("Menu open")
    st.regions.append(vision.make_region(img(MENU), 0, 0, 0.5, 0.1))
    lay.update_feature(FeatureMapping("teleport", Availability.AVAILABLE, ["menu"], None, st.id, "free edition"))
    store = LayoutStore(tmp_path / "layout.json")
    store.save(lay)
    loaded, warn = store.load()
    assert warn is None
    assert loaded.to_dict()["elements"] == lay.to_dict()["elements"]
    assert loaded.features["teleport"].availability is Availability.AVAILABLE
    assert loaded.states[st.id].regions[0].signature == st.regions[0].signature


def test_store_corrupt_file_backed_up(tmp_path):
    path = tmp_path / "layout.json"
    path.write_text(json.dumps({"elements": [{"id": "x", "label": "x", "x": 9, "y": 0}]}))
    layout, warn = LayoutStore(path).load()
    assert warn and "invalid" in warn
    assert layout.elements == {}
    assert any(p.name.startswith("layout.json.corrupt-") for p in tmp_path.iterdir())


def test_check_resolution():
    lay = PgsharpLayout()
    assert lay.check_resolution(1080, 1920) is None  # nothing calibrated
    lay.set_reference(540, 1200)
    lay.add_element("m", 0.1, 0.1)
    assert lay.check_resolution(1080, 2400) is None  # same aspect, scales
    assert "Recalibrate" in lay.check_resolution(2400, 1080)  # rotated
    assert lay.check_resolution(1080, 1920) is not None


# ------------------------------------------------------------------- vision
def test_signature_and_difference():
    a = vision.signature(img(HOME))
    assert len(a) == vision.SIG_SIZE ** 2
    assert vision.difference(a, a) == 0
    b = vision.signature(img(MENU))
    assert vision.difference(a, b) > 0.04  # box covers ~5% of the full screen
    assert vision.decode(vision.encode(a)) == a
    with pytest.raises(ValueError):
        vision.decode(vision.encode(b"short"))


def test_verify_state_match_and_scale_invariance():
    lay = PgsharpLayout()
    st = lay.add_state("menu")
    st.regions.append(vision.make_region(img(MENU), 0, 0, 0.5, 0.1))
    assert vision.verify_state(img(MENU), st).matched is True
    assert vision.verify_state(img(HOME), st).matched is False
    # Same screen at double resolution still matches (normalized regions).
    big = img(MENU).scaled(1080, 2400)
    assert vision.verify_state(big, st).matched is True
    empty = lay.add_state("empty")
    assert vision.verify_state(img(MENU), empty).matched is None


def test_detect_states_orders_matches_first():
    lay = PgsharpLayout()
    home = lay.add_state("home")
    home.regions.append(vision.make_region(img(HOME), 0, 0, 0.5, 0.1))
    menu = lay.add_state("menu")
    menu.regions.append(vision.make_region(img(MENU), 0, 0, 0.5, 0.1))
    result = vision.detect_states(img(MENU), [home, menu])
    assert result[0].state_id == "menu" and result[0].matched
    assert result[1].matched is False
