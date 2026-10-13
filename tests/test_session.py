"""A whole session against a fake device: act-then-observe, stable targeting, and the gated finish."""
import json

from verdikt_core.drivers.android import parse_dump
from verdikt_core.drivers.base import Shot
from verdikt_core.session import Session


def node(label, y, kind='Button', ident='', value=None, traits=()):
    n = {'type': kind, 'AXLabel': label, 'AXUniqueId': ident, 'frame': {'x': 0, 'y': y, 'width': 400, 'height': 80},
         'enabled': True, 'traits': list(traits)}
    if value is not None:
        n['AXValue'] = value
    return n


class FakeDriver:
    platform = 'Android'

    def __init__(self, screens):
        self.screens, self.taps, self.typed = list(screens), [], []

    def capture(self):
        nodes = self.screens[0] if len(self.screens) == 1 else self.screens.pop(0)
        return Shot(png=b'\x89PNG', nodes=nodes, width=1080, height=2400, foreground='app')

    def tap(self, x, y): self.taps.append((x, y))
    def type_text(self, text): self.typed.append(text)
    def swipe(self, *a): pass
    def press(self, key): pass
    def launch(self, app): pass
    def close(self): pass


def test_a_tap_lands_where_the_chosen_element_is_now(tmp_path):
    seen = [node('Delete', 100, ident='del')]
    moved = [node('Banner', 100, ident='b'), node('Delete', 300, ident='del')]
    d = FakeDriver([seen, moved, moved])
    s = Session(d, tmp_path / 'run')
    s.look()
    text, png = s.tap(index=0)
    assert d.taps == [(200, 340)] and 'step 2' in text and png


def test_finish_is_refused_until_every_obligation_is_proven(tmp_path):
    d = FakeDriver([[node('Kindling Ventures raised $18M', 100, kind='StaticText')]])
    s = Session(d, tmp_path / 'run', rounds=2)
    s.look()
    s.record('KNOW', 'raise amount')
    s.record('DO', 'set alarm')
    assert 'closed' in s.close('raise amount', value='$18M')
    first = s.finish('done')
    assert first.startswith('refused') and 'OPEN: DO: set alarm' in first
    s.close('set alarm', absent=True, explanation='no clock app')
    second = s.finish('done')
    assert second.startswith('refused') and 'ABSENCE CHALLENGED' in second
    third = s.finish('done')
    assert third.startswith('finished') and 'raise amount: $18M' in third
    cert = json.loads((tmp_path / 'run' / 'certificate.json').read_text())
    assert (cert['proven'], cert['absent'], cert['actions']) == (1, 1, 0)


def test_a_claim_the_screen_does_not_show_is_flagged_on_close(tmp_path):
    d = FakeDriver([[node('Total $31.40', 100, kind='StaticText')]])
    s = Session(d, tmp_path / 'run')
    s.look()
    s.record('KNOW', 'bank charge')
    assert 'does not accept' in s.close('bank charge', value='$28.00')


def test_the_action_budget_is_enforced(tmp_path):
    d = FakeDriver([[node('OK', 100)]])
    s = Session(d, tmp_path / 'run', budget=1)
    s.look()
    s.tap(x=1, y=1)
    text, _ = s.tap(x=1, y=1)
    assert text.startswith('refused')


def test_android_dump_maps_to_the_element_model():
    xml = ('<?xml version="1.0"?><hierarchy><node class="android.widget.EditText" text="Ann" content-desc="" '
           'resource-id="app:id/name" bounds="[0,100][400,180]" focused="true" clickable="true" enabled="true"/>'
           '<node class="android.widget.TextView" text="Saved" bounds="[0,200][400,260]" enabled="true"/></hierarchy>'
           'UI hierchary dumped to: /dev/tty')
    nodes = parse_dump(xml)
    assert nodes[0]['type'] == 'TextField' and nodes[0]['AXValue'] == 'Ann' and 'Focused' in nodes[0]['traits']
    assert nodes[1]['type'] == 'StaticText' and nodes[1]['AXLabel'] == 'Saved'
