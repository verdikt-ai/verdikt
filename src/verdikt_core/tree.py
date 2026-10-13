"""Accessibility tree model built from `idb ui describe-all --json` output (a flat node list)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

INTERACTIVE_TYPES = frozenset(
    {
        "Button",
        "TextField",
        "SecureTextField",
        "SearchField",
        "TextView",
        "Cell",
        "Link",
        "Switch",
        "Toggle",
        "Tab",
        "TabBar",
        "SegmentedControl",
        "Slider",
        "Stepper",
        "Picker",
        "PickerWheel",
        "MenuItem",
        "Key",
    }
)


@dataclass
class Element:
    index: int
    type: str
    label: str
    value: str
    identifier: str
    x1: int
    y1: int
    x2: int
    y2: int
    enabled: bool
    traits: list[str] = field(default_factory=list)
    pid: int | None = None

    @property
    def center(self) -> tuple[int, int]:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)

    @property
    def interactive(self) -> bool:
        return self.type in INTERACTIVE_TYPES

    def compact_line(self, with_value: bool = True, with_bounds: bool = True) -> str:
        parts = [f"[{self.index}]", self.type]
        if self.label or self.interactive:
            parts.append(f'"{self.label}"')
        if with_value and self.value:
            parts.append(f'value="{self.value}"')
        if self.identifier:
            parts.append(f"id={self.identifier}")
        if with_bounds:
            parts.append(f"({self.x1},{self.y1})-({self.x2},{self.y2})")
        if not self.enabled:
            parts.append("disabled")
        if "Selected" in self.traits:
            parts.append("selected")
        return " ".join(parts)


def _text(node: dict, *keys: str) -> str:
    for key in keys:
        val = node.get(key)
        if val not in (None, ""):
            return str(val)
    return ""


def parse_tree(raw: list[dict]) -> list[Element]:
    elements: list[Element] = []
    for i, node in enumerate(raw):
        frame = node.get("frame") or {}
        x = int(frame.get("x", 0) or 0)
        y = int(frame.get("y", 0) or 0)
        w = int(frame.get("width", 0) or 0)
        h = int(frame.get("height", 0) or 0)
        elements.append(
            Element(
                index=i,
                type=str(node.get("type") or "Unknown"),
                label=_text(node, "AXLabel", "label", "title"),
                value=_text(node, "AXValue", "value"),
                identifier=_text(node, "AXUniqueId", "identifier"),
                x1=x,
                y1=y,
                x2=x + w,
                y2=y + h,
                enabled=bool(node.get("enabled", True)),
                traits=list(node.get("traits") or []),
                pid=node.get("pid"),
            )
        )
    return elements


def _is_noise(e: Element) -> bool:
    if e.type == "Application":
        return True
    return not (e.interactive or e.label or e.value or e.identifier)


def visible_elements(elements: list[Element]) -> list[Element]:
    return [e for e in elements if not _is_noise(e)]


def compact(elements: list[Element]) -> str:
    return "\n".join(e.compact_line() for e in visible_elements(elements))


def has_unlabeled_or_ambiguous_nodes(elements: list[Element]) -> bool:
    """True when the tree has at least one interactive node with no label and no
    identifier (nothing a screenshot-free description could name), or two or more visible
    nodes that share the same non-empty label (ambiguous without positions/screenshot to
    disambiguate). Backs `screenshot_mode: auto` in `server.screen`: with no such nodes, the
    compact tree text alone is enough to act on and the screenshot can be skipped."""
    visible = visible_elements(elements)
    labels: dict[str, int] = {}
    for e in visible:
        if e.interactive and not e.label and not e.identifier:
            return True
        if e.label:
            labels[e.label] = labels.get(e.label, 0) + 1
    return any(count > 1 for count in labels.values())


def to_json_dict(elements: list[Element]) -> list[dict]:
    """Visible elements as plain dicts, for `hierarchy_format: pretty` (`json.dumps(...,
    indent=2)` on the result)."""
    out = []
    for e in visible_elements(elements):
        out.append(
            {
                "index": e.index,
                "type": e.type,
                "label": e.label,
                "value": e.value,
                "identifier": e.identifier,
                "bounds": [e.x1, e.y1, e.x2, e.y2],
                "enabled": e.enabled,
                "traits": e.traits,
            }
        )
    return out


def tree_hash(elements: list[Element]) -> str:
    stable = "\n".join(
        e.compact_line(with_value=False, with_bounds=False).split("] ", 1)[1]
        for e in visible_elements(elements)
    )
    return hashlib.sha1(stable.encode()).hexdigest()[:12]


def tree_value_hash(elements: list[Element]) -> str:
    """`tree_hash` with element values included: a toggled switch ("0" -> "1"), a checked box
    or a stepper's count changes it where `tree_hash` (labels and structure only) does not."""
    stable = "\n".join(
        e.compact_line(with_value=True, with_bounds=False).split("] ", 1)[1]
        for e in visible_elements(elements)
    )
    return hashlib.sha1(stable.encode()).hexdigest()[:12]


CLOCK_PATTERN = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")


def screen_shape(elements: list[Element]) -> str:
    """What the screen looks like regardless of which capture looked at it: every visible line
    without its index and bounds, values kept (a typed character counts), clock-like text masked
    so a ticking timer never ends a change wait early or keeps a stillness check from passing."""
    lines = (
        e.compact_line(with_value=True, with_bounds=False).split("] ", 1)[1]
        for e in visible_elements(elements)
    )
    return CLOCK_PATTERN.sub("<time>", "\n".join(lines))


def find(elements: list[Element], text: str, role: str | None = None) -> list[Element]:
    needle = text.lower()
    return [
        e
        for e in elements
        if (needle in e.label.lower() or needle in e.value.lower() or needle in e.identifier.lower())
        and (role is None or e.type == role)
    ]


def foreground_app(elements: list[Element]) -> tuple[str | None, int | None]:
    for e in elements:
        if e.type == "Application":
            return (e.label or None, e.pid)
    return (None, None)


def screen_size(elements: list[Element]) -> tuple[int, int]:
    for e in elements:
        if e.type == "Application":
            return (e.x2 - e.x1, e.y2 - e.y1)
    return (0, 0)
