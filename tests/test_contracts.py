"""Android contracts: checks written in the check language, decided against the UI tree."""
from types import SimpleNamespace as NS

from verdikt_core import contracts as C


def el(cls, text=None, desc=None, y=0, rid=None, **kw):
    flags = dict(is_clickable=False, is_editable=False, is_focused=False, is_selected=False, is_checked=False,
                 is_checkable=False, is_enabled=True, hint_text=None)
    flags.update(kw)
    return NS(class_name='android.widget.' + cls, text=text, content_description=desc, resource_name=rid,
              bbox_pixels=NS(x_min=0, x_max=1080, y_min=y, y_max=y + 100), **flags)


def test_checks_decide_against_the_ui_tree():
    screen = C.to_screen([el('TextView', 'Pasta', y=100), el('TextView', 'Pasta', y=300),
                          el('EditText', 'Ann', y=500, hint_text='Name', is_editable=True),
                          el('Switch', 'Wi-Fi', y=700, is_checkable=True, is_checked=True)], lambda e: True)
    checks, bad = C.parse(['count StaticText "Pasta" == 2', 'TextField "Name" value "Ann"', 'Switch "Wi-Fi" checked',
                           'text "Cake" absent', 'text "Pasta" visible'])
    assert not bad
    assert [ok for _, ok, _ in C.evaluate(checks, screen)] == [True, True, True, True, False]  # last: ambiguous


def test_android_class_names_are_accepted_as_roles_and_evidence_must_have_been_seen():
    screen = C.to_screen([el('CheckBox', desc='to-do: X', is_checkable=True)], lambda e: True)
    checks, bad = C.parse(['CheckBox "to-do: X" visible'])
    assert not bad and C.held_on_any(checks, [screen])[0][1]
    missing, _ = C.parse(['text "Y" visible'])
    assert not C.held_on_any(missing, [screen])[0][1]
