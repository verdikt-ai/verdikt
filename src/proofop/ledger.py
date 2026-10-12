"""Proof-carrying operation: the checker for a run's obligation ledger.

The agent compiles the goal into typed obligations (DO / KNOW / IF) recorded as Verdikt
scenario criteria, and closes each one with the value it claims (`actual`) and the step of a
recorded screen that shows it (`evidence_frame`). This module, not the model, decides whether
the run is done:

- a closed obligation is *proven* only when the cited screen's UI tree contains the claimed
  value (normalised text match; long text may match by token coverage);
- an obligation closed as missing is an absence claim, challenged once before it is accepted;
- open obligations and unproven claims send the agent back to work (`challenge`);
- the final answer is completed from the proven KNOW facts (`answer_with_facts`), and the
  whole ledger with its verdicts is the run's certificate (`certificate`).
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

TYPES = ('DO', 'KNOW', 'IF')
LONG = 30            # claims longer than this may match by token coverage
COVERAGE = 0.8       # share of a long claim's tokens the screen must show


def norm(s: str) -> str:
    s = unicodedata.normalize('NFKC', s or '').lower()
    s = s.translate(str.maketrans({'‘': "'", '’': "'", '“': '"', '”': '"', '–': '-', '—': '-', ' ': ' '}))
    return re.sub(r'\s+', ' ', s).strip()


def kind(criterion: str) -> str:
    head = criterion.split(':', 1)[0].strip().upper()
    return head if head in TYPES else 'DO'


def run_dir(task_dir: Path) -> Path | None:
    runs = sorted((task_dir / 'runs').glob('*/progress.json'), key=lambda p: p.stat().st_mtime)
    return runs[-1].parent if runs else None


def ledger(run: Path) -> dict[str, dict]:
    """Latest event per obligation, in the order obligations were first recorded."""
    try:
        events = json.loads((run / 'progress.json').read_text())
    except (OSError, ValueError):
        return {}
    out: dict[str, dict] = {}
    for e in events:
        c = (e.get('criterion') or '').strip()
        if c:
            out[c] = e
    return out


def screen_text(run: Path, frame) -> str | None:
    try:
        nodes = json.loads((run / 'screens' / f'{int(frame):04d}.tree.json').read_text())
    except (OSError, ValueError, TypeError):
        return None
    parts = []
    for n in nodes if isinstance(nodes, list) else []:
        for k in ('AXLabel', 'AXValue', 'title', 'label', 'value'):
            v = n.get(k)
            if isinstance(v, str) and v:
                parts.append(v)
    return norm(' | '.join(parts))


def shows(text: str, claim: str) -> bool:
    c = norm(claim)
    if not c:
        return False
    if c in text:
        return True
    tokens = re.findall(r'[\w$%.:/-]+', c)
    if len(c) > LONG and tokens:
        return sum(t in text for t in tokens) / len(tokens) >= COVERAGE
    digits = re.sub(r'[^\d.]', '', c)
    return bool(digits) and len(digits) >= 2 and digits in re.sub(r'[^\d.]', '', text)


def verify(task_dir: Path) -> dict:
    run = run_dir(task_dir)
    if run is None:
        return {'run': None, 'obligations': []}
    obligations = []
    for crit, e in ledger(run).items():
        status = e.get('status')
        o = {'obligation': crit, 'type': kind(crit), 'status': status, 'claim': e.get('actual'),
             'evidence_frame': e.get('evidence_frame'), 'explanation': e.get('explanation')}
        if status == 'pass':
            text = screen_text(run, e.get('evidence_frame'))
            if not e.get('actual'):
                o['verdict'], o['reason'] = 'unproven', 'closed without the value it claims (`actual`)'
            elif text is None:
                o['verdict'], o['reason'] = 'unproven', f"cites no recorded screen (evidence_frame={e.get('evidence_frame')})"
            elif shows(text, e['actual']):
                o['verdict'], o['reason'] = 'proven', ''
            else:
                o['verdict'], o['reason'] = 'unproven', f"screen {e.get('evidence_frame')} does not show {e['actual']!r}"
        elif status in ('fail', 'blocked', 'inconclusive'):
            o['verdict'], o['reason'] = 'absent', e.get('explanation') or 'closed as not possible'
        else:
            o['verdict'], o['reason'] = 'open', 'never closed'
        obligations.append(o)
    return {'run': str(run), 'obligations': obligations}


def challenge(result: dict, absence_challenged: set[str]) -> str | None:
    """What the agent must still do, or None when the ledger is discharged."""
    obs = result['obligations']
    if not obs:
        return ('The checker found no obligations in your ledger. Record every DO / KNOW / IF obligation of the goal '
                'with scenario_progress(criterion=...), close each one with actual=<value> and evidence_frame=<step>, '
                'and continue with the actions you have left.')
    lines = []
    for o in obs:
        if o['verdict'] == 'open':
            lines.append(f"- OPEN: {o['obligation']}")
        elif o['verdict'] == 'unproven':
            lines.append(f"- REJECTED: {o['obligation']}: {o['reason']}. Show it on a screen and close it again with the exact value.")
        elif o['verdict'] == 'absent' and o['obligation'] not in absence_challenged:
            lines.append(f"- ABSENCE CHALLENGED: {o['obligation']}: before accepting that it does not exist, open every place it "
                         "could be (threads and replies, item details, other tabs, other apps) and close it again.")
    if not lines:
        return None
    return ('The checker reviewed your obligation ledger and did not accept it yet:\n' + '\n'.join(lines) +
            '\nContinue with the actions you have left (your budget did not reset). Do not call end_session. '
            'When done, end with the ANSWER line again.')


def answer_with_facts(answer: str | None, result: dict) -> str | None:
    """The agent's answer, completed with every proven KNOW fact it left out."""
    facts = [o for o in result['obligations'] if o['type'] == 'KNOW' and o['verdict'] == 'proven' and o.get('claim')]
    base = (answer or '').strip()
    missing = [o for o in facts if norm(o['claim']) not in norm(base)]
    if not missing:
        return answer
    extra = '; '.join(f"{o['obligation'].split(':', 1)[-1].strip()}: {o['claim']}" for o in missing)
    return f'{base}; {extra}' if base and base.lower() != 'done' else extra


def certificate(result: dict, rounds: int) -> dict:
    obs = result['obligations']
    count = lambda v: sum(o['verdict'] == v for o in obs)  # noqa: E731
    return {'rounds': rounds, 'obligations': len(obs), 'proven': count('proven'), 'unproven': count('unproven'),
            'absent': count('absent'), 'open': count('open'), 'ledger': obs}
