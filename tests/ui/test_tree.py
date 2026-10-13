import json
from pathlib import Path

import pytest

from verdikt_core.ui.tree import (
    compact,
    find,
    foreground_app,
    has_unlabeled_or_ambiguous_nodes,
    parse_tree,
    screen_size,
    to_json_dict,
    tree_hash,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "raw_tree_dump.json"


@pytest.fixture
def raw() -> list[dict]:
    return json.loads(FIXTURE.read_text())


def test_parse_keeps_index_and_int_bounds(raw):
    els = parse_tree(raw)
    assert len(els) == len(raw)
    assert [e.index for e in els] == list(range(len(raw)))
    btn = next(e for e in els if e.identifier == "tab-account")
    assert btn.type == "Button"
    assert btn.label == "Account"
    assert (btn.x1, btn.y1, btn.x2, btn.y2) == (342, 74, 386, 114)
    assert btn.enabled is True


def test_parse_tolerates_missing_frame():
    els = parse_tree([{"type": "Button", "AXLabel": "x"}])
    assert els[0].x1 == els[0].y1 == els[0].x2 == els[0].y2 == 0


def test_compact_drops_unlabelled_generic_elements():
    els = parse_tree(
        [
            {"type": "GenericElement", "frame": {"x": 0, "y": 0, "width": 10, "height": 10}},
            {
                "type": "Button",
                "AXLabel": "Go",
                "AXUniqueId": "go",
                "frame": {"x": 1, "y": 2, "width": 3, "height": 4},
                "enabled": True,
            },
            {
                "type": "TextField",
                "AXValue": "hello",
                "frame": {"x": 0, "y": 0, "width": 10, "height": 10},
                "enabled": False,
                "traits": ["Selected"],
            },
        ]
    )
    lines = compact(els).splitlines()
    assert lines == [
        '[1] Button "Go" id=go (1,2)-(4,6)',
        '[2] TextField "" value="hello" (0,0)-(10,10) disabled selected',
    ]


def test_compact_keeps_unlabelled_interactive_elements():
    els = parse_tree([{"type": "Button", "frame": {"x": 0, "y": 0, "width": 1, "height": 1}}])
    assert compact(els) == '[0] Button "" (0,0)-(1,1)'


def test_tree_hash_ignores_values_and_bounds_but_not_labels():
    a = parse_tree(
        [{"type": "TextField", "AXValue": "a", "AXLabel": "Name", "frame": {"x": 0, "y": 0, "width": 1, "height": 1}}]
    )
    b = parse_tree(
        [{"type": "TextField", "AXValue": "b", "AXLabel": "Name", "frame": {"x": 5, "y": 5, "width": 1, "height": 1}}]
    )
    c = parse_tree(
        [{"type": "TextField", "AXValue": "a", "AXLabel": "Other", "frame": {"x": 0, "y": 0, "width": 1, "height": 1}}]
    )
    assert tree_hash(a) == tree_hash(b)
    assert tree_hash(a) != tree_hash(c)
    assert len(tree_hash(a)) == 12


def test_find_is_case_insensitive_substring_with_optional_role(raw):
    els = parse_tree(raw)
    hits = find(els, "account")
    assert any(e.identifier == "tab-account" for e in hits)
    assert all(e.type == "Button" for e in find(els, "account", role="Button"))
    assert find(els, "zzz-not-there") == []


def test_foreground_app_and_screen_size(raw):
    els = parse_tree(raw)
    name, pid = foreground_app(els)
    assert isinstance(name, str) and name
    assert isinstance(pid, int)
    w, h = screen_size(els)
    assert w > 300 and h > 600


def test_foreground_app_without_application_node():
    assert foreground_app(parse_tree([{"type": "Button"}])) == (None, None)
    assert screen_size(parse_tree([{"type": "Button"}])) == (0, 0)


# ---------- has_unlabeled_or_ambiguous_nodes (screenshot_mode: auto heuristic) ----------


def test_no_unlabeled_or_ambiguous_nodes_when_every_interactive_node_is_named():
    els = parse_tree(
        [
            {"type": "Button", "AXLabel": "Go", "frame": {"x": 0, "y": 0, "width": 1, "height": 1}},
            {"type": "TextField", "AXUniqueId": "email", "frame": {"x": 0, "y": 0, "width": 1, "height": 1}},
        ]
    )
    assert has_unlabeled_or_ambiguous_nodes(els) is False


def test_unlabeled_interactive_node_is_flagged():
    els = parse_tree([{"type": "Button", "frame": {"x": 0, "y": 0, "width": 1, "height": 1}}])
    assert has_unlabeled_or_ambiguous_nodes(els) is True


def test_duplicate_labels_are_ambiguous():
    els = parse_tree(
        [
            {"type": "Cell", "AXLabel": "Item", "frame": {"x": 0, "y": 0, "width": 1, "height": 1}},
            {"type": "Cell", "AXLabel": "Item", "frame": {"x": 0, "y": 10, "width": 1, "height": 1}},
        ]
    )
    assert has_unlabeled_or_ambiguous_nodes(els) is True


def test_non_interactive_unlabeled_node_is_dropped_as_noise_not_flagged():
    # A bare GenericElement with no label/value/id is noise (visible_elements drops it), so
    # it never reaches the ambiguity check at all.
    els = parse_tree([{"type": "GenericElement", "frame": {"x": 0, "y": 0, "width": 1, "height": 1}}])
    assert has_unlabeled_or_ambiguous_nodes(els) is False


def test_empty_tree_has_no_unlabeled_or_ambiguous_nodes():
    assert has_unlabeled_or_ambiguous_nodes([]) is False


# ---------- to_json_dict (hierarchy_format: pretty) ----------


def test_to_json_dict_matches_compact_visibility_and_shape():
    els = parse_tree(
        [
            {"type": "GenericElement", "frame": {"x": 0, "y": 0, "width": 10, "height": 10}},
            {
                "type": "Button",
                "AXLabel": "Go",
                "AXUniqueId": "go",
                "frame": {"x": 1, "y": 2, "width": 3, "height": 4},
                "enabled": True,
            },
        ]
    )
    out = to_json_dict(els)
    assert out == [
        {
            "index": 1,
            "type": "Button",
            "label": "Go",
            "value": "",
            "identifier": "go",
            "bounds": [1, 2, 4, 6],
            "enabled": True,
            "traits": [],
        }
    ]
