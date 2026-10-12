import pytest

from proofop.targeting import Target, resolve
from proofop.tree import parse_tree


@pytest.fixture
def els():
    return parse_tree(
        [
            {
                "type": "Button",
                "AXLabel": "Save",
                "AXUniqueId": "saveButton",
                "frame": {"x": 10, "y": 10, "width": 20, "height": 20},
            },
            {"type": "Button", "AXLabel": "Save", "frame": {"x": 100, "y": 100, "width": 20, "height": 20}},
            {"type": "TextField", "AXValue": "Draft", "frame": {"x": 0, "y": 200, "width": 100, "height": 40}},
        ]
    )


def test_bounds_win_over_everything(els):
    point, how = resolve(Target(bounds="0,0,10,10", id="saveButton", text="Save"), els)
    assert point == (5, 5) and how == "bounds"


def test_index_resolves_to_center(els):
    point, how = resolve(Target(index=1), els)
    assert point == (110, 110) and how == "index"


def test_index_out_of_range_is_error(els):
    point, how = resolve(Target(index=99), els)
    assert point is None and "index 99" in how


def test_id_before_text(els):
    point, how = resolve(Target(id="saveButton", text="Save", text_index=1), els)
    assert point == (20, 20) and how == "id"


def test_text_matches_label_or_value_with_index(els):
    assert resolve(Target(text="Save", text_index=1), els) == ((110, 110), "text")
    assert resolve(Target(text="draft"), els) == ((50, 220), "text")


def test_no_locator_is_error(els):
    point, how = resolve(Target(), els)
    assert point is None and "no locator" in how


def test_bad_bounds_string_is_error(els):
    point, how = resolve(Target(bounds="1,2,3"), els)
    assert point is None and "bounds" in how


def test_unknown_id_falls_back_to_text(els):
    assert resolve(Target(id="nope", text="Save"), els) == ((20, 20), "text")


# ---------- chosen / refind: the element the agent picked, on the screen as it is now ----------

from proofop.targeting import chosen, refind  # noqa: E402


def _row(label, y, ident="row", type_="Button", value=None):
    node = {"type": type_, "AXLabel": label, "AXUniqueId": ident, "frame": {"x": 0, "y": y, "width": 100, "height": 40}}
    if value is not None:
        node["AXValue"] = value
    return node


def test_chosen_picks_the_element_each_locator_names(els):
    assert chosen(Target(index=1), els) is els[1]
    assert chosen(Target(id="saveButton"), els) is els[0]
    assert chosen(Target(text="Save", text_index=1), els) is els[1]
    assert chosen(Target(bounds="0,0,10,10"), els) is None
    assert chosen(Target(index=99), els) is None


def test_refind_follows_an_element_that_moved():
    seen = parse_tree([_row("Banner", 0, "banner"), _row("Delete", 100), _row("Keep", 140)])
    live = parse_tree([_row("Banner", 0, "banner"), _row("New item", 100), _row("Delete", 140), _row("Keep", 180)])
    now = refind(seen[1], live)
    assert now is not None and now.label == "Delete" and now.y1 == 140


def test_refind_prefers_the_nearest_of_several_same_labels():
    seen = parse_tree([_row("Edit", 100), _row("Edit", 300)])
    live = parse_tree([_row("Edit", 120), _row("Edit", 320)])
    assert refind(seen[1], live).y1 == 320


def test_refind_returns_none_when_the_element_is_gone():
    seen = parse_tree([_row("Delete", 100)])
    live = parse_tree([_row("Undo", 100, "undo")])
    assert refind(seen[0], live) is None


def test_refind_does_not_cross_types_or_identifiers():
    seen = parse_tree([_row("OK", 100, "ok")])
    live = parse_tree([_row("OK", 100, "other"), _row("OK", 100, "ok", type_="StaticText")])
    assert refind(seen[0], live) is None
