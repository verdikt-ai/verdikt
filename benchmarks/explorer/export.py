"""Export the results site as a self-contained folder ready to host.

    python3 -m benchmarks.explorer.export OUT_DIR [--runs a,b,...] [--limit N]

OUT_DIR gets index.html, data.js (every run, with stats), media/ (replay frames re-encoded as
360-px WebP), and downloads/ (per-run CSV and sanitized JSON, iOS certificates, stats.json,
STATS.md). Nothing in it points outside OUT_DIR. Local paths and agent session ids are removed.
"""
from __future__ import annotations

import csv
import json
import time
import re
import shutil
import os
import sys
from pathlib import Path

from PIL import Image

from benchmarks.explorer import build

WIDTH = 360
LOCAL = re.compile(r'(/Users/[^\s"\']+|/private/[^\s"\']+|/tmp/[^\s"\']+)')
UUID = re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', re.I)
SIM = re.compile(r'\b[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\b')


def clean(v):
    """Strip machine-specific values (paths, simulator and session ids) from anything published."""
    if isinstance(v, str):
        return SIM.sub('<device>', UUID.sub('<id>', LOCAL.sub('<local>', v)))
    if isinstance(v, list):
        return [clean(x) for x in v]
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items() if k not in ('session_id', 'runs_dir', 'udid', 'sig')}
    return v


def media(src_rel: str | None, out: Path, run: str, task: str, cache: dict) -> str | None:
    if not src_rel:
        return None
    if src_rel in cache:
        return cache[src_rel]
    src = (build.OUT / src_rel).resolve()
    dest = out / 'media' / run / task / (src.stem + '.webp')
    if not dest.exists():
        try:
            im = Image.open(src).convert('RGB')
        except OSError:
            cache[src_rel] = None
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.resize((WIDTH, round(im.height * WIDTH / im.width)), Image.LANCZOS).save(dest, 'WEBP', quality=72, method=4)
    cache[src_rel] = str(dest.relative_to(out))
    return cache[src_rel]


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    opt = dict(a.split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
    out = Path(args[0]).resolve()
    only = set(opt['--runs'].split(',')) if '--runs' in opt else None
    limit = int(opt.get('--limit', 0))
    build.GIFS = False
    # build.py resolves its data root from argv at import; point it back at the benchmark folder.
    build.ROOT = Path(opt.get('--root', Path(os.environ.get('VERDIKT_BENCH', 'bench-results'))))
    build.OUT = build.ROOT / 'explorer'
    runs = [r for spec in build.ANDROID_RUNS if (r := build.android_run(*spec))]
    runs += [r for spec in build.IOS_RUNS if (r := build.ios_run(*spec))]
    runs = [r for r in runs if not only or r['id'] in only]
    dl = out / 'downloads'
    dl.mkdir(parents=True, exist_ok=True)
    for r in runs:
        cache: dict = {}
        tasks = r['tasks'][:limit] if limit else r['tasks']
        rows = []
        for t in tasks:
            for k in ('start', 'thumb'):
                t[k] = media(t.get(k), out, r['id'], t['id'], cache)
            for s in t['step_list']:
                s['frame'] = media(s.get('frame'), out, r['id'], t['id'], cache)
            t['gif'] = None
            cert = build.ROOT / 'iosworld-runs' / r['id'] / t['id'] / 'certificate.json'
            if cert.exists():
                (dl / r['id']).mkdir(exist_ok=True)
                (dl / r['id'] / f"{t['id']}.certificate.json").write_text(json.dumps(clean(json.loads(cert.read_text())), indent=1))
            detail = clean({k: v for k, v in t.items() if k not in ('thumb', 'start', 'gif', 'data', 'steplog')})
            (dl / r['id']).mkdir(exist_ok=True)
            (dl / r['id'] / f"{t['id']}.json").write_text(json.dumps(detail, indent=1))
            t['data'] = f"downloads/{r['id']}/{t['id']}.json"
            t['steplog'] = None
            rows.append({'run': r['id'], 'benchmark': r['benchmark'], 'task': t['id'], 'app': t['app'], 'category': t.get('category'),
                         'success': int(bool(t['success'])), 'score': t['score'], 'actions': len(t['step_list']),
                         'budget': t.get('budget'), 'seconds': t.get('seconds'), 'cost_usd': t.get('cost')})
        r['tasks'] = [clean(t) | {k: t[k] for k in ('start', 'thumb', 'data')} | {'step_list': [clean(s) | {'frame': s['frame']} for s in t['step_list']]} for t in tasks]
        with (dl / f"{r['id']}.csv").open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ['task'])
            w.writeheader()
            w.writerows(rows)
        print(f"{r['id']}: {len(tasks)} tasks, {len(cache)} frames")
    stats = build.OUT / 'stats.json'
    data = {'runs': runs, 'stats': json.loads(stats.read_text()) if stats.exists() else None, 'published': True}
    (out / 'data.js').write_text('window.EXPLORER = ' + json.dumps(data, separators=(',', ':')) + ';\n')
    (out / 'index.html').write_text((build.HERE / 'index.html').read_text().replace('src="data.js"', f'src="data.js?v={int(time.time())}"'))
    for f in ('stats.json', 'STATS.md'):
        if (build.OUT / f).exists():
            shutil.copy(build.OUT / f, dl / f)
    size = sum(p.stat().st_size for p in out.rglob('*') if p.is_file())
    print(f'site: {out} ({size / 1e6:.0f} MB)')


if __name__ == '__main__':
    main()
