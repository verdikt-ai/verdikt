"""One operated session: act-then-observe, stable targeting, an obligation ledger, and a finish
that a checker gates.

- Every action returns the screen it produced; the agent never spends an action only to look.
- `[index]` refers to the screen the agent last saw; before acting, the element is re-found on
  the live screen (`proofop.targeting.refind`), so a layout shift cannot redirect a tap.
- Typing into a field taps it until the field reports focus (where the platform reports focus).
- The agent records obligations (DO / KNOW / IF) and closes each with the value it claims and the
  step of a recorded screen that shows it. `finish` asks the checker (`proofop.ledger`) first:
  open, unproven or unchallenged-absent obligations refuse it (at most `rounds` times), the
  action budget never resets, and the final answer is completed from proven facts only.
"""
from __future__ import annotations

import time
from pathlib import Path

from proofop import ledger
from proofop.drivers.base import Driver, Shot
from proofop.targeting import refind
from proofop.tree import Element, parse_tree, visible_elements

TYPES = ('DO', 'KNOW', 'IF')
SETTLE_S = 0.8
FOCUS_TAPS = 3


class Session:
    def __init__(self, driver: Driver, run_dir: Path | str, budget: int = 50, rounds: int = 2):
        from proofop.store import Store
        self.driver, self.store = driver, Store(Path(run_dir))
        self.budget, self.max_rounds = budget, rounds
        self.actions = self.rounds = 0
        self.absence_seen: set[str] = set()
        self.shown: dict[int, Element] = {}
        self.shot: Shot | None = None
        self.done = False

    # ---------- perception ----------

    def look(self) -> tuple[str, bytes]:
        shot = self.driver.capture()
        step = self.store.screen(shot)
        elements = parse_tree(shot.nodes)
        self.shot, self.shown = shot, {e.index: e for e in elements}
        lines = [e.compact_line() for e in visible_elements(elements)]
        head = (f'step {step} · {self.driver.platform} · {shot.foreground or "?"} · {shot.width}x{shot.height} · '
                f'actions used {self.actions}/{self.budget}')
        return head + '\n' + '\n'.join(lines), shot.png

    # ---------- actions ----------

    def _act(self, name: str, args: dict, fn) -> tuple[str, bytes | None]:
        if self.done:
            return 'error: the session is finished.', None
        if self.actions >= self.budget:
            return f'refused: the action budget ({self.budget}) is used up. Call finish.', None
        self.actions += 1
        try:
            result = fn() or 'done'
        except Exception as exc:  # noqa: BLE001 - the agent sees what failed
            result = f'error: {type(exc).__name__}: {exc}'
        self.store.action(name, args, result)
        time.sleep(SETTLE_S)
        text, png = self.look()
        return f'{result}\n\n{text}', png

    def _point(self, index: int | None, x: int | None, y: int | None) -> tuple[int, int, Element | None]:
        if index is None:
            if x is None or y is None:
                raise ValueError('give an element index from the last screen, or x and y')
            return int(x), int(y), None
        seen = self.shown.get(index)
        if seen is None:
            raise ValueError(f'no element [{index}] on the last screen')
        live = parse_tree(self.driver.capture().nodes)
        now = refind(seen, live) or seen
        cx, cy = now.center
        return cx, cy, now

    def tap(self, index: int | None = None, x: int | None = None, y: int | None = None):
        def go():
            px, py, el = self._point(index, x, y)
            self.driver.tap(px, py)
            return f'tapped ({px},{py})' + (f' {el.type} "{el.label}"' if el is not None else '')
        return self._act('tap', {'index': index, 'x': x, 'y': y}, go)

    def type_text(self, text: str, index: int | None = None):
        def go():
            if index is not None:
                px, py, el = self._point(index, None, None)
                for _ in range(FOCUS_TAPS):
                    self.driver.tap(px, py)
                    time.sleep(0.5)
                    live = parse_tree(self.driver.capture().nodes)
                    now = refind(el, live) if el is not None else None
                    reports_focus = any('Focused' in e.traits for e in live)
                    if now is None or not reports_focus or 'Focused' in now.traits:
                        break
                    px, py = now.center
            self.driver.type_text(text)
            return f'typed {text!r}'
        return self._act('type_text', {'text': text, 'index': index}, go)

    def swipe(self, direction: str, distance: float = 0.5):
        def go():
            w = (self.shot.width if self.shot else 0) or 1080
            h = (self.shot.height if self.shot else 0) or 2400
            cx, cy, dx, dy = w // 2, h // 2, int(w * distance / 2), int(h * distance / 2)
            ends = {'up': (cx, cy + dy, cx, cy - dy), 'down': (cx, cy - dy, cx, cy + dy),
                    'left': (cx + dx, cy, cx - dx, cy), 'right': (cx - dx, cy, cx + dx, cy)}
            if direction not in ends:
                raise ValueError('direction is one of up, down, left, right (the finger moves that way)')
            self.driver.swipe(*ends[direction])
            return f'swiped {direction}'
        return self._act('swipe', {'direction': direction, 'distance': distance}, go)

    def press(self, key: str):
        return self._act('press', {'key': key}, lambda: (self.driver.press(key), f'pressed {key}')[1])

    def launch(self, app: str):
        return self._act('launch', {'app': app}, lambda: (self.driver.launch(app), time.sleep(1.5), f'launched {app}')[2])

    def wait(self, seconds: float = 2):
        return self._act('wait', {'seconds': seconds}, lambda: (time.sleep(max(0.5, min(seconds, 10))), 'waited')[1])

    # ---------- the obligation ledger ----------

    def _find(self, text: str) -> str | None:
        recorded = [e['criterion'] for e in self.store.events]
        for c in reversed(recorded):
            if c == text or c.split(':', 1)[-1].strip() == text.strip():
                return c
        return None

    def record(self, kind: str, text: str) -> str:
        kind = kind.upper()
        if kind not in TYPES:
            return f'error: kind is one of {", ".join(TYPES)}'
        crit = f'{kind}: {text.strip()}'
        self.store.ledger({'criterion': crit, 'status': 'running'})
        return f'recorded {crit} (free; no action used)'

    def close(self, text: str, value: str | None = None, step: int | None = None, absent: bool = False,
              explanation: str | None = None) -> str:
        crit = self._find(text)
        if crit is None:
            return f'error: no obligation {text!r} was recorded; record it first'
        if absent:
            self.store.ledger({'criterion': crit, 'status': 'fail', 'explanation': explanation or 'not found'})
            return f'closed {crit} as absent; the checker will challenge it once'
        step = self.store.step if step is None else int(step)
        if not value:
            return 'error: give `value`, the exact text the screen shows'
        if not self.store.has_screen(step):
            return f'error: no recorded screen at step {step}'
        self.store.ledger({'criterion': crit, 'status': 'pass', 'actual': value, 'evidence_frame': step})
        verdict = next(o for o in ledger.verify_run(self.store.path)['obligations'] if o['obligation'] == crit)
        note = '' if verdict['verdict'] == 'proven' else f" (the checker does not accept it yet: {verdict['reason']})"
        return f'closed {crit} with {value!r} at step {step}{note}'

    def finish(self, answer: str = '', status: str = 'complete') -> str:
        if self.done:
            return 'error: the session is already finished.'
        result = ledger.verify_run(self.store.path)
        msg = ledger.challenge(result, self.absence_seen) if status == 'complete' else None
        if msg and self.rounds < self.max_rounds:
            self.rounds += 1
            self.absence_seen |= {o['obligation'] for o in result['obligations'] if o['verdict'] == 'absent'}
            return 'refused: ' + msg
        cert = ledger.certificate(result, self.rounds)
        completed = ledger.answer_with_facts(answer or None, result)
        self.store.write('certificate.json', {**cert, 'status': status, 'answer': completed, 'actions': self.actions,
                                              'budget': self.budget})
        self.done = True
        return (f"finished ({status}). Certificate: {cert['proven']} proven, {cert['unproven']} unproven, "
                f"{cert['absent']} absent, {cert['open']} open of {cert['obligations']} obligations. Answer: {completed or '(none)'}")
