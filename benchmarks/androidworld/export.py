"""Export per-task results of attempts to CSV and print aggregate stats.

    python -m benchmarks.androidworld.export OUT.csv RUN_DIR [RUN_DIR ...]
"""
import csv
import os
import json
import statistics
import sys
from pathlib import Path

META = json.loads((Path(os.environ.get('ANDROID_WORLD_SRC', 'android_world')) / 'android_world/task_metadata.json').read_text())
META = {m['task_name']: m for m in META}


def main() -> None:
    out = Path(sys.argv[1])
    rows = []
    for run in map(Path, sys.argv[2:]):
        for f in sorted(run.glob('tasks/*/result.json')):
            r = json.loads(f.read_text())
            m = META.get(r['task'], {})
            rows.append({'run': run.name, 'task': r['task'], 'difficulty': m.get('difficulty'),
                         'tags': ';'.join(m.get('tags', [])), 'success': r.get('success'),
                         'reward': r.get('reward'), 'done': r.get('done'), 'status': r.get('status'),
                         'steps': r.get('steps'), 'budget': r.get('budget'), 'seconds': r.get('seconds'),
                         'agent_seconds': r.get('agent_seconds'), 'cost_usd': r.get('total_cost_usd'),
                         'turns': r.get('num_turns'), 'model': r.get('model'), 'answer': r.get('answer')})
    with out.open('w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for run in sorted({r['run'] for r in rows}):
        rs = [r for r in rows if r['run'] == run]
        ok = [r for r in rs if r['success'] == 1.0]
        print(f"\n{run}: {len(ok)}/{len(rs)} = {len(ok)/len(rs):.1%}  cost ${sum(r['cost_usd'] or 0 for r in rs):.2f}  "
              f"median task {statistics.median(r['seconds'] for r in rs):.0f}s  "
              f"median steps/budget {statistics.median(r['steps']/r['budget'] for r in rs):.2f}")
        for d in ('easy', 'medium', 'hard'):
            ds = [r for r in rs if r['difficulty'] == d]
            if ds:
                print(f"  {d:6} {sum(r['success'] == 1.0 for r in ds)}/{len(ds)} = {sum(r['success'] == 1.0 for r in ds)/len(ds):.1%}")
        tags = sorted({t for r in rs for t in r['tags'].split(';') if t})
        for t in tags:
            ts = [r for r in rs if t in r['tags'].split(';')]
            print(f"    tag {t:24} {sum(r['success'] == 1.0 for r in ts)}/{len(ts)}")


if __name__ == '__main__':
    main()
