"""Locate an element to act on. Resolution order: bounds -> index -> id -> text."""

from __future__ import annotations

from pydantic import BaseModel, Field

from proofop.tree import Element

Point = tuple[int, int]


class Target(BaseModel):
    index: int | None = Field(None, description="Element index from the last `screen` call")
    id: str | None = Field(None, description="Accessibility identifier (exact match)")
    text: str | None = Field(None, description="Label or value (case-insensitive exact match)")
    text_index: int = Field(0, description="Which match to use when several share the text")
    bounds: str | None = Field(None, description="Explicit 'x1,y1,x2,y2' in points")


def has_locator(target: dict | None) -> bool:
    """Whether a recorded target dict names an element. `Target.model_dump()` always carries
    `text_index`, so an empty-looking "type into the focused field" target is never `{}`."""
    t = target or {}
    return t.get("index") is not None or bool(t.get("id") or t.get("text") or t.get("bounds"))


def _parse_bounds(s: str) -> Point | None:
    try:
        x1, y1, x2, y2 = (int(float(p)) for p in s.split(","))
    except ValueError:
        return None
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def resolve(target: Target, elements: list[Element]) -> tuple[Point | None, str]:
    """Return (tap point, strategy) or (None, error message)."""
    if target.bounds:
        point = _parse_bounds(target.bounds)
        if point is None:
            return None, f"error: bounds must be 'x1,y1,x2,y2', got {target.bounds!r}"
        return point, "bounds"

    if target.index is not None:
        if 0 <= target.index < len(elements):
            return elements[target.index].center, "index"
        return None, f"error: index {target.index} out of range (0..{len(elements) - 1})"

    if target.id:
        for e in elements:
            if e.identifier == target.id:
                return e.center, "id"

    if target.text:
        needle = target.text.lower()
        matches = [e for e in elements if e.label.lower() == needle or e.value.lower() == needle]
        if target.text_index < len(matches):
            return matches[target.text_index].center, "text"
        if matches:
            return (
                None,
                f"error: text {target.text!r} has {len(matches)} matches, "
                f"index {target.text_index} out of range",
            )

    if target.id or target.text:
        tried = ", ".join(
            p for p in [f"id={target.id}" if target.id else "", f"text={target.text}" if target.text else ""] if p
        )
        return None, f"error: no element matched ({tried})"

    return None, "error: no locator given (need index, id, text, or bounds)"


def chosen(target: Target, elements: list[Element]) -> Element | None:
    """The element an index/id/text target picks on `elements` (None for bounds or no match)."""
    if target.bounds:
        return None
    if target.index is not None:
        return elements[target.index] if 0 <= target.index < len(elements) else None
    point, _ = resolve(target, elements)
    return next((e for e in elements if e.center == point), None) if point else None


def refind(seen: Element, live: list[Element]) -> Element | None:
    """`seen` (from the screen the agent decided on) on the screen as it is now. A list that
    loaded, a toast or a keyboard can move it between the look and the action. Match by
    identity: type and identifier, then the same place and label, else the nearest element
    with the same label or value, else the only element with its identifier."""
    same = [e for e in live if e.type == seen.type and e.identifier == seen.identifier]
    box = (seen.x1, seen.y1, seen.x2, seen.y2)
    for e in same:
        if (e.x1, e.y1, e.x2, e.y2) == box and e.label == seen.label:
            return e
    cx, cy = seen.center
    for attr in ("label", "value"):
        want = getattr(seen, attr)
        hits = [e for e in same if want and getattr(e, attr) == want]
        if hits:
            return min(hits, key=lambda e: (e.center[0] - cx) ** 2 + (e.center[1] - cy) ** 2)
    if seen.identifier and len(same) == 1:
        return same[0]
    return None
