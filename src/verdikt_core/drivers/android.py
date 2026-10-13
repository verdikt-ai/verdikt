"""Android over plain adb: `uiautomator dump` for the tree, `screencap` for pixels, `input` for actions."""
from __future__ import annotations

import re
import subprocess
import xml.etree.ElementTree as ET

from verdikt_core.drivers.base import Shot

CLASS_TYPE = {'Button': 'Button', 'ImageView': 'Image', 'ImageButton': 'Button', 'CheckBox': 'Switch', 'Switch': 'Switch',
              'ToggleButton': 'Switch', 'RadioButton': 'Radio', 'EditText': 'TextField', 'TextView': 'StaticText'}
KEYS = {'back': '4', 'home': '3', 'enter': '66', 'delete': '67', 'tab': '61', 'recents': '187', 'escape': '111', 'search': '84'}
BOUNDS = re.compile(r'\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]')


def _node(n: ET.Element) -> dict | None:
    a = n.attrib
    cls = (a.get('class') or '').rsplit('.', 1)[-1]
    text, desc = a.get('text') or '', a.get('content-desc') or ''
    kind = CLASS_TYPE.get(cls) or ('Button' if a.get('clickable') == 'true' else 'StaticText' if (text or desc) else None)
    if kind is None and a.get('checkable') == 'true':
        kind = 'Switch'
    if kind is None:
        return None
    if kind == 'TextField' and a.get('password') == 'true':
        kind = 'SecureTextField'
    m = BOUNDS.match(a.get('bounds') or '')
    x1, y1, x2, y2 = (int(v) for v in m.groups()) if m else (0, 0, 0, 0)
    field = kind in ('TextField', 'SecureTextField')
    traits = [t for t, on in (('Focused', a.get('focused') == 'true'),
                              ('Selected', a.get('selected') == 'true' or a.get('checked') == 'true')) if on]
    rid = a.get('resource-id') or ''
    return {'type': kind, 'AXLabel': desc or ('' if field else text), 'AXValue': text if field else ('on' if a.get('checked') == 'true' else ''),
            'AXUniqueId': rid.rsplit('/', 1)[-1], 'frame': {'x': x1, 'y': y1, 'width': x2 - x1, 'height': y2 - y1},
            'enabled': a.get('enabled') != 'false', 'traits': traits, 'package': a.get('package') or ''}


def parse_dump(xml_text: str) -> list[dict]:
    xml_text = xml_text[xml_text.find('<'):xml_text.rfind('>') + 1]
    root = ET.fromstring(xml_text)
    return [x for n in root.iter('node') if (x := _node(n)) is not None]


class AndroidDriver:
    platform = 'Android'

    def __init__(self, serial: str, adb: str = 'adb'):
        self.serial, self.adb = serial, adb

    def _run(self, *args: str, text: bool = True, timeout: float = 30):
        out = subprocess.run([self.adb, '-s', self.serial, *args], capture_output=True, timeout=timeout, text=text)
        if out.returncode != 0:
            raise RuntimeError(f'adb {" ".join(args[:3])} failed: {(out.stderr or "")[:200]}')
        return out.stdout

    def capture(self) -> Shot:
        nodes = parse_dump(self._run('exec-out', 'uiautomator', 'dump', '/dev/tty'))
        png = self._run('exec-out', 'screencap', '-p', text=False)
        w = max((n['frame']['x'] + n['frame']['width'] for n in nodes), default=0)
        h = max((n['frame']['y'] + n['frame']['height'] for n in nodes), default=0)
        pkg = next((n['package'] for n in nodes if n.get('package')), '')
        return Shot(png=png, nodes=nodes, width=w, height=h, foreground=pkg)

    def tap(self, x: int, y: int) -> None:
        self._run('shell', 'input', 'tap', str(x), str(y))

    def type_text(self, text: str) -> None:
        for i, part in enumerate(text.split('\n')):
            if i:
                self.press('enter')
            if part:
                self._run('shell', 'input', 'text', re.sub(r'([\\\'"`$&|;<>()!*?\[\]{}#~ ])', lambda m: '%s' if m.group(1) == ' ' else '\\' + m.group(1), part))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 400) -> None:
        self._run('shell', 'input', 'swipe', str(x1), str(y1), str(x2), str(y2), str(duration_ms))

    def press(self, key: str) -> None:
        if key.lower() not in KEYS:
            raise ValueError(f'unknown key {key!r}; use one of {sorted(KEYS)}')
        self._run('shell', 'input', 'keyevent', KEYS[key.lower()])

    def launch(self, app: str) -> None:
        self._run('shell', 'monkey', '-p', app, '-c', 'android.intent.category.LAUNCHER', '1')

    def close(self) -> None:
        pass
