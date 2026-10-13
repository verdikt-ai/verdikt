"""Run the Verdikt agent on the official AndroidWorld suite, one worker per emulator.

    python -m benchmarks.androidworld.runner --attempt DIR --console-port 5580 --mcp-port 7801

Workers share DIR: each task is claimed with an atomic mkdir, so several workers on
several emulators split one suite, and a re-run resumes (finished tasks are skipped).
Task instances come from the official suite_utils.create_suite(seed=30,
n_task_combinations=1), so every worker sees the same parameters as the official runner.
Success follows suite_utils._run_task: is_successful(env) counts only when the agent
declared the episode done within int(10 * complexity) steps.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
import traceback
from pathlib import Path

os.environ.setdefault('GRPC_VERBOSITY', 'ERROR')
os.environ.setdefault('GRPC_ENABLE_FORK_SUPPORT', '0')

from android_world import registry, suite_utils  # noqa: E402
from android_world.env import adb_utils, env_launcher  # noqa: E402

from . import server, tools  # noqa: E402

HERE = Path(__file__).resolve().parent
ADB = os.environ.get('ADB', str(Path(os.environ.get('ANDROID_SDK_ROOT', Path.home() / 'Library/Android/sdk')) / 'platform-tools/adb'))
SEED = 30
CLAUDE = os.environ.get('CLAUDE_BIN', 'claude')
SYSTEM_PROMPT = ''  # frozen at worker start so mid-run edits never leak into an attempt


def build_suite(names: list[str] | None, seed: int = SEED):
    reg = registry.TaskRegistry().get_registry(family='android_world')
    suite = suite_utils.create_suite(reg, n_task_combinations=1, seed=seed, tasks=names)
    return [(name, instances[0]) for name, instances in suite.items()]


def ensure_routes(serial: str) -> bool:
    """The emulator sometimes boots with Wi-Fi as the default network but an empty wlan0
    routing table, so the device cannot reach the host and the accessibility forwarder
    (the benchmark's own perception and grading channel) goes dark. Toggling Wi-Fi rebuilds it."""
    def sh(cmd: str) -> str:
        return subprocess.run([ADB, '-s', serial, 'shell', cmd], capture_output=True, text=True).stdout.strip()
    if sh('settings get global wifi_on') != '1' or sh('ip route show table wlan0'):
        return False
    sh('svc wifi disable')
    time.sleep(3)
    sh('svc wifi enable')
    for _ in range(20):
        time.sleep(1)
        if sh('ip route show table wlan0'):
            break
    return True


def ensure_osmand_map(env) -> None:
    """OsmAndApp.setup copies Liechtenstein_europe.obf into OsmAnd's files dir, but on this
    image the file is gone by the time tasks run (OsmAnd re-initializes that folder). Put it
    back exactly as the official setup does (copy + chcon) before each OsmAnd task."""
    from android_world.env.setup_device import apps
    from android_world.utils import file_utils
    path = apps.download_app_data('Liechtenstein_europe.obf')
    file_utils.copy_data_to_device(path, apps.OsmAndApp.DEVICE_MAPS_PATH, env.controller)
    adb_utils.issue_generic_request(['shell', 'chcon', 'u:object_r:media_rw_data_file:s0',
                                     apps.OsmAndApp.DEVICE_MAPS_PATH + 'Liechtenstein_europe.obf'], env.controller)


def vlc_permission_flow(env, serial: str) -> bool:
    """VlcApp.setup is meant to walk VLC's own permission flow (GRANT PERMISSION -> OK ->
    "Allow access to manage all files"), but it taps the label, so the grant never happens.
    VLC's media library only starts indexing when the grant arrives through that flow, so a
    pre-granted permission leaves Playlists stuck on "Loading" and playlists never reach the
    DB the grader reads. Replay the flow after the task's own initialization, then go home."""
    def sh(*args: str) -> None:
        subprocess.run([ADB, '-s', serial, 'shell', *args], capture_output=True)

    def tap_where(match) -> bool:
        for _ in range(6):
            for e in env.get_state(wait_to_stabilize=False).ui_elements:
                if e.bbox_pixels is not None and match(e):
                    x, y = e.bbox_pixels.center
                    sh('input', 'tap', str(int(x)), str(int(y)))
                    time.sleep(2)
                    return True
            time.sleep(1)
        return False

    sh('am', 'force-stop', 'org.videolan.vlc')
    sh('appops', 'set', '--uid', 'org.videolan.vlc', 'MANAGE_EXTERNAL_STORAGE', 'default')
    sh('monkey', '-p', 'org.videolan.vlc', '-c', 'android.intent.category.LAUNCHER', '1')
    time.sleep(4)
    tap_where(lambda e: (e.content_description or '') == 'Browse')  # the grant button lives in Browse
    ok = (tap_where(lambda e: (e.text or '').upper() == 'GRANT PERMISSION')
          and tap_where(lambda e: (e.text or '') == 'OK')
          and tap_where(lambda e: (e.resource_name or '').endswith('switch_widget')))
    sh('input', 'keyevent', '4')
    time.sleep(4)
    sh('input', 'keyevent', '3')
    time.sleep(1)
    return ok


def claim(task_dir: Path) -> bool:
    if (task_dir / 'result.json').exists():
        return False
    lock = task_dir / 'claim'
    task_dir.mkdir(parents=True, exist_ok=True)
    try:
        lock.mkdir()
    except FileExistsError:
        try:
            pid = int((lock / 'pid').read_text())
            os.kill(pid, 0)
            return False
        except (OSError, ValueError):
            pass  # the worker that claimed it died: take it over
    (lock / 'pid').write_text(str(os.getpid()))
    return True


def skills_for(goal: str, skills_dir: str) -> tuple[str, list[str]]:
    """App playbooks for the apps a goal names: skills_dir/index.json maps a playbook file
    to the lowercase keywords that select it."""
    if not skills_dir:
        return '', []
    root = Path(skills_dir)
    index = json.loads((root / 'index.json').read_text())
    text = goal.lower()
    chosen = [f for f, keys in index.items() if any(k in text for k in keys)]
    body = '\n\n'.join((root / f).read_text().strip() for f in chosen)
    return (f'\n\n# App playbooks (learned from earlier practice episodes)\n\n{body}\n' if body else ''), chosen


def run_agent(task_dir: Path, goal: str, budget: int, mcp_port: int, model: str, timeout_s: int,
              extra_system: str = '') -> dict:
    mcp_config = json.dumps({'mcpServers': {'android': {'type': 'http', 'url': f'http://127.0.0.1:{mcp_port}/mcp'}}})
    prompt = (f'Goal: {goal}\n\nStep budget: {budget} steps in total, including `answer` (if needed) '
              f'and `finish`. Begin with `screen`.')
    args = [CLAUDE, '-p', prompt, '--model', model, '--output-format', 'stream-json', '--verbose',
            '--system-prompt', SYSTEM_PROMPT + extra_system,
            '--mcp-config', mcp_config, '--strict-mcp-config',
            '--tools', '', '--allowedTools', 'mcp__android__*',
            '--setting-sources', '', '--max-turns', str(budget * 3 + 15)]
    workdir = task_dir / 'cwd'
    workdir.mkdir(exist_ok=True)
    env = dict(os.environ, ENABLE_TOOL_SEARCH='false', MCP_TIMEOUT='60000', MCP_TOOL_TIMEOUT='120000')
    started = time.monotonic()
    timed_out = False
    with (task_dir / 'agent.jsonl').open('w') as out, (task_dir / 'agent.stderr').open('w') as err:
        proc = subprocess.Popen(args, cwd=workdir, env=env, stdout=out, stderr=err,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        while proc.poll() is None:
            ep = tools.current()
            if ep is not None and ep.done:
                # Finished: give the CLI a moment to write its result event, then stop it.
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGTERM)
                break
            if time.monotonic() - started > timeout_s:
                timed_out = True
                os.killpg(proc.pid, signal.SIGTERM)
                break
            time.sleep(0.5)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
    info = {'exit_code': proc.returncode, 'timed_out': timed_out, 'agent_seconds': round(time.monotonic() - started, 1)}
    for line in (task_dir / 'agent.jsonl').read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'assistant':
            info['model'] = event.get('message', {}).get('model', info.get('model'))
        elif event.get('type') == 'result':
            info.update({k: event.get(k) for k in ('is_error', 'num_turns', 'total_cost_usd', 'subtype')})
    return info


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--attempt', required=True)
    p.add_argument('--console-port', type=int, default=5580)
    p.add_argument('--mcp-port', type=int, default=7801)
    p.add_argument('--model', default='opus')
    p.add_argument('--tasks', default='')
    p.add_argument('--timeout', type=int, default=1200)
    p.add_argument('--seed', type=int, default=SEED, help='suite seed; 30 is the official one')
    p.add_argument('--skills', default='', help='directory of app skill playbooks to give the agent')
    p.add_argument('--contracts', action='store_true',
                   help='contracted operation: goal contract, action expectations, answer evidence (contracts.py)')
    o = p.parse_args()
    root = Path(o.attempt).resolve()
    root.mkdir(parents=True, exist_ok=True)
    names = [t for t in o.tasks.split(',') if t] or None
    serial = f'emulator-{o.console_port}'
    log = (root / f'worker-{o.console_port}.log').open('a')
    global SYSTEM_PROMPT
    SYSTEM_PROMPT = (HERE / 'prompt.md').read_text()
    if o.contracts:
        SYSTEM_PROMPT += (HERE / 'prompt-contracts.md').read_text()
        tools.CONTRACTS = True
    (root / f'prompt-used-{o.console_port}.md').write_text(SYSTEM_PROMPT)

    def say(*parts):
        print(time.strftime('%H:%M:%S'), *parts, file=log, flush=True)

    ensure_routes(serial)
    env = env_launcher.load_and_setup_env(console_port=o.console_port, grpc_port=o.console_port + 3000,
                                          adb_path=ADB, freeze_datetime=True)
    # uiautomator2 (left by earlier tooling) suppresses the accessibility forwarder.
    subprocess.run([ADB, '-s', serial, 'shell', 'am', 'force-stop', 'com.github.uiautomator'], capture_output=True)
    # Complete what the official setup intends but misses on this image: the Markor,
    # Simple Gallery and VLC setups tap the "Allow access to manage all files" label,
    # which does not flip the switch, so the grant never happens.
    for package in ('net.gsantner.markor', 'com.simplemobiletools.gallery.pro', 'org.videolan.vlc'):
        subprocess.run([ADB, '-s', serial, 'shell', 'appops', 'set', '--uid', package,
                        'MANAGE_EXTERNAL_STORAGE', 'allow'], capture_output=True)
    env.hide_automation_ui()  # the pointer-location overlay covers the status bar clock
    server.serve_in_thread(o.mcp_port, contracts=o.contracts)
    say('worker up', serial, 'mcp', o.mcp_port)
    for name, task in build_suite(names, o.seed):
        task_dir = root / 'tasks' / name
        if not claim(task_dir):
            continue
        budget = int(10 * task.complexity)
        say('RUN', name, 'budget', budget)
        started = time.monotonic()
        result = {'task': name, 'goal': task.goal, 'budget': budget, 'complexity': task.complexity,
                  'seed': task.params.get('seed'), 'suite_seed': o.seed, 'device': serial, 'model_requested': o.model,
                  'skills': o.skills or None, 'contracts': o.contracts}
        (task_dir / 'task.json').write_text(json.dumps({'task': name, 'goal': task.goal,
                                                        'params': task.params}, indent=2, default=str))
        if ensure_routes(serial):
            say('repaired wlan0 routes before', name)
        try:
            env.reset(go_home=True)
            if name.startswith('OsmAnd'):
                ensure_osmand_map(env)
            task.initialize_task(env)
        except Exception:  # noqa: BLE001
            result.update(outcome='init_error', error=traceback.format_exc()[-3000:], success=None)
            say('INIT-ERROR', name)
            _write(task_dir, result)
            _teardown(task, env)
            continue
        if name.startswith('Vlc'):
            say('vlc permission flow', 'ok' if vlc_permission_flow(env, serial) else 'FAILED')
        env.reset(go_home=task.start_on_home_screen)
        ep = tools.Episode(env=env, goal=task.goal, budget=budget, out_dir=task_dir / 'frames')
        tools.begin(ep)
        try:
            extra, chosen = skills_for(task.goal, o.skills)
            result['skills_used'] = chosen
            agent = run_agent(task_dir, task.goal, budget, o.mcp_port, o.model, o.timeout, extra)
        finally:
            tools.end()
        result.update(agent)
        try:
            reward = float(task.is_successful(env))
            result['grader_error'] = None
        except Exception:  # noqa: BLE001
            reward = None
            result['grader_error'] = traceback.format_exc()[-3000:]
        done = ep.done and ep.status in ('complete', 'infeasible')
        result.update(reward=reward, done=done, status=ep.status, steps=ep.steps, answer=ep.answer,
                      success=(reward if done else 0.0) if reward is not None else None,
                      outcome='graded' if reward is not None else 'grader_error',
                      seconds=round(time.monotonic() - started, 1))
        try:
            env.get_state()  # final screenshot for the record
            tools_shot = env.get_state().pixels
            from PIL import Image
            Image.fromarray(tools_shot).save(task_dir / 'final.png')
        except Exception:  # noqa: BLE001
            pass
        _write(task_dir, result)
        say('RESULT', name, 'success', result['success'], 'reward', reward, 'steps', ep.steps, '/', budget,
            'cost', result.get('total_cost_usd'))
        _teardown(task, env)
    say('worker done')
    env.close()


def _write(task_dir: Path, result: dict) -> None:
    (task_dir / 'result.json').write_text(json.dumps(result, indent=2, default=str))
    try:
        (task_dir / 'claim' / 'pid').unlink()
        (task_dir / 'claim').rmdir()
    except OSError:
        pass


def _teardown(task, env) -> None:
    try:
        task.tear_down(env)
    except Exception:  # noqa: BLE001
        pass


if __name__ == '__main__':
    main()
