"""The driver interface: capture a screen (image + UI tree) and perform input."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Shot:
    """One captured screen: a PNG and the UI tree as nodes `verdikt_core.ui.tree.parse_tree` reads
    (type, AXLabel, AXValue, AXUniqueId, frame, enabled, traits)."""
    png: bytes
    nodes: list[dict] = field(default_factory=list)
    width: int = 0
    height: int = 0
    foreground: str = ''


class Driver(Protocol):
    platform: str

    def capture(self) -> Shot: ...
    def tap(self, x: int, y: int) -> None: ...
    def type_text(self, text: str) -> None: ...
    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 400) -> None: ...
    def press(self, key: str) -> None: ...
    def launch(self, app: str) -> None: ...
    def close(self) -> None: ...
