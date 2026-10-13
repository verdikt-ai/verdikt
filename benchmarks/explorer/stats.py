"""Every number the paper and the results site report, computed from the run folders.

    python3 -m benchmarks.explorer.stats [BENCH_ROOT]   -> BENCH_ROOT/explorer/stats.json + STATS.md

Per run: pass@1 with a 95% Wilson interval, cost, actions; iOS also the mean rubric score with a
bootstrap interval and a per-category breakdown. Paired comparisons on the same tasks: exact
McNemar test on pass/fail; for iOS rubric scores an exact sign test and a bootstrap interval of the
mean paired difference. Nothing is typed by hand.
"""
from __future__ import annotations

import json
import math
import random
import os
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(os.environ.get('VERDIKT_BENCH', 'bench-results'))

ANDROID = {
    'run2-opus': ('A v1', 30), 'run3-opus': ('A', 30), 'practice-seed7': ('A', 7), 'practice-seed8': ('A', 8),
    'run4-opus-skills': ('B v3', 30), 'run5-opus-skills': ('B', 30), 'run6-opus-skills78': ('B (seeds 7+8)', 30),
    'run8-opus-contracts': ('C (contracts)', 30),
    'run9-contracts-seed7': ('C (contracts)', 7), 'run10-contracts-seed8': ('C (contracts)', 8),
}
IOS = {'run1-opus': 'Baseline', 'run2-pco': 'PCO v1', 'run3-pco-v2': 'PCO v2', 'run4-pco-v2-repeat': 'PCO v2 (repeat)', 'run5-v2-ledger-only': 'v2 ledger, no checker', 'run3-pco': 'PCO round 2', 'run4-pco-ledger-only': 'Ledger only (no checker)'}
PAIRS_ANDROID = [('run3-opus', 'run8-opus-contracts'), ('practice-seed7', 'run9-contracts-seed7'), ('practice-seed8', 'run10-contracts-seed8'), ('run3-opus', 'run5-opus-skills'), ('run5-opus-skills', 'run6-opus-skills78')]
PAIRS_IOS = [('run1-opus', 'run3-pco-v2'), ('run1-opus', 'run4-pco-v2-repeat'), ('run3-pco-v2', 'run4-pco-v2-repeat'), ('run5-v2-ledger-only', 'run3-pco-v2'), ('run1-opus', 'run5-v2-ledger-only'), ('run2-pco', 'run3-pco-v2'), ('run1-opus', 'run2-pco'), ('run1-opus', 'run3-pco'), ('run2-pco', 'run3-pco'), ('run2-pco', 'run4-pco-ledger-only')]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 4), round(c + h, 4))


def binom_two_sided(k: int, n: int) -> float:
    """Exact two-sided binomial test p-value for k successes in n trials at p = 0.5."""
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(k, n - k) + 1)) / 2 ** n
    return round(min(1.0, 2 * tail), 4)


def bootstrap_mean(xs: list[float], reps: int = 10000, seed: int = 7) -> tuple[float, float]:
    if not xs:
        return (0.0, 0.0)
    rnd = random.Random(seed)
    means = sorted(sum(rnd.choice(xs) for _ in xs) / len(xs) for _ in range(reps))
    return (round(means[int(.025 * reps)], 4), round(means[int(.975 * reps)], 4))


def android_tasks(run: str) -> dict[str, dict]:
    out = {}
    for f in (ROOT / 'androidworld-full' / run / 'tasks').glob('*/result.json'):
        r = json.loads(f.read_text())
        if r.get('outcome') == 'graded':
            out[r['task']] = {'pass': r.get('success') == 1.0, 'steps': r.get('steps'), 'budget': r.get('budget'),
                              'cost': r.get('total_cost_usd') or 0, 'seconds': r.get('seconds') or 0}
    return out


def ios_tasks(run: str) -> dict[str, dict]:
    out = {}
    for f in (ROOT / 'iosworld-runs' / run).glob('*/task.json'):
        t = json.loads(f.read_text())
        e = t.get('evaluation') or {}
        if e.get('score') is None:
            continue
        cert = {}
        cf = f.parent / 'certificate.json'
        if cf.exists():
            c = json.loads(cf.read_text())
            cert = {k: c.get(k) for k in ('rounds', 'obligations', 'proven', 'unproven', 'absent', 'open')}
        out[t['task']] = {'score': float(e['score']), 'pass': e['score'] == 1, 'category': t.get('category'),
                          'actions': t.get('actions'), 'cost': t.get('cost_usd') or 0, 'seconds': t.get('seconds') or 0, **cert}
    return out


def summary(tasks: dict[str, dict], ios: bool) -> dict:
    n = len(tasks)
    k = sum(t['pass'] for t in tasks.values())
    s = {'tasks': n, 'passed': k, 'pass_rate': round(k / n, 4) if n else None, 'pass_ci95': wilson(k, n),
         'cost_usd': round(sum(t['cost'] for t in tasks.values()), 2),
         'median_seconds': sorted(t['seconds'] for t in tasks.values())[n // 2] if n else None}
    if ios:
        scores = [t['score'] for t in tasks.values()]
        s['mean_score'] = round(sum(scores) / n, 4) if n else None
        s['mean_score_ci95'] = bootstrap_mean(scores)
        cats = {}
        for t in tasks.values():
            c = cats.setdefault(t['category'] or 'other', {'tasks': 0, 'passed': 0, 'score_sum': 0.0})
            c['tasks'] += 1
            c['passed'] += t['pass']
            c['score_sum'] += t['score']
        s['by_category'] = {c: {'tasks': v['tasks'], 'passed': v['passed'], 'mean_score': round(v['score_sum'] / v['tasks'], 4)}
                            for c, v in sorted(cats.items())}
        if any('rounds' in t for t in tasks.values()):
            s['checker'] = {'tasks_resumed': sum(1 for t in tasks.values() if (t.get('rounds') or 0) > 0),
                            'obligations': sum(t.get('obligations') or 0 for t in tasks.values()),
                            'proven': sum(t.get('proven') or 0 for t in tasks.values()),
                            'unproven_at_end': sum(t.get('unproven') or 0 for t in tasks.values()),
                            'absent': sum(t.get('absent') or 0 for t in tasks.values())}
    return s


def paired(a: dict, b: dict, ios: bool) -> dict:
    common = sorted(set(a) & set(b))
    only_b = sum(1 for t in common if b[t]['pass'] and not a[t]['pass'])
    only_a = sum(1 for t in common if a[t]['pass'] and not b[t]['pass'])
    out = {'tasks': len(common), 'a_passes': sum(a[t]['pass'] for t in common), 'b_passes': sum(b[t]['pass'] for t in common),
           'b_only_passes': only_b, 'a_only_passes': only_a,
           'mcnemar_exact_p': binom_two_sided(min(only_a, only_b), only_a + only_b)}
    if ios:
        diffs = [b[t]['score'] - a[t]['score'] for t in common]
        up, down = sum(d > 0 for d in diffs), sum(d < 0 for d in diffs)
        out.update({'a_mean': round(sum(a[t]['score'] for t in common) / len(common), 4) if common else None,
                    'b_mean': round(sum(b[t]['score'] for t in common) / len(common), 4) if common else None,
                    'mean_score_diff': round(sum(diffs) / len(diffs), 4) if diffs else None,
                    'mean_score_diff_ci95': bootstrap_mean(diffs), 'improved': up, 'worsened': down,
                    'sign_test_p': binom_two_sided(min(up, down), up + down)})
    return out


def main() -> None:
    a_runs = {r: android_tasks(r) for r in ANDROID if (ROOT / 'androidworld-full' / r).exists()}
    i_runs = {r: ios_tasks(r) for r in IOS if (ROOT / 'iosworld-runs' / r).exists()}
    stats = {
        'android': {r: {'config': ANDROID[r][0], 'seed': ANDROID[r][1], **summary(t, False)} for r, t in a_runs.items() if t},
        'ios': {r: {'config': IOS[r], **summary(t, True)} for r, t in i_runs.items() if t},
        'paired_android': {f'{a} vs {b}': paired(a_runs[a], a_runs[b], False) for a, b in PAIRS_ANDROID if a_runs.get(a) and a_runs.get(b)},
        'paired_ios': {f'{a} vs {b}': paired(i_runs[a], i_runs[b], True) for a, b in PAIRS_IOS if i_runs.get(a) and i_runs.get(b)},
    }
    out = ROOT / 'explorer'
    out.mkdir(exist_ok=True)
    (out / 'stats.json').write_text(json.dumps(stats, indent=1))
    md = ['# Results statistics (generated by benchmarks/explorer/stats.py)', '', '## AndroidWorld (official grader, pass@1)', '',
          '| Run | Config | Seed | Passed | Rate | 95% CI | Cost |', '|---|---|---|---|---|---|---|']
    for r, s in stats['android'].items():
        md.append(f"| {r} | {s['config']} | {s['seed']} | {s['passed']}/{s['tasks']} | {s['pass_rate']:.1%} | "
                  f"{s['pass_ci95'][0]:.1%}–{s['pass_ci95'][1]:.1%} | ${s['cost_usd']} |")
    md += ['', '## iOSWorld (rubric judge, Claude Sonnet 4.6)', '',
           '| Run | Config | Fully passed | 95% CI | Mean rubric | 95% CI | Cost |', '|---|---|---|---|---|---|---|']
    for r, s in stats['ios'].items():
        md.append(f"| {r} | {s['config']} | {s['passed']}/{s['tasks']} ({s['pass_rate']:.1%}) | {s['pass_ci95'][0]:.1%}–{s['pass_ci95'][1]:.1%} | "
                  f"{s['mean_score']:.3f} | {s['mean_score_ci95'][0]:.3f}–{s['mean_score_ci95'][1]:.3f} | ${s['cost_usd']} |")
    md += ['', '## Paired comparisons (same tasks)', '', '| Pair | Tasks | Only 2nd passes | Only 1st passes | McNemar p | Mean score Δ (95% CI) | Sign test p |', '|---|---|---|---|---|---|---|']
    for name, p in {**stats['paired_android'], **stats['paired_ios']}.items():
        delta = f"{p['mean_score_diff']:+.3f} ({p['mean_score_diff_ci95'][0]:+.3f}…{p['mean_score_diff_ci95'][1]:+.3f})" if 'mean_score_diff' in p else '–'
        md.append(f"| {name} | {p['tasks']} | {p['b_only_passes']} | {p['a_only_passes']} | {p['mcnemar_exact_p']} | {delta} | {p.get('sign_test_p', '–')} |")
    (out / 'STATS.md').write_text('\n'.join(md) + '\n')
    print('\n'.join(md))


if __name__ == '__main__':
    main()
