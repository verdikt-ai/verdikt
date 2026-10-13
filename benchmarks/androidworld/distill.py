"""Distill app playbooks ("skills") from practice runs.

    python -m benchmarks.androidworld.distill OUT_DIR RUN_DIR [RUN_DIR ...]

Practice runs must use a suite seed other than the evaluation seed (30), so a playbook
can only carry how an app works - where things are, what each control does, which paths
are short, which traps cost steps - never the answer to an evaluation instance. Each
practice trajectory is rendered as goal, outcome, and the actions with the element each
one targeted; one model call per app turns them into a short playbook.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

# playbook file -> (task-name prefixes that teach it, goal keywords that select it)
APPS = {
    'audio_recorder.md': (('AudioRecorder',), ['audio recorder']),
    'browser_tasks.md': (('Browser',), ['task.html']),
    'camera.md': (('Camera',), ['take one photo', 'take one video']),
    'clock.md': (('Clock',), ['stopwatch', 'timer']),
    'contacts.md': (('Contacts', 'OpenAppTaskEval'), ['contact']),
    'pro_expense.md': (('Expense',), ['pro expense']),
    'files.md': (('Files',), ['android filesystem']),
    'markor.md': (('Markor', 'ExpenseAddMultipleFromMarkor', 'RecipeAddMultipleRecipesFromMarkor'), ['markor']),
    'joplin.md': (('Notes',), ['joplin']),
    'osmand.md': (('OsmAnd',), ['osmand']),
    'broccoli.md': (('Recipe',), ['broccoli']),
    'retro_music.md': (('Retro',), ['retro music']),
    'simple_gallery.md': (('SaveCopyOfReceipt', 'ExpenseAddMultipleFromGallery', 'RecipeAddMultipleRecipesFromImage',
                           'MarkorTranscribeReceipt'), ['simple gallery', '.jpg', '.png']),
    'simple_calendar.md': (('SimpleCalendar',), ['simple calendar']),
    'simple_draw.md': (('SimpleDraw',), ['simple draw']),
    'simple_sms.md': (('SimpleSms', 'MarkorCreateNoteAndSms'), ['simple sms']),
    'opentracks.md': (('SportsTracker',), ['opentracks']),
    'settings.md': (('System', 'TurnOff', 'TurnOn'), ['bluetooth', 'brightness', 'wifi', 'clipboard']),
    'tasks.md': (('Tasks',), ['tasks app']),
    'vlc.md': (('Vlc', 'MarkorTranscribeVideo'), ['vlc']),
}

PROMPT = """You are writing an operator playbook for the Android app(s) below, used by an agent that
drives a Pixel 6 (Android 13, 1080x2400) through tools: tap/long_press/type/press/scroll/swipe/
drag/open_app/wait/answer/finish, targeting elements from an accessibility element list.

Below are practice episodes in this app: the goal, whether it succeeded (official grader), and
each action with the element it targeted. Practice goals use different names and values from
the real tasks, so DO NOT include any specific names, titles, numbers or answers from them.

Write a concise playbook (max ~350 words, markdown bullets, heading "## <App name>") with:
- How to reach each function (exact element labels / content descriptions / ids, menu paths).
- The shortest reliable action sequence for each kind of goal seen, with step counts.
- Traps that cost steps or caused failures, and how to avoid them; what to verify before finish.
- Answer-format conventions for question goals, if any.
Only state what the episodes show; mark anything uncertain as such.

EPISODES:
"""


def render(task_dir: Path) -> str | None:
    try:
        r = json.loads((task_dir / 'result.json').read_text())
    except (OSError, ValueError):
        return None
    if r.get('outcome') != 'graded':
        return None
    lines = [f"GOAL: {r['goal']}", f"OUTCOME: {'SUCCESS' if r.get('success') == 1.0 else 'FAIL'} "
             f"(steps {r.get('steps')}/{r.get('budget')}, finish={r.get('status')})"]
    screen = ''
    for raw in (task_dir / 'agent.jsonl').read_text().splitlines():
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if e.get('type') == 'assistant':
            for b in e['message']['content']:
                if b.get('type') != 'tool_use':
                    continue
                tool = b['name'].split('__')[-1]
                args = dict(b['input'])
                target = ''
                if 'index' in args:
                    m = re.search(rf'^\[{args["index"]}\] (.*)$', screen, re.M)
                    target = f'  <{m.group(1)[:140]}>' if m else ''
                if tool != 'screen':
                    lines.append(f'- {tool} {json.dumps(args, ensure_ascii=False)[:160]}{target}')
        elif e.get('type') == 'user' and isinstance(e['message'].get('content'), list):
            for b in e['message']['content']:
                if b.get('type') == 'tool_result':
                    c = b.get('content')
                    text = c if isinstance(c, str) else '\n'.join(x.get('text', '') for x in c if isinstance(x, dict))
                    if 'activity:' in text:
                        screen = text
    if r.get('success') != 1.0:
        last = ''
        for raw in (task_dir / 'agent.jsonl').read_text().splitlines():
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            if e.get('type') == 'assistant':
                for b in e['message']['content']:
                    if b.get('type') == 'text':
                        last = b['text']
        if last:
            lines.append('AGENT\'S OWN ACCOUNT: ' + last[:900].replace('\n', ' '))
    return '\n'.join(lines)


def main() -> None:
    out = Path(sys.argv[1])
    runs = [Path(p) for p in sys.argv[2:]]
    out.mkdir(parents=True, exist_ok=True)
    from concurrent.futures import ThreadPoolExecutor

    def one(item):
        name, (prefixes, keys) = item
        episodes = []
        for run in runs:
            for d in sorted((run / 'tasks').iterdir()):
                if d.name.startswith(prefixes):
                    text = render(d)
                    if text:
                        episodes.append(text)
        if not episodes:
            return None
        prompt = PROMPT + '\n\n'.join(episodes)[:60000]
        res = subprocess.run(['claude', '-p', prompt, '--model', 'opus', '--tools', '', '--setting-sources', '',
                              '--strict-mcp-config', '--output-format', 'json'],
                             capture_output=True, text=True, stdin=subprocess.DEVNULL, cwd=out)
        try:
            body = json.loads(res.stdout)['result']
        except (ValueError, KeyError):
            print('failed', name, res.stderr[-300:])
            return None
        (out / name).write_text(body.strip() + '\n')
        print('wrote', name, len(episodes), 'episodes', flush=True)
        return name, keys

    with ThreadPoolExecutor(6) as pool:
        index = dict(r for r in pool.map(one, APPS.items()) if r)
    (out / 'index.json').write_text(json.dumps(index, indent=2))


if __name__ == '__main__':
    main()
