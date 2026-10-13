"""Audit numbers for the paper, computed from the iOSWorld run folders.

    python3 -m benchmarks.paper.audit [BENCH_ROOT]   -> BENCH_ROOT/paper/audit.json (+ audit-sample.json)

What it measures, per run: how each proven claim matched its cited screen (exact substring,
token coverage, digits), how short the claims are, which kinds of UI nodes they matched, how many
final answers the checker completed, which rubric criteria flipped between the baseline and a PCO
run (action-type vs report-type), what happened to the tasks the checker sent back, how many
tasks exhausted the action budget, and how many tasks the companion-port repair re-ran. It also
draws the manual-audit sample (seed 7) and joins it with the labels in paper/audit-labels.json.
Nothing in the paper's audit section is typed by hand.
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
from collections import Counter
from pathlib import Path

from benchmarks.explorer.stats import binom_two_sided
from benchmarks.iosworld import pco  # the checker as run on the benchmark

if not hasattr(pco, 'verify_run'):  # older checker module: verify one run folder through its task dir
    pco.verify_run = lambda run: pco.verify(Path(run).parent.parent)  # noqa: E731

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(os.environ.get('VERDIKT_BENCH', 'bench-results'))
RUNS = ROOT / 'iosworld-runs'
BASE, V2, REP, ABL, V1 = 'run1-opus', 'run3-pco-v2', 'run4-pco-v2-repeat', 'run5-v2-ledger-only', 'run2-pco'
# Rubric criteria that ask for something to be reported rather than done.
REPORT = re.compile(r'^(report|answer|provide|give|state|tell|list|summar|return|include|mention|identify|calculate|compute|'
                    r'determine|present|respond|output|explain|recommend|compare|note)', re.I)
EDITABLE = {'TextField', 'TextArea', 'SearchField', 'SecureTextField', 'TextView'}
BUDGET = 50


def load(run: str) -> dict[str, dict]:
    out = {}
    for f in (RUNS / run).glob('*/task.json'):
        d = json.loads(f.read_text())
        ev = d.get('evaluation') or {}
        rr = ev.get('rubric_results') or []
        out[d['task']] = {'dir': f.parent, 'pass': bool(rr) and all(r.get('satisfied') for r in rr), 'score': ev.get('score'), 'rr': rr,
                          'augmented': d.get('agent_answer_raw') is not None and (d.get('agent_answer_raw') or '') != (d.get('answer') or ''),
                          'actions': d.get('actions') or 0, 'rounds': d.get('checker_rounds') or 0, 'category': d.get('category'), 'goal': d.get('goal', '')}
    return out


def branch(text: str, claim: str) -> str:
    c = pco.norm(claim)
    if not c:
        return 'empty'
    if c in text:
        return 'substring'
    tokens = re.findall(r'[\w$%.:/-]+', c)
    if len(c) > pco.LONG and tokens and sum(t in text for t in tokens) / len(tokens) >= pco.COVERAGE:
        return 'token-coverage'
    digits = re.sub(r'[^\d.]', '', c)
    if digits and len(digits) >= 2 and digits in re.sub(r'[^\d.]', '', text):
        return 'digits'
    return 'none'


def matched_nodes(run: Path, frame, claim: str) -> list[dict]:
    try:
        nodes = json.loads((run / 'screens' / f'{int(frame):04d}.tree.json').read_text())
    except (OSError, ValueError, TypeError):
        return []
    c = pco.norm(claim)
    hits = []
    for n in nodes if isinstance(nodes, list) else []:
        for k in ('AXLabel', 'AXValue', 'title', 'label', 'value'):
            v = n.get(k)
            if isinstance(v, str) and v and c and c in pco.norm(v):
                hits.append({'type': n.get('type') or n.get('role'), 'key': k, 'text': v[:120]})
                break
    return hits


def proven_items(run_name: str) -> list[dict]:
    items = []
    for f in sorted((RUNS / run_name).glob('*/task.json')):
        run = pco.run_dir(f.parent)
        if not run:
            continue
        for o in pco.verify_run(run)['obligations']:
            if o['verdict'] == 'proven':
                items.append({'task': f.parent.name, 'run': run, **o})
    return items


def proof_stats(run_name: str) -> dict:
    items = proven_items(run_name)
    br, kinds, by_type = Counter(), Counter(), Counter()
    short = editable_only = 0
    lengths = []
    for o in items:
        by_type[o['type']] += 1
        if o['type'] == 'SAY':
            br['stated'] += 1
            continue
        text = pco.screen_text(o['run'], o['evidence_frame']) or ''
        b = branch(text, o['claim'])
        br[b] += 1
        n = len(pco.norm(o['claim']))
        lengths.append(n)
        short += n <= 6
        if b == 'substring':
            hits = matched_nodes(o['run'], o['evidence_frame'], o['claim'])
            ks = {h['type'] for h in hits}
            for k in ks:
                kinds[k] += 1
            if ks and ks <= EDITABLE:
                editable_only += 1
    lengths.sort()
    return {'proven': len(items), 'by_type': dict(by_type), 'match': dict(br), 'claims_le_6_chars': short,
            'median_claim_chars': lengths[len(lengths) // 2] if lengths else None, 'matched_only_in_editable_field': editable_only,
            'node_kinds': dict(kinds.most_common(8))}


def flips(base: dict, x: dict) -> dict:
    gained = sorted(t for t in base if t in x and not base[t]['pass'] and x[t]['pass'])
    lost = sorted(t for t in base if t in x and base[t]['pass'] and not x[t]['pass'])
    kinds = Counter()
    only_report = 0
    for t in gained:
        before = {c['criterion']: c.get('satisfied') for c in base[t]['rr']}
        flipped = [c['criterion'] for c in x[t]['rr'] if c.get('satisfied') and not before.get(c['criterion'])]
        for c in flipped:
            kinds['report' if REPORT.match(c) else 'action'] += 1
        only_report += bool(flipped) and all(REPORT.match(c) for c in flipped)
    return {'gained': gained, 'lost': lost, 'criteria_flipped_in_gained': dict(kinds), 'gained_on_report_criteria_only': only_report,
            'answers_completed_in_gained': sum(x[t]['augmented'] for t in gained), 'answers_completed': sum(x[t]['augmented'] for t in x)}


def rounds(base: dict, x: dict) -> dict:
    sent = [t for t in x if x[t]['rounds'] > 0]
    kept = [t for t in x if x[t]['rounds'] == 0]
    return {'sent_back': len(sent), 'sent_back_passed': sum(x[t]['pass'] for t in sent), 'sent_back_baseline_passed': sum(base[t]['pass'] for t in sent if t in base),
            'not_sent_back': len(kept), 'not_sent_back_passed': sum(x[t]['pass'] for t in kept), 'not_sent_back_baseline_passed': sum(base[t]['pass'] for t in kept if t in base),
            'sent_back_mean_actions': round(sum(x[t]['actions'] for t in sent) / len(sent), 1) if sent else None}


def budget(x: dict) -> dict:
    failed = [t for t in x if not x[t]['pass']]
    return {'exhausted': sum(x[t]['actions'] >= BUDGET for t in x), 'near_exhausted_48': sum(x[t]['actions'] >= BUDGET - 2 for t in x),
            'failed': len(failed), 'failed_exhausted': sum(x[t]['actions'] >= BUDGET for t in failed),
            'failed_near_exhausted_48': sum(x[t]['actions'] >= BUDGET - 2 for t in failed),
            'mean_actions': round(sum(x[t]['actions'] for t in x) / len(x), 1) if x else None}


def collision(run: str) -> int:
    try:
        return len(json.loads((RUNS / run / 'at-risk-companion-collision.json').read_text()))
    except (OSError, ValueError):
        return 0


def rubric_mix() -> dict:
    tasks = json.loads((ROOT / 'iosworld' / 'tasks.json').read_text())
    crit = [c['criterion'] for t in tasks for c in t['rubric']]
    return {'criteria': len(crit), 'report_type': sum(bool(REPORT.match(c)) for c in crit)}


def manual_sample() -> dict:
    """The seed-7 sample of proven DO and KNOW obligations in the v2 run, joined with the labels."""
    items = [o for o in proven_items(V2) if o['type'] in ('DO', 'KNOW')]
    rnd = random.Random(7)
    do = [o for o in items if o['type'] == 'DO']
    know = [o for o in items if o['type'] == 'KNOW']
    sample = rnd.sample(do, 40) + rnd.sample(know, 20)
    try:
        lab = json.loads((ROOT / 'paper' / 'audit-labels.json').read_text())
    except (OSError, ValueError):
        lab = {}
    labels = lab.get('labels') or []
    rows = []
    for i, o in enumerate(sample):
        rows.append({'i': i, 'task': o['task'], 'type': o['type'], 'obligation': o['obligation'], 'claim': o['claim'], 'evidence_frame': o['evidence_frame'],
                     'explanation': o.get('explanation'), 'matched': matched_nodes(o['run'], o['evidence_frame'], o['claim'])[:3],
                     'label': labels[i] if i < len(labels) else None, 'note': (lab.get('notes') or {}).get(str(i))})
    counts = Counter(r['label'] for r in rows if r['label'])
    by_type = {ty: dict(Counter(r['label'] for r in rows if r['type'] == ty and r['label'])) for ty in ('DO', 'KNOW')}
    (ROOT / 'paper' / 'audit-sample.json').write_text(json.dumps({'legend': lab.get('legend'), 'seed': 7, 'rows': rows}, indent=1, default=str))
    return {'n': len(rows), 'labelled': sum(1 for r in rows if r['label']), 'counts': dict(counts), 'by_type': by_type, 'legend': lab.get('legend')}


def main() -> None:
    runs = {k: load(k) for k in (BASE, V1, V2, REP, ABL)}
    base = runs[BASE]
    out = {
        'rubric': rubric_mix(),
        'proofs': {k: proof_stats(k) for k in (V1, V2, REP, ABL)},
        'flips': {k: flips(base, runs[k]) for k in (V2, REP, ABL, V1)},
        'rounds': {k: rounds(base, runs[k]) for k in (V2, REP)},
        'budget': {k: budget(runs[k]) for k in (BASE, V1, V2, REP, ABL)},
        'collision_rerun': {BASE: collision(BASE), V1: collision(V1)},
        'manual': manual_sample(),
    }
    # Did the resumption rounds matter? Paired on the tasks the checker sent back.
    v2 = runs[V2]
    sent = [t for t in v2 if v2[t]['rounds'] > 0]
    gain = sum(v2[t]['pass'] and not base[t]['pass'] for t in sent)
    loss = sum(base[t]['pass'] and not v2[t]['pass'] for t in sent)
    out['rounds'][V2].update({'paired_gain': gain, 'paired_loss': loss, 'mcnemar_p': binom_two_sided(min(gain, loss), gain + loss)})
    (ROOT / 'paper' / 'audit.json').write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != 'manual'}, indent=1))
    print('manual:', json.dumps({k: v for k, v in out['manual'].items() if k != 'legend'}))


if __name__ == '__main__':
    main()
