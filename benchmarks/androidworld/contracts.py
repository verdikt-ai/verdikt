"""Contracted operation: the agent states what must hold, in Verdikt's own check language,
and deterministic code - not the model - decides whether it does.

- Action contract: an action may carry `expect` checks, evaluated on the screen the action
  produced; a miss is reported in the same tool result, so a swallowed tap or a wrong field
  is caught on the step it happens.
- Goal contract: `contract` records checks that hold on screen once the goal is done.
  `finish` is refused once (without spending the step) while they fail on the current screen.
- Answer evidence: `answer` may cite checks for the facts it reports; each must have held on
  some screen seen in the episode, else the answer is refused once.

Checks use `verdikt.checks` unchanged (e.g. `text "Pasta" visible`, `count StaticText ~"Pasta"
== 1`, `TextField "Name" value "Ann"`, `Switch "Wi-Fi" checked`), over the UI tree mapped to
Verdikt elements the way `verdikt.sessions.android` maps uiautomator nodes.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from verdikt_core.ui.checks import Check, match_once, nearest_labels, parse_check
from verdikt_core.ui.tree import parse_tree

# Same class -> type map as verdikt.sessions.android.CLASS_TYPE_MAP.
CLASS_TYPE = {'Button': 'Button', 'ImageView': 'Image', 'ImageButton': 'Button', 'CheckBox': 'Switch',
              'Switch': 'Switch', 'RadioButton': 'Radio', 'EditText': 'TextField', 'TextView': 'StaticText'}


def _node(e: Any) -> dict | None:
    cls = (e.class_name or '').rsplit('.', 1)[-1]
    kind = CLASS_TYPE.get(cls) or ('Button' if e.is_clickable else 'StaticText' if (e.text or e.content_description) else None)
    if kind is None and e.is_checkable:
        kind = 'Switch'
    if kind is None:
        return None
    b = e.bbox_pixels
    traits = [t for t, on in (('Focused', e.is_focused), ('Selected', e.is_selected or e.is_checked)) if on]
    return {
        'type': kind,
        # A field is named by its description or hint; what was typed into it is its value.
        'AXLabel': ((e.content_description or e.hint_text or '') if kind == 'TextField'
                    else e.content_description or e.text or ''),
        'AXValue': (e.text or '') if kind == 'TextField' else ('on' if e.is_checked else 'off') if e.is_checkable else '',
        'AXUniqueId': (e.resource_name or '').rsplit('/', 1)[-1],
        'frame': {'x': b.x_min, 'y': b.y_min, 'width': b.x_max - b.x_min, 'height': b.y_max - b.y_min},
        'enabled': e.is_enabled is not False,
        'traits': traits,
    }


def to_screen(ui_elements: list, keep: Any) -> SimpleNamespace:
    """Verdikt elements for the visible UI elements; each keeps the agent's [index]."""
    pairs = [(i, n) for i, e in enumerate(ui_elements) if keep(e) and (n := _node(e)) is not None]
    elements = parse_tree([n for _, n in pairs])
    for (i, _), el in zip(pairs, elements):
        el.index = i
    return SimpleNamespace(elements=elements)


# Android class names an agent reads off the element list, as Verdikt roles.
ROLE_ALIASES = {'CheckBox': 'Switch', 'ToggleButton': 'Switch', 'CheckedTextView': 'StaticText',
                'EditText': 'TextField', 'TextView': 'StaticText', 'ImageButton': 'Button',
                'ImageView': 'Image', 'RadioButton': 'Radio'}


def _alias(line: str) -> str:
    head, _, rest = line.strip().partition(' ')
    return f'{ROLE_ALIASES[head]} {rest}' if head in ROLE_ALIASES else line


def parse(lines: list[str] | str | None) -> tuple[list[Check], list[str]]:
    if isinstance(lines, str):
        lines = [lines]
    checks, bad = [], []
    for line in lines or []:
        c = parse_check(_alias(line))
        (bad.append(f'{line!r}: {"; ".join(c.problems)}') if c.problems else checks.append(c))
    return checks, bad


def evaluate(checks: list[Check], screen: Any) -> list[tuple[Check, bool, str]]:
    out = []
    for c in checks:
        ok, actual, _ = match_once(c, screen)
        if ok is None and not actual:
            near = nearest_labels(c, list(screen.elements))
            actual = 'no match' + (f'; nearest: {", ".join(near)}' if near else '')
        out.append((c, ok is True, actual))
    return out


def held_on_any(checks: list[Check], screens: list[Any]) -> list[tuple[Check, bool, str]]:
    """Evidence: each check must have held on at least one screen seen in the episode."""
    out = []
    for c in checks:
        hit = None
        for screen in reversed(screens):
            ok, actual, _ = match_once(c, screen)
            if ok is True:
                hit = actual or 'held'
                break
        out.append((c, hit is not None, hit or 'held on no screen seen in this episode'))
    return out


def render(results: list[tuple[Check, bool, str]], title: str) -> str:
    lines = [f'{title}: {"PASS" if all(ok for _, ok, _ in results) else "FAIL"}']
    lines += [f'  {"ok  " if ok else "MISS"} {c.raw} -> {actual}' for c, ok, actual in results]
    return '\n'.join(lines)
