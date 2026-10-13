"""Verdikt device tools over the official AndroidWorld environment.

Every action returns the settled screen it produced (act-then-observe), so one
tool call is one benchmark step: the agent never spends a step only to look.
Element indexes always refer to the last observation the agent was shown, so a
screen that shifts between observation and action cannot redirect a tap.
"""
from __future__ import annotations

import dataclasses
import io
import json
import threading
import time
from pathlib import Path
from typing import Any

from PIL import Image as PILImage, ImageDraw

from android_world.env import adb_utils, json_action

from . import contracts

SHOT_WIDTH = 540  # half of the Pixel 6 width; ~1.1k image tokens per frame


@dataclasses.dataclass
class Episode:
    env: Any
    goal: str
    budget: int
    out_dir: Path
    steps: int = 0
    done: bool = False
    status: str | None = None
    answer: str | None = None
    elements: list = dataclasses.field(default_factory=list)
    log: list = dataclasses.field(default_factory=list)
    # Contracted operation (contracts.py): None when contracts are off for this run.
    contract: list | None = None
    seen: list = dataclasses.field(default_factory=list)  # Verdikt screens observed so far
    refused: set = dataclasses.field(default_factory=set)  # gates already refused once


CONTRACTS = False  # set by the runner (--contracts)


_lock = threading.Lock()
_episode: Episode | None = None


def begin(episode: Episode) -> None:
    global _episode
    _episode = episode
    episode.out_dir.mkdir(parents=True, exist_ok=True)


def current() -> Episode | None:
    return _episode


def end() -> None:
    global _episode
    _episode = None


# ---------- perception ----------

def _keep(e: Any, w: int, h: int) -> bool:
    b = e.bbox_pixels
    if not e.is_visible or b is None:
        return False
    if b.x_min >= b.x_max or b.y_min >= b.y_max or b.x_min >= w or b.x_max <= 0 or b.y_min >= h or b.y_max <= 0:
        return False
    return bool(e.text or e.content_description or e.hint_text or e.is_clickable or e.is_editable
                or e.is_scrollable or e.is_checkable or e.is_long_clickable)


def _describe(i: int, e: Any) -> str:
    cls = (e.class_name or '').rsplit('.', 1)[-1]
    parts = [f'[{i}] {cls}']
    if e.text:
        parts.append(json.dumps(e.text[:300], ensure_ascii=False))
    if e.content_description and e.content_description != e.text:
        parts.append('desc=' + json.dumps(e.content_description[:200], ensure_ascii=False))
    if e.hint_text and e.hint_text != e.text:
        parts.append('hint=' + json.dumps(e.hint_text[:80], ensure_ascii=False))
    flags = [name for name, on in (('click', e.is_clickable), ('long', e.is_long_clickable),
                                    ('edit', e.is_editable), ('scroll', e.is_scrollable),
                                    ('focused', e.is_focused), ('selected', e.is_selected)) if on]
    if e.is_checkable:
        flags.append('checked' if e.is_checked else 'unchecked')
    if e.is_enabled is False:
        flags.append('disabled')
    if e.resource_name:
        flags.append('id=' + e.resource_name.rsplit('/', 1)[-1])
    if flags:
        parts.append('{' + ','.join(flags) + '}')
    b = e.bbox_pixels
    parts.append(f'@({int(b.x_min)},{int(b.y_min)},{int(b.x_max)},{int(b.y_max)})')
    return ' '.join(parts)


def _keyboard_shown(env: Any) -> bool:
    try:
        out = adb_utils.issue_generic_request(['shell', 'dumpsys', 'input_method'], env.controller)
        text = out.generic.output.decode(errors='ignore')
        return 'mInputShown=true' in text
    except Exception:  # noqa: BLE001 - perception extra
        return False


def _shot(pixels: Any, kept: list[tuple[int, Any]]) -> bytes:
    img = PILImage.fromarray(pixels)
    scale = SHOT_WIDTH / img.width
    img = img.resize((SHOT_WIDTH, int(img.height * scale)))
    draw = ImageDraw.Draw(img)
    for i, e in kept:
        if not (e.is_clickable or e.is_editable or e.is_long_clickable or e.is_checkable):
            continue
        b = e.bbox_pixels
        box = [b.x_min * scale, b.y_min * scale, b.x_max * scale, b.y_max * scale]
        draw.rectangle(box, outline=(255, 0, 140), width=1)
        draw.rectangle([box[0], box[1], box[0] + 7 + 6 * len(str(i)), box[1] + 11], fill=(255, 0, 140))
        draw.text((box[0] + 2, box[1]), str(i), fill=(255, 255, 255))
    buf = io.BytesIO()
    img.convert('RGB').save(buf, 'JPEG', quality=70)
    return buf.getvalue()


def observe(ep: Episode, settle: bool = True) -> tuple[str, bytes]:
    state = ep.env.get_state(wait_to_stabilize=settle)
    w, h = ep.env.logical_screen_size
    ep.elements = state.ui_elements
    kept = [(i, e) for i, e in enumerate(state.ui_elements) if _keep(e, w, h)]
    if CONTRACTS:
        ep.seen.append(contracts.to_screen(state.ui_elements, lambda e: _keep(e, w, h)))
    try:
        activity = ep.env.foreground_activity_name or '?'
    except Exception:  # noqa: BLE001
        activity = '?'
    header = (f'activity: {activity} | keyboard: {"shown" if _keyboard_shown(ep.env) else "hidden"} | '
              f'screen {w}x{h} | steps used {ep.steps}/{ep.budget}')
    text = header + '\n' + '\n'.join(_describe(i, e) for i, e in kept)
    jpeg = _shot(state.pixels, kept)
    seq = len(ep.log)
    (ep.out_dir / f'{seq:03d}.jpg').write_bytes(jpeg)
    return text, jpeg


# ---------- actions ----------

class StepError(Exception):
    pass


APP_PACKAGES = {
    'audio recorder': 'com.dimowner.audiorecorder', 'broccoli': 'com.flauschcode.broccoli',
    'recipe': 'com.flauschcode.broccoli', 'camera': 'com.android.camera2',
    'chrome': 'com.android.chrome', 'clock': 'com.google.android.deskclock',
    'contacts': 'com.google.android.contacts', 'files': 'com.google.android.documentsui',
    'markor': 'net.gsantner.markor', 'joplin': 'net.cozic.joplin', 'osmand': 'net.osmand',
    'opentracks': 'de.dennisguse.opentracks', 'open tracks': 'de.dennisguse.opentracks',
    'pro expense': 'com.arduia.expense', 'expense': 'com.arduia.expense',
    'retro music': 'code.name.monkey.retromusic', 'retro': 'code.name.monkey.retromusic',
    'simple calendar': 'com.simplemobiletools.calendar.pro', 'calendar': 'com.simplemobiletools.calendar.pro',
    'simple draw': 'com.simplemobiletools.draw.pro', 'simple gallery': 'com.simplemobiletools.gallery.pro',
    'gallery': 'com.simplemobiletools.gallery.pro', 'simple sms': 'com.simplemobiletools.smsmessenger',
    'sms': 'com.simplemobiletools.smsmessenger', 'tasks': 'org.tasks', 'vlc': 'org.videolan.vlc',
    'settings': 'com.android.settings', 'phone': 'com.google.android.dialer',
    'dialer': 'com.google.android.dialer', 'clipper': 'ca.zgrs.clipper',
}


def _package_for(app: str) -> str | None:
    key = app.lower().strip()
    if key in APP_PACKAGES:
        return APP_PACKAGES[key]
    for name, package in sorted(APP_PACKAGES.items(), key=lambda kv: -len(kv[0])):
        if name in key:
            return package
    return None


def _same_place(a: Any, b: Any) -> bool:
    x, y = a.bbox_pixels, b.bbox_pixels
    return (x.x_min, x.y_min, x.x_max, x.y_max) == (y.x_min, y.y_min, y.x_max, y.y_max)


def _refind(old: Any, fresh: list) -> Any:
    """Locate the element the agent chose on the screen as it is NOW. The agent picked
    [index] from an observation that may be stale (a keyboard opened, a list moved, an
    earlier action in the same turn changed the layout). Match by identity - class,
    resource id, then text/description/hint - and take the nearest such element; fall back
    to the observed element itself."""
    w = lambda e: e.bbox_pixels is not None and e.is_visible
    same = [e for e in fresh if w(e) and e.class_name == old.class_name
            and (e.resource_name or None) == (old.resource_name or None)]
    for e in same:
        if _same_place(e, old) and (e.text, e.content_description) == (old.text, old.content_description):
            return e
    keys = [('text', old.text), ('content_description', old.content_description), ('hint_text', old.hint_text)]
    for attr, value in keys:
        if not value:
            continue
        hits = [e for e in same if getattr(e, attr) == value]
        if hits:
            ox, oy = old.bbox_pixels.center
            return min(hits, key=lambda e: (e.bbox_pixels.center[0] - ox) ** 2 + (e.bbox_pixels.center[1] - oy) ** 2)
    if old.resource_name and len(same) == 1:
        return same[0]
    return old


def _target(ep: Episode, index: int) -> Any:
    if index < 0 or index >= len(ep.elements) or ep.elements[index].bbox_pixels is None:
        raise StepError(f'no element [{index}] on the last screen')
    try:
        fresh = ep.env.get_state(wait_to_stabilize=False).ui_elements
    except Exception:  # noqa: BLE001 - fall back to what the agent saw
        return ep.elements[index]
    return _refind(ep.elements[index], fresh)


def _point(ep: Episode, index: int | None, x: int | None, y: int | None) -> tuple[int, int]:
    if index is not None:
        cx, cy = _target(ep, index).bbox_pixels.center
        return int(cx), int(cy)
    if x is None or y is None:
        raise StepError('give an element index or both x and y')
    return int(x), int(y)


def _shell(ep: Episode, *args: str) -> None:
    adb_utils.issue_generic_request(['shell', *args], ep.env.controller)


def act(name: str, args: dict[str, Any]) -> tuple[str, bytes | None]:
    """Run one step. Returns (text, jpeg) for the screen after the action."""
    with _lock:
        ep = _episode
        if ep is None:
            return 'error: no episode is running', None
        if ep.done:
            return 'error: the episode is already finished; stop now.', None
        if ep.steps >= ep.budget:
            ep.done, ep.status = True, 'budget_exhausted'
            return f'error: step budget ({ep.budget}) exhausted; the episode is over. Stop now.', None
        if ep.steps == ep.budget - 1 and name != 'finish':
            # The finish call is itself a step: an action here could only end the episode
            # undone. Refuse it without spending the step.
            return (f'refused: {ep.steps}/{ep.budget} steps used, so only `finish` can still be '
                    'called. If the goal is achieved (or is as done as it can be), call finish now.'), None
        gate = _gate(ep, name, args) if CONTRACTS else None
        if gate:
            ep.log.append({'step': ep.steps, 'tool': name, 'args': args, 'refused': gate})
            _flush(ep)
            return gate, None
        expect = args.pop('expect', None)
        ep.steps += 1
        started = time.time()
        record = {'step': ep.steps, 'tool': name, 'args': args}
        try:
            result = _run(ep, name, args)
        except StepError as exc:
            result = f'error: {exc}'
        except Exception as exc:  # noqa: BLE001 - a device error is the agent's to see
            result = f'error: {type(exc).__name__}: {exc}'
        record['result'] = result
        if ep.done:
            record['seconds'] = round(time.time() - started, 2)
            ep.log.append(record)
            _flush(ep)
            return result, None
        time.sleep(0.3)
        text, jpeg = observe(ep)
        if CONTRACTS and expect:
            checks, bad = contracts.parse(expect)
            verdict = contracts.render(contracts.evaluate(checks, ep.seen[-1]), 'expect') if checks else ''
            verdict += ''.join(f'\n  unparsable expect {b}' for b in bad)
            record['expect'] = verdict
            result = f'{result}\n{verdict}'
        record['seconds'] = round(time.time() - started, 2)
        ep.log.append(record)
        _flush(ep)
        left = ep.budget - ep.steps
        warn = f'\nWARNING: only {left} step(s) left including finish.' if left <= 2 else ''
        return f'{result}{warn}\n\n{text}', jpeg


def _gate(ep: Episode, name: str, args: dict[str, Any]) -> str | None:
    """Refuse, once and without spending the step, a finish whose goal contract fails on the
    current screen or an answer whose cited evidence held on no screen seen."""
    if ep.contract is None and name not in ('open_app', 'finish', 'answer'):
        return ('refused (no step used): state the goal contract first. Call `contract` with checks for every '
                'value the goal requires, as they will appear on the screen you end on (or contract([]) if no '
                'screen can show the result), then act.')
    if name == 'answer' and not args.get('evidence') and 'answer-evidence' not in ep.refused:
        ep.refused.add('answer-evidence')
        return ('refused (no step used): give `evidence` with the answer: checks for the on-screen text each '
                'fact rests on (e.g. ["text ~\\"Running\\" visible"] seen on each counted item). If an attribute '
                'is shown only as an icon or colour, open the item to read it as text first.')
    if name == 'finish' and (args.get('status') or 'complete') == 'complete' and ep.contract and 'finish' not in ep.refused:
        observe(ep)
        results = contracts.evaluate(ep.contract, ep.seen[-1])
        if not all(ok for _, ok, _ in results):
            ep.refused.add('finish')
            return (contracts.render(results, 'goal contract') + '\nrefused (no step used): the goal contract '
                    'does not hold on the current screen. Fix what is missing, or navigate to where it can be '
                    'seen, or - if the contract itself was wrong - call finish again to finish anyway.')
    if name == 'finish' and ep.answer is None and ep.refused & {'answer', 'answer-evidence'} \
            and 'finish-noanswer' not in ep.refused:
        ep.refused.add('finish-noanswer')
        return ('refused (no step used): your `answer` was refused, so no answer is recorded yet. '
                'Call answer again (with evidence that held on a screen you saw), then finish.')
    if name == 'answer' and args.get('evidence') and 'answer' not in ep.refused:
        checks, bad = contracts.parse(args['evidence'])
        results = contracts.held_on_any(checks, ep.seen)
        # Unparsable evidence is reported, never a reason to withhold the answer.
        if results and not all(ok for _, ok, _ in results):
            ep.refused.add('answer')
            return (contracts.render(results, 'answer evidence') + ''.join(f'\n  unparsable {b}' for b in bad)
                    + '\nrefused (no step used): part of the evidence held on no screen you have seen. Check '
                    'the facts behind your answer, or call answer again to answer anyway.')
    return None


def set_contract(checks: list[str]) -> str:
    """Record the goal contract (free: no step). Returns how it stands on the current screen."""
    with _lock:
        ep = _episode
        if ep is None:
            return 'error: no episode is running'
        parsed, bad = contracts.parse(checks or [])
        if bad:
            return 'error: unparsable checks, nothing recorded:\n  ' + '\n  '.join(bad)
        ep.contract = parsed
        ep.log.append({'step': ep.steps, 'tool': 'contract', 'args': {'checks': checks}})
        _flush(ep)
        if not parsed:
            return 'recorded an empty contract: finish will not be checked.'
        if not ep.seen:
            observe(ep)
        return contracts.render(contracts.evaluate(parsed, ep.seen[-1]), 'goal contract (now)') + \
            '\nrecorded. finish is checked against it.'


def look() -> tuple[str, bytes | None]:
    with _lock:
        ep = _episode
        if ep is None:
            return 'error: no episode is running', None
        text, jpeg = observe(ep)
        ep.log.append({'step': ep.steps, 'tool': 'screen'})
        _flush(ep)
        return text, jpeg


def _flush(ep: Episode) -> None:
    (ep.out_dir / 'steps.json').write_text(json.dumps(ep.log, indent=1, default=str))


def _run(ep: Episode, name: str, a: dict[str, Any]) -> str:
    env = ep.env
    c = env.controller
    if name == 'tap':
        x, y = _point(ep, a.get('index'), a.get('x'), a.get('y'))
        adb_utils.tap_screen(x, y, c)
        return f'tapped ({x},{y})'
    if name == 'double_tap':
        x, y = _point(ep, a.get('index'), a.get('x'), a.get('y'))
        adb_utils.double_tap(x, y, c)
        return f'double-tapped ({x},{y})'
    if name == 'long_press':
        x, y = _point(ep, a.get('index'), a.get('x'), a.get('y'))
        ms = int(a.get('duration_ms') or 1000)
        _shell(ep, 'input', 'swipe', str(x), str(y), str(x), str(y), str(ms))
        return f'long-pressed ({x},{y}) for {ms}ms'
    if name == 'type':
        target = None
        if a.get('index') is not None:
            target = _target(ep, a['index'])
        if target is not None or a.get('x') is not None:
            # Focus-verified entry: a tap meant for a field is sometimes swallowed (an
            # autocomplete popup from the previous field, a keyboard transition). Tap, check
            # the field really holds focus, and tap again if not, before typing anything.
            for attempt in range(3):
                if target is not None:
                    x, y = (int(v) for v in target.bbox_pixels.center)
                else:
                    x, y = int(a['x']), int(a['y'])
                adb_utils.tap_screen(x, y, c)
                time.sleep(0.7)
                if target is None:
                    break
                fresh = env.get_state(wait_to_stabilize=False).ui_elements
                now = _refind(target, fresh)
                if now.is_focused or not now.is_editable:
                    break
                focused = [e for e in fresh if e.is_focused and e.is_editable]
                if focused and focused[0].resource_name == target.resource_name and target.resource_name:
                    break
                target = now
        if a.get('clear', True):
            _shell(ep, 'input', 'keycombination', '113', '29')
            time.sleep(0.2)
            _shell(ep, 'input', 'keyevent', '67')
            time.sleep(0.3)
        text = a.get('text') or ''
        if text:
            adb_utils.type_text(text, c, timeout_sec=30)
        if a.get('enter'):
            adb_utils.press_enter_button(c)
        note = ''
        if target is not None and text and '\n' not in text:
            time.sleep(0.3)
            field = _refind(target, env.get_state(wait_to_stabilize=False).ui_elements)
            shown = field.text or ''
            if text not in shown:
                focused = [e for e in env.get_state(wait_to_stabilize=False).ui_elements if e.is_focused and e.is_editable]
                where = f' The focused field now shows {json.dumps((focused[0].text or "")[:80])}.' if focused else ''
                note = f' WARNING: the target field shows {json.dumps(shown[:80])}, not the typed text; check where it went.{where}'
        return f'typed {json.dumps(text)}' + (' and pressed enter' if a.get('enter') else '') + note
    if name == 'press':
        key = (a.get('key') or '').lower()
        codes = {'back': '4', 'home': '3', 'enter': '66', 'delete': '67', 'backspace': '67',
                 'tab': '61', 'space': '62', 'recents': '187', 'escape': '111', 'search': '84',
                 'forward_delete': '112', 'move_end': '123', 'move_home': '122',
                 'dpad_up': '19', 'dpad_down': '20', 'dpad_left': '21', 'dpad_right': '22',
                 'volume_up': '24', 'volume_down': '25', 'select_all': 'ctrl+a', 'copy': 'ctrl+c',
                 'paste': 'ctrl+v', 'cut': 'ctrl+x', 'undo': 'ctrl+z'}
        if key not in codes:
            raise StepError(f'unknown key {key!r}; use one of {sorted(codes)}')
        repeat = max(1, min(int(a.get('repeat') or 1), 60))
        code = codes[key]
        for _ in range(repeat):
            if code.startswith('ctrl+'):
                letter = {'a': '29', 'c': '31', 'v': '50', 'x': '52', 'z': '54'}[code[-1]]
                _shell(ep, 'input', 'keycombination', '113', letter)
            else:
                _shell(ep, 'input', 'keyevent', code)
        return f'pressed {key}' + (f' x{repeat}' if repeat > 1 else '')
    if name == 'scroll':
        w, h = env.logical_screen_size
        direction = a.get('direction')
        if a.get('index') is not None:
            b = _target(ep, a['index']).bbox_pixels
            x0, y0, x1, y1 = max(b.x_min, 0), max(b.y_min, 0), min(b.x_max, w), min(b.y_max, h)
        else:
            x0, y0, x1, y1 = 0, int(h * 0.15), w, int(h * 0.85)
        frac = {'small': 0.25, 'half': 0.5, 'page': 0.8}.get(a.get('amount') or 'half', 0.5)
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        dy, dx = int((y1 - y0) * frac / 2), int((x1 - x0) * frac / 2)
        moves = {'down': (cx, cy + dy, cx, cy - dy), 'up': (cx, cy - dy, cx, cy + dy),
                 'right': (cx + dx, cy, cx - dx, cy), 'left': (cx - dx, cy, cx + dx, cy)}
        if direction not in moves:
            raise StepError('direction must be up, down, left or right')
        sx, sy, ex, ey = moves[direction]
        _shell(ep, 'input', 'swipe', str(sx), str(sy), str(ex), str(ey), '600')
        return f'scrolled {direction} (revealing content further {direction})'
    if name == 'swipe':
        ms = int(a.get('duration_ms') or 400)
        _shell(ep, 'input', 'swipe', str(int(a['x1'])), str(int(a['y1'])), str(int(a['x2'])),
               str(int(a['y2'])), str(ms))
        return f'swiped ({a["x1"]},{a["y1"]})->({a["x2"]},{a["y2"]}) in {ms}ms'
    if name == 'drag':
        ms = int(a.get('duration_ms') or 2000)
        _shell(ep, 'input', 'draganddrop', str(int(a['x1'])), str(int(a['y1'])), str(int(a['x2'])),
               str(int(a['y2'])), str(ms))
        return 'dragged'
    if name == 'open_app':
        app = a.get('name') or ''
        try:
            activity = adb_utils.launch_app(app, c)
        except Exception:  # noqa: BLE001 - e.g. `am start -W` timing out on a cold start
            activity = None
        if not activity:
            package = _package_for(app)
            if not package:
                raise StepError(f'no app matches {app!r}; known: {", ".join(sorted(APP_PACKAGES))}')
            _shell(ep, 'monkey', '-p', package, '-c', 'android.intent.category.LAUNCHER', '1')
        time.sleep(1.5)
        return f'opened {app}'
    if name == 'wait':
        time.sleep(max(1, min(int(a.get('seconds') or 2), 10)))
        return 'waited'
    if name == 'answer':
        env.execute_action(json_action.JSONAction(action_type='answer', text=a.get('text') or ''))
        ep.answer = a.get('text')
        return f'answer recorded: {json.dumps(ep.answer)}'
    if name == 'finish':
        ep.done = True
        ep.status = a.get('status') or 'complete'
        return 'episode finished. Stop now and do not call any more tools.'
    raise StepError(f'unknown tool {name}')
