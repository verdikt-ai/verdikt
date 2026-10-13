"""Deterministic checks (`verdikt.checks`): grammar, matchers, polling, verdict composition,
proposals, the server hook, replay, sync and the PR gate."""

from __future__ import annotations

import json

import pytest

from verdikt_core.ui import checks
from verdikt_core.ui.checks import CheckResult, evaluate, parse_check
from verdikt_core.ui.tree import parse_tree


def _node(t, label="", value="", ident="", x=0, y=0, w=100, h=20, enabled=True, traits=None):
    return {"type": t, "AXLabel": label, "AXValue": value, "AXUniqueId": ident,
            "frame": {"x": x, "y": y, "width": w, "height": h}, "enabled": enabled, "traits": traits or []}


class Shot:
    def __init__(self, nodes, page=None, foreground_name="App"):
        self.elements = parse_tree(nodes)
        self.page = page
        self.foreground_name = foreground_name


EXAMPLES = [
    ('text "Order placed"', 'text "Order placed"'),
    ('text ~"order placed"', 'text ~"order placed"'),
    ("text /Order #\\d+ placed/", "text /Order #\\d+ placed/"),
    ('Button "Place order" enabled', 'Button "Place order" enabled'),
    ('Button "Pay" disabled within 10s', 'Button "Pay" disabled within 10s'),
    ('StaticText "Payment failed" absent', 'StaticText "Payment failed" absent'),
    ('Switch "Dark mode" checked', 'Switch "Dark mode" checked'),
    ('TextField "Email" value "{{email}}"', 'TextField "Email" value "{{email}}"'),
    ('id=checkout.total contains "$"', 'id=checkout.total contains "$"'),
    ("count Cell >= 3", "count Cell >= 3"),
    ('url contains "/orders/" [warning]', 'url contains "/orders/" [warning]'),
    ("screen changed", "screen changed"),
]


@pytest.mark.parametrize("line,normal", EXAMPLES)
def test_parse_table_and_render_round_trip(line, normal):
    c = parse_check("Check: " + line)
    assert c.problems == ()
    assert c.render() == normal
    assert parse_check(c.render()).render() == normal


def test_parse_specifics():
    c = parse_check('Button "Pay" disabled within 10s')
    assert (c.subject, c.role, c.matcher, c.timeout_s) == ("role", "Button", "disabled", 10.0)
    assert parse_check('url contains "/x" [warning]').warning is True
    assert parse_check('text "a" within 600s').timeout_s == 60.0  # capped


@pytest.mark.parametrize(
    "line,needle",
    [
        ('Bogus "x"', "unknown subject"),
        ("text /([a-z]/", None),  # a bad regex parses; it simply never matches
        ("count Cell", "count needs"),
        ('Button "x" >= 2', "only applies to count"),
        ("url visible", "url needs"),
        ("screen enabled", "screen needs"),
        ('text "a" frobbed', "unknown matcher"),
    ],
)
def test_parse_problems_are_kept(line, needle):
    c = parse_check(line)
    if needle is None:
        return
    assert c.problems and needle in "; ".join(c.problems)
    assert c.render() == line  # a problem line is kept as written


def test_text_is_exact_after_whitespace_collapse_and_case_sensitive():
    shot = Shot([_node("StaticText", "Order   placed ")])
    assert checks.match_once(parse_check('text "Order placed"'), shot)[0] is True
    assert checks.match_once(parse_check('text "order placed"'), shot)[0] is None


def test_tilde_is_case_insensitive_substring_and_regex_flag():
    shot = Shot([_node("StaticText", "Your Order Placed today")])
    assert checks.match_once(parse_check('text ~"order placed"'), shot)[0] is True
    assert checks.match_once(parse_check("text /order placed/i"), shot)[0] is True
    assert checks.match_once(parse_check("text /order placed/"), shot)[0] is None


def test_role_matches_label_only_text_falls_back_to_value():
    shot = Shot([_node("TextField", "Email", value="a@b.test")])
    assert checks.match_once(parse_check('TextField "a@b.test"'), shot)[0] is None
    assert checks.match_once(parse_check('text "a@b.test"'), shot)[0] is True
    assert checks.match_once(parse_check('TextField "Email" value "a@b.test"'), shot)[0] is True


def test_id_suffix_match():
    shot = Shot([_node("Button", "Go", ident="com.app:id/login.submit")])
    assert checks.match_once(parse_check("id=login.submit"), shot)[0] is True
    assert checks.match_once(parse_check("id=submit"), shot)[0] is True
    assert checks.match_once(parse_check("id=bmit"), shot)[0] is None


def test_checked_reads_value_or_selected_trait_and_enabled():
    shot = Shot([_node("Switch", "Dark mode", value="on"), _node("Switch", "Wifi", value="off"), _node("Button", "Pay", enabled=False)])
    assert checks.match_once(parse_check('Switch "Dark mode" checked'), shot)[0] is True
    assert checks.match_once(parse_check('Switch "Wifi" unchecked'), shot)[0] is True
    assert checks.match_once(parse_check('Button "Pay" disabled'), shot)[0] is True
    assert checks.match_once(parse_check('Button "Pay" enabled'), shot)[0] is None


def test_focused_unsupported_without_page_fails_with_reason():
    ok, actual, _ = checks.match_once(parse_check('TextField "Email" focused'), Shot([_node("TextField", "Email")]))
    assert ok is False and "not reported" in actual


def test_count_url_title():
    shot = Shot([_node("Cell", f"Row {i}") for i in range(3)], page={"url": "https://x.test/orders/7#top", "title": "Order 7"})
    assert checks.match_once(parse_check("count Cell >= 3"), shot)[0] is True
    assert checks.match_once(parse_check("count Cell == 2"), shot)[0] is None
    assert checks.match_once(parse_check('url contains "/orders/"'), shot)[0] is True
    assert checks.match_once(parse_check('title equals "Order 7"'), shot)[0] is True
    no_page = Shot([])
    ok, actual, _ = checks.match_once(parse_check('url contains "/x"'), no_page)
    assert ok is False and "web only" in actual


def test_screen_changed_against_before_hash():
    from verdikt_core.ui.tree import tree_value_hash

    before = Shot([_node("Switch", "A", value="off")])
    after = Shot([_node("Switch", "A", value="on")])
    h = tree_value_hash(before.elements)
    assert checks.match_once(parse_check("screen changed"), after, before_hash=h)[0] is True
    assert checks.match_once(parse_check("screen unchanged"), before, before_hash=h)[0] is True


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    async def sleep(self, s):
        self.t += s


async def _eval(line, shots, **kw):
    clock = Clock()
    it = iter(shots)
    last = {"s": None}

    async def capture():
        try:
            last["s"] = next(it)
        except StopIteration:
            pass
        return last["s"]

    return await evaluate(line, capture, clock=clock, sleep=clock.sleep, timeout_s=kw.pop("timeout_s", 1.0), **kw), clock


async def test_ambiguous_fails_immediately_without_polling():
    shot = Shot([_node("Cell", "Settings", y=0), _node("Cell", "Settings", y=40)])
    r, clock = await _eval('Cell "Settings"', [shot, shot, shot])
    assert r.outcome == "fail" and "ambiguous" in r.actual and clock.t == 0.0
    assert "[0]" in r.actual and "[1]" in r.actual


async def test_zero_matches_polls_then_passes_or_lists_nearest():
    miss = Shot([_node("Button", "Place your order"), _node("Link", "Order history")])
    hit = Shot([_node("Button", "Place order")])
    r, clock = await _eval('Button "Place order"', [miss, miss, hit])
    assert r.outcome == "pass" and clock.t == pytest.approx(0.5)
    r, _ = await _eval('Button "Place order"', [miss] * 10)
    assert r.outcome == "fail" and "after 1.0s" in r.actual
    assert r.actual.index('Button "Place your order"') < r.actual.index("Order history") if "Order history" in r.actual else True


async def test_absent_must_hold_for_a_second_and_waits_for_disappearance():
    gone = Shot([])
    r, clock = await _eval('StaticText "Saving" absent', [gone], timeout_s=5)
    assert r.outcome == "pass" and clock.t == pytest.approx(checks.ABSENT_HOLD_S)
    there = Shot([_node("StaticText", "Saving")])
    r, clock = await _eval('StaticText "Saving" absent', [there, there, gone], timeout_s=5)
    assert r.outcome == "pass" and clock.t == pytest.approx(0.5 + checks.ABSENT_HOLD_S)
    # Appears after a moment (a spinner not yet shown): not absent.
    r, _ = await _eval('StaticText "Saving" absent within 2s', [gone, there, there, there, there, there, there, there, there, there])
    assert r.outcome == "fail"


async def test_warning_check_reports_warning_and_placeholders_resolve():
    r, _ = await _eval('text "Nope" [warning]', [Shot([])])
    assert r.outcome == "warning"
    r, _ = await _eval('TextField "Email" value "{{email}}"', [Shot([_node("TextField", "Email", value="q@x.test")])], placeholders={"email": "q@x.test"})
    assert r.outcome == "pass"


async def test_problem_line_evaluates_to_fail_with_the_problem():
    r, _ = await _eval('Bogus "x"', [Shot([])])
    assert r.outcome == "fail" and "unknown subject" in r.actual


def _r(outcome):
    return CheckResult("e", outcome, "a")












# ---------- server hook ----------




class _Sess:
    def __init__(self, tmp_path, shot):
        self.run = type("R", (), {"path": str(tmp_path)})()
        self.recorder = _Rec()
        self.last_screen = shot
        self.shot = shot
        self.captures = 0

    async def screen(self, settle_s=2.0, record=False):
        self.captures += 1
        self.last_screen = self.shot
        return self.shot


SCEN = """# Shop

## Checkout
Scenario-Id: s-1
1. The order is confirmed
   Check: text "Order placed"
2. A receipt is offered
"""






def _progress(tmp_path):
    return json.loads((tmp_path / "progress.json").read_text())










# ---------- sync, replay, PR gate ----------












