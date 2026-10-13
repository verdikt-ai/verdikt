"""Summarize an attempt directory: python -m benchmarks.androidworld.summarize DIR"""
import json
import sys
from pathlib import Path


def main() -> None:
    root = Path(sys.argv[1])
    rows = []
    for f in sorted(root.glob('tasks/*/result.json')):
        rows.append(json.loads(f.read_text()))
    graded = [r for r in rows if r.get('outcome') == 'graded']
    ok = [r for r in graded if r.get('success') == 1.0]
    infra = [r for r in rows if r.get('outcome') != 'graded']
    cost = sum(r.get('total_cost_usd') or 0 for r in rows)
    print(f'tasks with results: {len(rows)}  graded: {len(graded)}  success: {len(ok)}  '
          f'rate over graded: {len(ok) / max(len(graded), 1):.1%}  infra errors: {len(infra)}  '
          f'CLI-estimated cost: ${cost:.2f}')
    for r in rows:
        mark = 'PASS' if r.get('success') == 1.0 else ('INFRA' if r.get('outcome') != 'graded' else 'FAIL')
        why = ''
        if mark == 'FAIL':
            why = f"reward={r.get('reward')} done={r.get('done')} status={r.get('status')} timed_out={r.get('timed_out')}"
        print(f"{mark:5} {r['task']:45} steps {r.get('steps', '-')}/{r['budget']:<3} "
              f"{r.get('seconds', 0):>6}s ${r.get('total_cost_usd') or 0:.2f} {why}")


if __name__ == '__main__':
    main()
