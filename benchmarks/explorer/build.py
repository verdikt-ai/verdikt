"""Build the local run explorer: every benchmark run, every task, and a step-by-step replay.

    python3 -m benchmarks.explorer.build [BENCH_ROOT] [--no-gifs]

BENCH_ROOT (default $VERDIKT_BENCH (default ./bench-results)) gets
`explorer/index.html` + `explorer/data.js` + `explorer/gifs/`. Frames are referenced in place
(relative paths), never copied; open explorer/index.html in a browser.
"""
from __future__ import annotations

import json
import time
import re
import os
import sys
from pathlib import Path

from PIL import Image

from benchmarks.androidworld.distill import APPS

HERE = Path(__file__).resolve().parent
ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
GIFS = '--no-gifs' not in sys.argv  # GIF encoding is heavy: skip it while benchmarks run
ROOT = Path(ARGS[0]) if ARGS else Path(os.environ.get('VERDIKT_BENCH', 'bench-results'))
OUT = ROOT / 'explorer'

# (folder, label, config note). Only scored, valid attempts; invalid ones stay out of the explorer.
ANDROID_RUNS = [
    ('androidworld-full/run5-opus-skills', 'Run 5 · playbooks', 'Config B: operator + playbooks from seed 7 · seed 30 (best: 114/116)'),
    ('androidworld-full/run9-contracts-seed7', 'Contracts · seed 7', 'Config C: enforced contracts, no playbooks · suite seed 7'),
    ('androidworld-full/run10-contracts-seed8', 'Contracts · seed 8', 'Config C: enforced contracts, no playbooks · suite seed 8'),
    ('androidworld-full/run8-opus-contracts', 'Run 8 · contracts', 'Config C: operator + enforced contracts, no playbooks · seed 30'),
    ('androidworld-full/run6-opus-skills78', 'Run 6 · playbooks 7+8', 'Config B: operator + playbooks from seeds 7 and 8 · seed 30'),
    ('androidworld-full/run4-opus-skills', 'Run 4 · playbooks', 'Config B v3 · seed 30'),
    ('androidworld-full/run3-opus', 'Run 3 · zero-shot', 'Config A: operator, no app knowledge · seed 30'),
    ('androidworld-full/practice-seed8', 'Practice · seed 8', 'Config A on suite seed 8 (practice, not scored)'),
    ('androidworld-full/practice-seed7', 'Practice · seed 7', 'Config A on suite seed 7 (practice, not scored)'),
    ('androidworld-full/run2-opus', 'Run 2 · v1', 'Config A v1, before environment completion · seed 30'),
]
IOS_RUNS = [
    ('iosworld-runs/run4-pco-v2-repeat', 'PCO v2 · repeat', 'Proof-carrying operation v2, repeat run (variance)'),
    ('iosworld-runs/run5-v2-ledger-only', 'Ledger only', 'Ablation: v2 obligation ledger, checker never sends the agent back'),
    ('iosworld-runs/run3-pco-v2', 'PCO v2', 'Proof-carrying operation v2: SAY obligations for derived results, clause-by-clause compile, cost-aware proving'),
    ('iosworld-runs/run2-pco', 'PCO v1', 'Proof-carrying operation: obligation ledger, evidence-checked claims, checker rounds'),
    ('iosworld-runs/run1-opus', 'Baseline', 'Verdikt product iOS tools, 50-action budget, no ledger'),
]
PREFIX_APP = sorted(((p, name[:-3].replace('_', ' ').title()) for name, (prefixes, _) in APPS.items() for p in prefixes),
                    key=lambda kv: -len(kv[0]))


def rel(p: Path) -> str:
    return str(Path('..') / p.relative_to(ROOT))


def make_gif(frames: list[Path], dest: Path) -> str | None:
    if not frames or not (GIFS or dest.exists()):
        return None
    if not dest.exists():
        imgs = []
        for f in frames:
            try:
                im = Image.open(f).convert('RGB')
            except OSError:
                continue
            w = 270
            imgs.append(im.resize((w, int(im.height * w / im.width))))
        if not imgs:
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        imgs[0].save(dest, save_all=True, append_images=imgs[1:], duration=800, loop=0)
    return str(dest.relative_to(OUT))


def android_app(task: str) -> str:
    return next((app for p, app in PREFIX_APP if task.startswith(p)), 'Other')


def android_run(folder: str, label: str, note: str) -> dict | None:
    run = ROOT / folder
    if not (run / 'tasks').exists():
        return None
    tasks = []
    for d in sorted((run / 'tasks').iterdir()):
        try:
            r = json.loads((d / 'result.json').read_text())
        except (OSError, ValueError):
            continue
        if r.get('outcome') != 'graded':
            continue
        try:
            log = json.loads((d / 'frames' / 'steps.json').read_text())
        except (OSError, ValueError):
            log = []
        steps, frames, last = [], [], None
        for k, e in enumerate(log):
            f = d / 'frames' / f'{k:03d}.jpg'
            if f.exists():
                last = f
                frames.append(f)
            if e.get('tool') == 'screen':
                continue
            steps.append({'n': e.get('step'), 'tool': e.get('tool'), 'args': e.get('args'),
                          'result': e.get('refused') or e.get('result'), 'refused': bool(e.get('refused')),
                          'expect': e.get('expect'), 'frame': rel(last) if last else None})
        final = d / 'final.png'
        thumb = rel(frames[-1]) if frames else (rel(final) if final.exists() else None)
        tasks.append({
            'id': d.name, 'app': android_app(d.name), 'goal': r.get('goal'),
            'success': r.get('success') == 1.0, 'score': float(r.get('success') or 0),
            'steps': r.get('steps'), 'budget': r.get('budget'), 'seconds': r.get('seconds'),
            'cost': r.get('total_cost_usd'), 'answer': r.get('answer'), 'thumb': thumb,
            'start': rel(frames[0]) if frames else None,
            'gif': make_gif(frames, OUT / 'gifs' / Path(folder).name / f'{d.name}.gif'),
            'data': rel(d / 'result.json'), 'steplog': rel(d / 'frames' / 'steps.json') if log else None,
            'summary': agent_summary(d / 'agent.jsonl'), 'step_list': steps,
        })
    return summarize({'id': Path(folder).name, 'label': label, 'note': note, 'platform': 'Android',
                      'benchmark': 'AndroidWorld', 'tasks': tasks})


def agent_summary(path: Path) -> str | None:
    try:
        for line in reversed(path.read_text().splitlines()):
            e = json.loads(line)
            if e.get('type') == 'result':
                return (e.get('result') or '')[:2500]
    except (OSError, ValueError):
        pass
    return None


def ios_run(folder: str, label: str, note: str) -> dict | None:
    run = ROOT / folder
    if not run.exists():
        return None
    tasks = []
    for d in sorted(p for p in run.iterdir() if (p / 'task.json').exists()):
        t = json.loads((d / 'task.json').read_text())
        try:
            traj = json.loads((d / 'trajectory.json').read_text())
        except (OSError, ValueError):
            traj = []
        ev = t.get('evaluation') or {}
        steps, frames = [], []
        for s in traj:
            post = s.get('post_action_screenshot') or s.get('screenshot')
            if s.get('screenshot') and not frames:
                frames.append(Path(s['screenshot']))
            if post:
                frames.append(Path(post))
            a = s.get('action') or {}
            if a.get('type') == 'find':
                continue
            steps.append({'n': s.get('step'), 'tool': a.get('type'), 'args': _ios_args(a.get('args') or {}),
                          'result': a.get('result'), 'refused': False,
                          'frame': rel(Path(post)) if post else None})
        frames = [f for f in frames if f.exists()]
        score = ev.get('score')
        tasks.append({
            'id': t['task'], 'app': ', '.join(t.get('apps') or []) or 'Other', 'category': t.get('category'),
            'goal': t.get('goal'), 'success': score == 1,  # iOSWorld's pass definition: every rubric criterion satisfied
            'score': float(score) if score is not None else None, 'judged': bool(ev),
            'steps': len(steps), 'budget': 50, 'seconds': t.get('seconds'), 'cost': t.get('cost_usd'),
            'answer': t.get('agent_answer'), 'thumb': rel(frames[-1]) if frames else None,
            'start': rel(frames[0]) if frames else None,
            'gif': make_gif(frames, OUT / 'gifs' / Path(folder).name / f"{t['task']}.gif"),
            'data': rel(d / 'task.json'), 'steplog': rel(d / 'trajectory.json'),
            'summary': (t.get('final_text') or '')[:2500], 'rubric': ev.get('rubric_results'),
            'judge': ev.get('reasoning'), 'step_list': steps,
            'ledger': _ledger(d),
        })
    return summarize({'id': Path(folder).name, 'label': label, 'note': note, 'platform': 'iOS',
                      'benchmark': 'iOSWorld', 'tasks': tasks})


def _ledger(d: Path) -> list | None:
    """The PCO certificate's obligations (type, text, verdict, claim, evidence step), if any."""
    try:
        cert = json.loads((d / 'certificate.json').read_text())
    except (OSError, ValueError):
        return None
    return [{'type': o.get('type'), 'text': o['obligation'].split(':', 1)[-1].strip(), 'verdict': o.get('verdict'),
             'claim': o.get('claim'), 'frame': o.get('evidence_frame')} for o in cert.get('ledger', [])]


def _ios_args(args: dict) -> dict:
    out = {k: v for k, v in args.items() if k not in ('sig', 'internal', 'settled')}
    t = out.get('target')
    if isinstance(t, dict):
        out['target'] = {k: v for k, v in t.items() if k != 'text_index' or v}
    return out


def summarize(run: dict) -> dict:
    tasks = run['tasks']
    judged = [t for t in tasks if t.get('judged', True)]
    run['n'] = len(tasks)
    run['passed'] = sum(t['success'] for t in judged)
    run['judged'] = len(judged)
    scores = [t['score'] for t in judged if t['score'] is not None]
    run['mean'] = round(sum(scores) / len(scores), 4) if scores else None
    run['cost'] = round(sum(t['cost'] or 0 for t in tasks), 2)
    return run


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    runs = [r for spec in ANDROID_RUNS if (r := android_run(*spec))]
    runs += [r for spec in IOS_RUNS if (r := ios_run(*spec))]
    stats = json.loads((OUT / 'stats.json').read_text()) if (OUT / 'stats.json').exists() else None
    (OUT / 'data.js').write_text('window.EXPLORER = ' + json.dumps({'runs': runs, 'stats': stats}, separators=(',', ':')) + ';\n')
    (OUT / 'index.html').write_text((HERE / 'index.html').read_text().replace('src="data.js"', f'src="data.js?v={int(time.time())}"'))
    for r in runs:
        print(f"{r['platform']:8} {r['label']:24} {r['passed']}/{r['judged']} judged of {r['n']}")


if __name__ == '__main__':
    main()
