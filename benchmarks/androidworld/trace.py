"""Print one task's trajectory: python -m benchmarks.androidworld.trace RUN_DIR TASK"""
import json
import sys
from pathlib import Path

d = Path(sys.argv[1]) / 'tasks' / sys.argv[2]
r = json.loads((d / 'result.json').read_text())
print('GOAL:', r['goal'])
print('reward', r.get('reward'), 'done', r.get('done'), 'status', r.get('status'), 'answer', r.get('answer'))
for line in (d / 'agent.jsonl').read_text().splitlines():
    try:
        e = json.loads(line)
    except ValueError:
        continue
    if e.get('type') == 'assistant':
        for b in e['message']['content']:
            if b.get('type') == 'text':
                print('  SAY', b['text'][:500].replace('\n', ' '))
            elif b.get('type') == 'tool_use':
                print('  USE', b['name'].split('__')[-1], json.dumps(b['input'])[:160])
    elif e.get('type') == 'user' and isinstance(e['message'].get('content'), list):
        for b in e['message']['content']:
            if b.get('type') == 'tool_result':
                c = b.get('content')
                t = c if isinstance(c, str) else ' '.join(x.get('text', '') for x in c if isinstance(x, dict))
                print('    ->', t.split('\n')[0][:150])
