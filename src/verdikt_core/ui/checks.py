"""Deterministic checks inside scenarios: `Check:` lines the harness evaluates itself.

A criterion can carry exact assertions the harness decides with no model call:

    1. The order is confirmed
       Check: text "Order placed"
       Check: Button "Place order" absent within 10s

Grammar (one line, the `Check:` prefix optional here)::

    check    = subject [matcher] ["within" N "s"] ["[warning]"]
    subject  = "text" textpat | ROLE textpat | "id=" ident | "url" | "title"
             | "count" ROLE [textpat] | "screen"
    textpat  = '"..."'            exact after whitespace collapse, case-sensitive
             | '~"..."'           case-insensitive substring
             | "/re/" ["i"]       regex
    matcher  = visible (default) | absent | enabled | disabled | checked | unchecked
             | selected | focused | value TEXTPAT | contains TEXTPAT | matches /re/
             | equals TEXTPAT | (== | >= | <=) N  (count) | unchanged | changed  (screen)

Semantics that never bend: a positive matcher needs exactly one visible element (several fail
at once, listing them; none polls until the deadline, then lists the nearest labels); `absent`
passes as soon as nothing matches; every poll takes a fresh capture; the default timeout is 5 s
(`limits.check_timeout_s`, `$QA_CHECK_TIMEOUT_S`), `within Ns` overrides up to 60 s.

`compose_verdict` combines a criterion's checks with the agent's judgment: a failed critical
check always wins over the agent's `pass`, and the disagreement is recorded, never hidden.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import os
import re
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from verdikt_core.ui.tree import INTERACTIVE_TYPES, Element, tree_value_hash, visible_elements

ENV_CHECK_TIMEOUT = "QA_CHECK_TIMEOUT_S"
DEFAULT_TIMEOUT_S = 5.0
MAX_TIMEOUT_S = 60.0
POLL_S = 0.25
ABSENT_HOLD_S = 1.0  # `absent` must hold this long: a spinner not yet shown is not gone
NEAREST = 5
WARNING_SUFFIX = "[warning]"
CHECKED_SUFFIX = "[checked]"
CRITERION_KEY = "checks"
CRITERION_PREFIX = "Checks: "

ROLE_WORDS = frozenset(
    set(INTERACTIVE_TYPES) | {"StaticText", "Heading", "Image", "Radio", "Dialog"}
)
POSITIVE = frozenset({"visible", "enabled", "disabled", "checked", "unchecked", "selected", "focused", "value", "contains", "matches", "equals"})
ELEMENT_MATCHERS = frozenset(POSITIVE | {"absent"})
COUNT_OPS = frozenset({"==", ">=", "<="})

_LINE = re.compile(r"^\s*check:\s*", re.IGNORECASE)


# ---------- grammar ----------


@dataclass(frozen=True)
class TextPat:
    kind: str  # exact | contains | regex
    text: str
    flags: str = ""

    def render(self) -> str:
        if self.kind == "regex":
            return f"/{self.text}/{self.flags}"
        if self.kind == "contains":
            return f'~"{self.text}"'
        return f'"{self.text}"'

    def matches(self, value: str | None) -> bool:
        value = normalise(value or "")
        if self.kind == "regex":
            try:
                return re.search(self.text, value, re.IGNORECASE if "i" in self.flags else 0) is not None
            except re.error:
                return False
        if self.kind == "contains":
            return normalise(self.text).casefold() in value.casefold()
        return value == normalise(self.text)


@dataclass(frozen=True)
class Check:
    raw: str
    subject: str = ""  # text | role | id | url | title | count | screen
    role: str | None = None
    pattern: TextPat | None = None
    ident: str | None = None
    matcher: str = "visible"
    arg: Any = None  # TextPat for value/contains/matches/equals, int for count ops
    timeout_s: float | None = None
    warning: bool = False
    problems: tuple[str, ...] = ()

    def render(self) -> str:
        if self.problems:
            return self.raw.strip()
        parts: list[str] = []
        if self.subject == "text":
            parts += ["text", self.pattern.render()]  # type: ignore[union-attr]
        elif self.subject == "role":
            parts += [self.role or "", self.pattern.render()]  # type: ignore[union-attr]
        elif self.subject == "id":
            parts.append(f"id={self.ident}")
        elif self.subject == "count":
            parts += ["count", self.role or ""]
            if self.pattern is not None:
                parts.append(self.pattern.render())
        else:
            parts.append(self.subject)
        if self.matcher in COUNT_OPS:
            parts += [self.matcher, str(self.arg)]
        elif self.matcher in ("value", "contains", "matches", "equals"):
            parts += [self.matcher, self.arg.render()]  # type: ignore[union-attr]
        elif self.matcher != "visible" or self.subject in ("screen",):
            parts.append(self.matcher)
        if self.timeout_s is not None:
            parts.append(f"within {self.timeout_s:g}s")
        if self.warning:
            parts.append(WARNING_SUFFIX)
        return " ".join(p for p in parts if p)


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _tokens(text: str) -> list[str]:
    """Split a check line into tokens, keeping quoted strings and /regex/ together."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == '"' or (c == "~" and i + 1 < n and text[i + 1] == '"'):
            start = i
            i += 2 if c == "~" else 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
            i += 1
            out.append(text[start:i])
            continue
        if c == "/":
            start = i
            i += 1
            while i < n and text[i] != "/":
                i += 2 if text[i] == "\\" else 1
            i += 1
            while i < n and text[i].isalpha():
                i += 1
            out.append(text[start:i])
            continue
        if c == "[":
            j = text.find("]", i)
            j = n - 1 if j == -1 else j
            out.append(text[i : j + 1])
            i = j + 1
            continue
        start = i
        while i < n and not text[i].isspace():
            i += 1
        out.append(text[start:i])
    return out


def _textpat(tok: str | None) -> TextPat | None:
    if not tok:
        return None
    if tok.startswith('~"') and tok.endswith('"') and len(tok) >= 3:
        return TextPat("contains", tok[2:-1].replace('\\"', '"'))
    if tok.startswith('"') and tok.endswith('"') and len(tok) >= 2:
        return TextPat("exact", tok[1:-1].replace('\\"', '"'))
    m = re.fullmatch(r"/(.*)/([a-z]*)", tok, re.DOTALL)
    if m:
        try:
            re.compile(m.group(1))
        except re.error:
            return None  # reported as a parse problem, never a silent "not on screen"
        return TextPat("regex", m.group(1), m.group(2))
    return None


def parse_check(line: str) -> Check:
    """Parse one `Check:` line. A line with problems is kept (`problems` set) so the site can
    show the error; it evaluates to `fail` with the problem as `actual`."""
    raw = _LINE.sub("", line or "").strip()
    toks = _tokens(raw)
    problems: list[str] = []
    warning = False
    timeout: float | None = None
    if toks and toks[-1].lower() == WARNING_SUFFIX:
        warning = True
        toks = toks[:-1]
    if len(toks) >= 2 and toks[-2].lower() == "within":
        m = re.fullmatch(r"(\d+(?:\.\d+)?)s", toks[-1].lower())
        if m:
            timeout = min(float(m.group(1)), MAX_TIMEOUT_S)
            toks = toks[:-2]
        else:
            problems.append(f"within needs a number of seconds like 10s, got {toks[-1]!r}")
            toks = toks[:-2]
    if not toks:
        return Check(raw=raw, problems=("empty check",))
    head, rest = toks[0], toks[1:]
    subject, role, pattern, ident = "", None, None, None
    if head == "text":
        subject = "text"
        pattern = _textpat(rest[0] if rest else None)
        if pattern is None:
            problems.append('text needs a quoted string, ~"substring" or /regex/')
        rest = rest[1:]
    elif head.startswith("id="):
        subject, ident = "id", head[3:]
        if not ident:
            problems.append("id= needs an identifier")
    elif head in ("url", "title", "screen"):
        subject = head
    elif head == "count":
        subject = "count"
        role = rest[0] if rest else None
        if role not in ROLE_WORDS:
            problems.append(f"count needs a role word ({', '.join(sorted(ROLE_WORDS))})")
        rest = rest[1:]
        if rest and _textpat(rest[0]) is not None:
            pattern = _textpat(rest[0])
            rest = rest[1:]
    elif head in ROLE_WORDS:
        subject, role = "role", head
        pattern = _textpat(rest[0] if rest else None)
        if pattern is None:
            problems.append(f'{head} needs a label: a quoted string, ~"substring" or /regex/')
        rest = rest[1:]
    else:
        problems.append(f"unknown subject {head!r}: use text, id=, url, title, count, screen or a role ({', '.join(sorted(ROLE_WORDS))})")
    matcher, arg = "visible", None
    if rest:
        word = rest[0]
        if word in COUNT_OPS:
            matcher = word
            try:
                arg = int(rest[1])
            except (IndexError, ValueError):
                problems.append(f"{word} needs a whole number")
            rest = rest[2:]
        elif word in ("value", "contains", "matches", "equals"):
            matcher = word
            arg = _textpat(rest[1] if len(rest) > 1 else None)
            if arg is None or (word == "matches" and arg.kind != "regex"):
                problems.append(f"{word} needs {'a /regex/' if word == 'matches' else 'a quoted string, ~substring or /regex/'}")
            rest = rest[2:]
        else:
            matcher = word
            rest = rest[1:]
    if rest:
        problems.append(f"unexpected text after the matcher: {' '.join(rest)!r}")
    if not problems:
        if subject == "count" and matcher not in COUNT_OPS:
            problems.append("count needs ==, >= or <= and a number")
        elif subject != "count" and matcher in COUNT_OPS:
            problems.append(f"{matcher} only applies to count")
        elif subject == "screen" and matcher not in ("unchanged", "changed"):
            problems.append("screen needs unchanged or changed")
        elif subject in ("url", "title") and matcher not in ("contains", "matches", "equals"):
            problems.append(f"{subject} needs contains, matches or equals")
        elif subject in ("text", "role", "id") and matcher not in ELEMENT_MATCHERS:
            problems.append(f"unknown matcher {matcher!r}: use {', '.join(sorted(ELEMENT_MATCHERS))}")
    return Check(
        raw=raw, subject=subject, role=role, pattern=pattern, ident=ident, matcher=matcher,
        arg=arg, timeout_s=timeout, warning=warning, problems=tuple(problems),
    )


def render(line: str) -> str:
    return parse_check(line).render()


def resolve_placeholders(line: str, data: dict[str, str] | None) -> str:
    if not data or "{{" not in line:
        return line
    return re.sub(r"\{\{\s*([\w.\-]+)\s*\}\}", lambda m: str(data.get(m.group(1), m.group(0))), line)


# ---------- matching ----------


@dataclass
class CheckResult:
    expression: str
    outcome: str  # pass | fail | warning
    actual: str
    matched: list[int] = field(default_factory=list)
    at_step: int | None = None
    ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def passed(self) -> bool:
        return self.outcome == "pass"


def _id_matches(identifier: str, ident: str) -> bool:
    if not identifier:
        return False
    if identifier == ident:
        return True
    return any(identifier.endswith(sep + ident) for sep in ("/", ":", "."))


def candidates(check: Check, elements: list[Element]) -> list[Element]:
    vis = visible_elements(elements)
    if check.subject == "text":
        return _text_candidates(check, elements)
    if check.subject == "role":
        return [e for e in vis if e.type == check.role and check.pattern.matches(e.label)]  # type: ignore[union-attr]
    if check.subject == "id":
        return [e for e in vis if _id_matches(e.identifier, check.ident or "")]
    if check.subject == "count":
        return [e for e in vis if e.type == check.role and (check.pattern is None or check.pattern.matches(e.label))]
    return []


def _text_candidates(check: Check, elements: list[Element]) -> list[Element]:
    """`text` subjects match an element's label first, then its value."""
    vis = visible_elements(elements)
    pat = check.pattern
    assert pat is not None
    by_label = [e for e in vis if pat.matches(e.label)]
    if by_label:
        return by_label
    return [e for e in vis if pat.matches(e.value)]


def nearest_labels(check: Check, elements: list[Element], n: int = NEAREST) -> list[str]:
    target = normalise((check.pattern.text if check.pattern else check.ident) or "").casefold()
    pool = [e for e in visible_elements(elements) if (e.label or e.identifier)]
    if check.subject in ("role", "count") and check.role:
        same = [e for e in pool if e.type == check.role]
        pool = same or pool
    scored = sorted(
        pool,
        key=lambda e: -difflib.SequenceMatcher(None, target, normalise(e.label or e.identifier).casefold()).ratio(),
    )
    return [f'{e.type} "{e.label or e.identifier}" [{e.index}]' for e in scored[:n]]


def _short(e: Element) -> str:
    return f'{e.type} "{e.label}"' + (f' value="{e.value}"' if e.value else "") + f" [{e.index}]"


def match_once(check: Check, screen: Any, *, before_hash: str | None = None) -> tuple[bool | None, str, list[int]]:
    """One evaluation on one capture: `(ok, actual, matched indices)`. `ok` is None when the
    answer could change on a later capture (zero matches for a positive matcher); False is
    final for this capture."""
    elements: list[Element] = list(getattr(screen, "elements", None) or [])
    if check.problems:
        return False, "; ".join(check.problems), []
    if check.subject == "screen":
        now = tree_value_hash(elements)
        changed = before_hash is not None and now != before_hash
        if before_hash is None:
            return False, "no earlier screen to compare with", []
        if check.matcher == "changed":
            # Unchanged may still change on a later capture: keep polling.
            return (True if changed else None), ("the screen changed" if changed else "the screen is unchanged"), []
        return (not changed), ("the screen changed" if changed else "the screen is unchanged"), []
    if check.subject in ("url", "title"):
        page = getattr(screen, "page", None) or {}
        value = (page.get("url") if check.subject == "url" else page.get("title")) if page else None
        if value is None and check.subject == "title":
            value = getattr(screen, "foreground_name", None)
        if value is None:
            return False, f"{check.subject} is not reported by this platform (web only)", []
        if check.subject == "url":
            value = value.split("#", 1)[0]
        pat: TextPat = check.arg
        if check.matcher == "equals":
            ok = normalise(value) == normalise(pat.text) if pat.kind == "exact" else pat.matches(value)
        elif check.matcher == "contains":
            ok = (pat.text in value) if pat.kind == "exact" else pat.matches(value)
        else:
            ok = pat.matches(value)
        return (True if ok else None), f"{check.subject} is {value!r}", []
    if check.subject == "count":
        hits = candidates(check, elements)
        n, want = len(hits), int(check.arg)
        ok = {"==": n == want, ">=": n >= want, "<=": n <= want}[check.matcher]
        return (True if ok else None), f"{n} visible {check.role}" + (f" {check.pattern.render()}" if check.pattern else ""), [e.index for e in hits]
    hits = _text_candidates(check, elements) if check.subject == "text" else candidates(check, elements)
    if check.matcher == "absent":
        if not hits:
            return True, "absent", []
        return None, "still on screen: " + ", ".join(_short(e) for e in hits[:5]), [e.index for e in hits]
    if not hits:
        return None, "", []
    if len(hits) > 1:
        return False, (
            f"ambiguous: {_subject_text(check)} matched {len(hits)} elements "
            + " ".join(f"[{e.index}]" for e in hits)
            + "; add a role, id= or a longer text"
        ), [e.index for e in hits]
    e = hits[0]
    m = check.matcher
    if m == "visible":
        return True, _short(e), [e.index]
    if m in ("enabled", "disabled"):
        ok = e.enabled if m == "enabled" else not e.enabled
        return (True if ok else None), f"{_short(e)} is {'enabled' if e.enabled else 'disabled'}", [e.index]
    if m in ("checked", "unchecked"):
        on = e.value.strip().lower() in ("on", "1", "true", "checked") or "Selected" in (e.traits or [])
        ok = on if m == "checked" else not on
        return (True if ok else None), f"{_short(e)} is {'checked' if on else 'unchecked'}", [e.index]
    if m == "selected":
        on = "Selected" in (e.traits or [])
        return (True if on else None), f"{_short(e)} is {'selected' if on else 'not selected'}", [e.index]
    if m == "focused":
        on = "Focused" in (e.traits or [])
        if not on and not any("Focused" in (x.traits or []) for x in elements) and not _platform_reports_focus(screen):
            return False, "focused is not reported by this platform", [e.index]
        return (True if on else None), f"{_short(e)} is {'focused' if on else 'not focused'}", [e.index]
    pat = check.arg
    if m == "value":
        ok = pat.matches(e.value)
        return (True if ok else None), f'{_short(e)} has value "{e.value}"', [e.index]
    if m in ("contains", "matches", "equals"):
        if m == "contains" and pat.kind == "exact":
            ok = pat.text in normalise(e.label)
        elif m == "equals" and pat.kind == "exact":
            ok = normalise(e.label) == normalise(pat.text)
        else:
            ok = pat.matches(e.label)
        return (True if ok else None), f'{_short(e)} label is "{e.label}"', [e.index]
    return False, f"unknown matcher {m!r}", [e.index]


def _platform_reports_focus(screen: Any) -> bool:
    return bool(getattr(screen, "page", None))


def _subject_text(check: Check) -> str:
    if check.subject == "role":
        return f"{check.role} {check.pattern.render()}"  # type: ignore[union-attr]
    if check.subject == "text":
        return f"text {check.pattern.render()}"  # type: ignore[union-attr]
    if check.subject == "id":
        return f"id={check.ident}"
    return check.subject


def default_timeout(env: dict[str, str] | None = None) -> float:
    env = os.environ if env is None else env
    try:
        return max(0.0, min(float(env.get(ENV_CHECK_TIMEOUT) or DEFAULT_TIMEOUT_S), MAX_TIMEOUT_S))
    except ValueError:
        return DEFAULT_TIMEOUT_S


async def evaluate(
    check: Check | str,
    capture_fn: Callable[[], Awaitable[Any]],
    *,
    timeout_s: float | None = None,
    poll_s: float = POLL_S,
    placeholders: dict[str, str] | None = None,
    before_hash: str | None = None,
    at_step: int | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> CheckResult:
    """Poll `capture_fn` (a fresh capture each time) until the check passes or its timeout
    runs out. Ambiguity fails at once; zero matches waits; `absent` passes at once when nothing
    matches."""
    if isinstance(check, str):
        check = parse_check(resolve_placeholders(check, placeholders))
    expression = check.render()
    budget = check.timeout_s if check.timeout_s is not None else (timeout_s if timeout_s is not None else default_timeout())
    start = clock()
    last_screen = None
    absent_since: float | None = None
    while True:
        last_screen = await capture_fn()
        ok, actual, matched = match_once(check, last_screen, before_hash=before_hash)
        elapsed = clock() - start
        if ok is True and check.matcher == "absent":
            # Gone means gone for ABSENT_HOLD_S: a spinner that has not appeared yet is not absent.
            absent_since = elapsed if absent_since is None else absent_since
            if elapsed - absent_since >= min(ABSENT_HOLD_S, budget):
                return CheckResult(expression, "pass", actual, matched, at_step, int(elapsed * 1000))
            if elapsed >= budget:
                return CheckResult(expression, "pass", actual, matched, at_step, int(elapsed * 1000))
            await sleep(poll_s)
            continue
        absent_since = None
        if ok is True:
            return CheckResult(expression, "pass", actual, matched, at_step, int(elapsed * 1000))
        if ok is False or elapsed >= budget:
            break
        await sleep(poll_s)
    elapsed = clock() - start
    if ok is None:
        if check.matcher == "absent":
            actual = f"{actual} after {elapsed:.1f}s"
        elif not actual:
            near = nearest_labels(check, list(getattr(last_screen, "elements", []) or []))
            actual = f"no {_subject_text(check)} on screen after {elapsed:.1f}s" + (f"; nearest: {', '.join(near)}" if near else "")
        else:
            actual = f"{actual} after {elapsed:.1f}s"
    outcome = "warning" if check.warning else "fail"
    return CheckResult(expression, outcome, actual, matched, at_step, int(elapsed * 1000))


def result_line(r: CheckResult) -> str:
    if r.passed:
        n = len(r.matched)
        where = " ".join(f"[{i}]" for i in r.matched[:5])
        return f"ok: {r.expression}{' ' + where if where else ''} ({n} match{'es' if n != 1 else ''}, {r.ms / 1000:.1f}s)"
    return f"{'warning' if r.outcome == 'warning' else 'fail'}: {r.actual}"


# ---------- verdict composition ----------


