"""Verdikt on iOSWorld: the product's own MCP server and iOS session (fb-idb) drive the
benchmark simulator; each task is one Verdikt scenario with a 50-action budget.

    <iosworld>/.venv/bin/python -m benchmarks.iosworld.runner --attempt DIR [--tasks a,b] [--limit N]

Per task: iOSWorld's own data wipe + reseed of every benchmark app (`appium_agent.reset_app_data`
/ `reseed_apps`, the non-erasing path), a cold `claude -p` session whose only tools are the
`verdikt` MCP server, then the product run folder is converted to iOSWorld's
`task.json` + `trajectory.json`, which `scripts/judge_trajectories.py` grades unchanged.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
IOSWORLD = Path(os.environ.get('IOSWORLD', Path('bench-results/iosworld')))
VERDIKT_PY = os.environ.get('VERDIKT_PY', sys.executable)
# The product as of the stable-targets fix (main + fix/android-stable-targets).
VERDIKT_SRC = os.environ.get('VERDIKT_SRC', '')
CLAUDE = shutil.which('claude') or 'claude'
MAX_ACTIONS = 50  # iOSWorld's step limit
PORT = 7911
PROMPT = 'prompt.md'
PCO = False      # proof-carrying operation (--pco)
PCO_ROUNDS = 2   # checker rounds after the agent first stops


def _wait_port(port: int, timeout: float = 60) -> None:
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                return
        time.sleep(0.3)
    raise RuntimeError(f'verdikt server did not come up on port {port}')

sys.path.insert(0, str(IOSWORLD / 'scripts'))
import appium_agent as aw  # noqa: E402  (iOSWorld's own reset/seed helpers)

from . import pco  # noqa: E402


def reset_apps(udid: str, manifest: dict) -> None:
    apps = list(manifest)
    aw.reset_app_data(udid, apps, manifest)
    aw.reseed_apps(udid, apps, manifest)
    aw.pin_simulator_state(udid)


def run_agent(task: dict, task_dir: Path, udid: str, manifest: dict, model: str, timeout_s: int, port: int = 7911) -> dict:
    global PORT
    PORT = port
    runs = task_dir / 'runs'
    home = task_dir / 'verdikt-home'
    runs.mkdir(parents=True, exist_ok=True)
    home.mkdir(exist_ok=True)
    bundles = {a: manifest[a]['bundle_id'] for a in manifest}
    # The product server runs beside the agent (not as its stdio child), so the runner can end
    # the session itself and the run.json is written however the agent stops. The benchmark's
    # apps are the environment's allowed apps (`$QA_ALLOWED_BUNDLES`, product config).
    server_env = {'PYTHONPATH': f'{VERDIKT_SRC}:{REPO}', 'VERDIKT_HOME': str(home), 'VERDIKT_RUNS_DIR': str(runs),
                  'QA_MAX_ACTIONS_PER_SCENARIO': str(MAX_ACTIONS), 'PATH': os.environ['PATH'], 'HOME': os.environ['HOME'],
                  'QA_ALLOWED_BUNDLES': json.dumps(sorted(bundles.values()))}
    srv = subprocess.Popen([VERDIKT_PY, '-m', 'benchmarks.iosworld.serve_verdikt', str(PORT)], env=server_env,
                           cwd=REPO, stdout=(task_dir / 'server.log').open('w'), stderr=subprocess.STDOUT)
    _wait_port(PORT)
    mcp = {'mcpServers': {'verdikt': {'type': 'http', 'url': f'http://127.0.0.1:{PORT}/mcp'}}}
    first = bundles.get(task['apps'][0]) if task.get('apps') else None
    message = (f"Goal: {task['goal']}\n\n"
               f"Simulator udid: {udid}. Start with start_session(bundle_id=\"{first}\", udid=\"{udid}\", "
               f"lock_app=false, runs_dir=\"{runs}\", mode=\"scenarios\").\n"
               f"Apps on this phone (name: bundle_id): " + ', '.join(f'{a}: {b}' for a, b in sorted(bundles.items())))
    args = [CLAUDE, '-p', message, '--model', model, '--output-format', 'stream-json', '--verbose',
            '--system-prompt', (HERE / PROMPT).read_text(),
            '--mcp-config', json.dumps(mcp), '--strict-mcp-config', '--tools', '',
            '--allowedTools', 'mcp__verdikt__*', '--setting-sources', '', '--max-turns', str(MAX_ACTIONS * 3 + 20)]
    cwd = task_dir / 'cwd'
    cwd.mkdir(exist_ok=True)
    env = dict(os.environ, ENABLE_TOOL_SEARCH='false', MCP_TIMEOUT='60000', MCP_TOOL_TIMEOUT='180000')
    env.pop('ANTHROPIC_API_KEY', None)  # the agent runs on the CLI login, like the Android runs
    started = time.monotonic()
    deadline = started + timeout_s
    timed_out = False

    def launch(argv: list[str], mode: str) -> None:
        nonlocal timed_out
        with (task_dir / 'agent.jsonl').open(mode) as out, (task_dir / 'agent.stderr').open(mode) as err:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                    start_new_session=True)
            try:
                proc.wait(timeout=max(30, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, 9)
                timed_out = True

    launch(args, 'w')
    # Proof-carrying operation: the checker, not the model, decides the run is done. While the
    # ledger has open, unproven or unchallenged-absent obligations, the same agent session is
    # resumed on the same device session (the action budget does not reset).
    rounds, absence_seen = 0, set()
    while PCO and not timed_out and rounds < PCO_ROUNDS:
        msg = pco.challenge(pco.verify(task_dir), absence_seen)
        sid = _session_id(task_dir)
        if not msg or not sid:
            break
        absence_seen |= {o['obligation'] for o in pco.verify(task_dir)['obligations'] if o['verdict'] == 'absent'}
        rounds += 1
        (task_dir / f'checker-round-{rounds}.txt').write_text(msg)
        launch([CLAUDE, '-p', msg, '--resume', sid] + args[3:], 'a')
    try:
        req = urllib.request.Request(f'http://127.0.0.1:{PORT}/end', method='POST')
        ended = json.loads(urllib.request.urlopen(req, timeout=120).read())
    except Exception as exc:  # noqa: BLE001
        ended = {'ended': False, 'reason': repr(exc)}
    srv.terminate()
    try:
        srv.wait(timeout=20)
    except subprocess.TimeoutExpired:
        srv.kill()
    final, cost = '', 0.0
    for line in (task_dir / 'agent.jsonl').read_text().splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get('type') == 'result':
            final = e.get('result') or final
            cost += e.get('total_cost_usd') or 0
    m = re.findall(r'^ANSWER:\s*(.*)$', final, re.M)
    answer = m[-1].strip() if m else None
    answer = None if answer in (None, 'done') else answer
    extra = {}
    if PCO:
        result = pco.verify(task_dir)
        cert = pco.certificate(result, rounds)
        (task_dir / 'certificate.json').write_text(json.dumps(cert, indent=1))
        extra = {'agent_answer_raw': answer, 'checker_rounds': rounds,
                 'certificate': {k: v for k, v in cert.items() if k != 'ledger'}}
        answer = pco.answer_with_facts(answer, result)
    return {'seconds': round(time.monotonic() - started, 1), 'timed_out': timed_out, 'cost_usd': round(cost, 4),
            'runner_end': ended, 'answer': answer, 'final_text': final[-2000:], **extra}


def _session_id(task_dir: Path) -> str | None:
    for line in (task_dir / 'agent.jsonl').read_text().splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get('session_id'):
            return e['session_id']
    return None


def to_trajectory(task_dir: Path) -> list[dict]:
    """Product run.json -> iOSWorld trajectory: one entry per action, with the frame of the
    screen it was decided on and the frame of the next screen."""
    runs = sorted((task_dir / 'runs').rglob('run.json'), key=lambda p: p.stat().st_mtime)
    if not runs:
        return []
    run = runs[-1]
    steps = json.loads(run.read_text()).get('steps') or []
    frames = [(i, s) for i, s in enumerate(steps) if s.get('kind') == 'screen' and s.get('frame')]
    out = []
    for i, s in enumerate(steps):
        if s.get('kind') in ('screen', 'find') or (s.get('args') or {}).get('internal'):  # looks, not actions
            continue
        before = next((str(run.parent / f['frame']) for j, f in reversed(frames) if j < i), None)
        after = next((str(run.parent / f['frame']) for j, f in frames if j > i), None)
        out.append({'step': len(out) + 1, 'screenshot': before, 'post_action_screenshot': after,
                    'action': {'type': s.get('kind'), 'args': s.get('args'), 'result': s.get('result')}})
    if out and not out[-1]['post_action_screenshot'] and frames:
        out[-1]['post_action_screenshot'] = str(run.parent / frames[-1][1]['frame'])
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--attempt', required=True)
    p.add_argument('--tasks', default='')
    p.add_argument('--limit', type=int, default=0)
    p.add_argument('--shuffle', type=int, default=None,
                   help='run tasks in a fixed random order (this seed), so a partial run is a fair sample')
    p.add_argument('--model', default='opus')
    p.add_argument('--timeout', type=int, default=1800)  # iOSWorld: 30 minutes per session
    p.add_argument('--udid', default='', help='simulator for this worker (default: TEMP_SIM_UDID)')
    p.add_argument('--port', type=int, default=7911, help='product MCP server port for this worker')
    p.add_argument('--prompt', default='prompt.md', help='system prompt file in benchmarks/iosworld')
    p.add_argument('--pco', action='store_true', help='proof-carrying operation: obligation ledger + checker rounds')
    p.add_argument('--pco-rounds', type=int, default=2, help='checker rounds after the agent first stops (0 = ledger only, no checker)')
    o = p.parse_args()
    global PROMPT, PCO, PCO_ROUNDS
    PCO = o.pco
    PCO_ROUNDS = o.pco_rounds
    PROMPT = 'prompt-pco.md' if o.pco and o.prompt == 'prompt.md' else o.prompt
    udid = o.udid or (IOSWORLD / 'TEMP_SIM_UDID').read_text().split()[0]
    manifest = aw.load_app_manifest(str(IOSWORLD / 'iphone/bootstrap/.app_manifest.json'))
    tasks = json.loads((IOSWORLD / 'tasks.json').read_text())
    if o.tasks:
        wanted = o.tasks.split(',')
        tasks = [t for t in tasks if t['name'] in wanted]
    if o.shuffle is not None:
        import random
        random.Random(o.shuffle).shuffle(tasks)
    if o.limit:
        tasks = tasks[:o.limit]
    root = Path(o.attempt).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / 'verdikt-commit').write_text(subprocess.run(['git', '-C', str(REPO), 'rev-parse', 'HEAD'],
                                                        capture_output=True, text=True).stdout)
    for task in tasks:
        task_dir = root / task['name']
        if (task_dir / 'task.json').exists():
            continue
        task_dir.mkdir(parents=True, exist_ok=True)
        try:  # several workers (one simulator each) share the task list
            (task_dir / 'claim').mkdir()
        except FileExistsError:
            continue
        print(time.strftime('%H:%M:%S'), 'RUN', task['name'], udid[:8], flush=True)
        reset_apps(udid, manifest)
        res = run_agent(task, task_dir, udid, manifest, o.model, o.timeout, o.port)
        traj = to_trajectory(task_dir)
        (task_dir / 'trajectory.json').write_text(json.dumps(traj, indent=1))
        status = 'ok' if traj else 'error'
        (task_dir / 'task.json').write_text(json.dumps({
            'task': task['name'], 'goal': task['goal'], 'apps': task.get('apps'), 'category': task.get('category'),
            'status': status, 'agent_answer': res['answer'], 'actions': len(traj), **res}, indent=1))
        print(time.strftime('%H:%M:%S'), 'DONE', task['name'], status, len(traj), 'actions', res['seconds'], 's',
              f"${res['cost_usd']}", flush=True)


if __name__ == '__main__':
    main()
