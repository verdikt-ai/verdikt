"""verdikt-core command line.

    verdikt-core serve --ios UDID | --android SERIAL [--run-dir DIR] [--budget N] [--rounds N] [--http PORT]
    verdikt-core verify RUN_DIR [--json]
    verdikt-core check 'CHECK' --tree TREE.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def cmd_serve(a: argparse.Namespace) -> int:
    from verdikt_core.server import build
    from verdikt_core.session import Session
    if bool(a.ios) == bool(a.android):
        print('give exactly one of --ios UDID or --android SERIAL', file=sys.stderr)
        return 2
    if a.ios:
        from verdikt_core.drivers.ios import IOSDriver
        driver = IOSDriver(a.ios)
    else:
        from verdikt_core.drivers.android import AndroidDriver
        driver = AndroidDriver(a.android)
    run_dir = Path(a.run_dir or Path('runs') / time.strftime('%Y%m%d-%H%M%S'))
    session = Session(driver, run_dir, budget=a.budget, rounds=a.rounds)
    print(f'verdikt-core: run folder {run_dir.resolve()}', file=sys.stderr)
    mcp = build(session)
    try:
        if a.http:
            import uvicorn
            uvicorn.run(mcp.streamable_http_app(), host='127.0.0.1', port=a.http, log_level='warning')
        else:
            mcp.run('stdio')
    finally:
        driver.close()
    return 0


def cmd_verify(a: argparse.Namespace) -> int:
    from verdikt_core import ledger
    result = ledger.verify_run(Path(a.run_dir))
    if a.json:
        print(json.dumps(ledger.certificate(result, rounds=0), indent=1))
    else:
        for o in result['obligations']:
            print(f"{o['verdict']:9} {o['obligation']}" + (f"  ({o['reason']})" if o.get('reason') else ''))
        cert = ledger.certificate(result, rounds=0)
        print(f"\n{cert['proven']} proven, {cert['unproven']} unproven, {cert['absent']} absent, {cert['open']} open of {cert['obligations']}")
    return 0 if all(o['verdict'] == 'proven' for o in result['obligations']) else 1


def cmd_check(a: argparse.Namespace) -> int:
    from types import SimpleNamespace

    from verdikt_core.checks import match_once, parse_check
    from verdikt_core.tree import parse_tree
    c = parse_check(a.check)
    if c.problems:
        print('cannot parse: ' + '; '.join(c.problems), file=sys.stderr)
        return 2
    screen = SimpleNamespace(elements=parse_tree(json.loads(Path(a.tree).read_text())))
    ok, actual, _ = match_once(c, screen)
    print(('PASS' if ok else 'FAIL') + (f': {actual}' if actual else ''))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="verdikt-core", description='Proof-carrying operation for device agents.')
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('serve', help='run the MCP server for one device')
    s.add_argument('--ios', metavar='UDID')
    s.add_argument('--android', metavar='SERIAL')
    s.add_argument('--run-dir')
    s.add_argument('--budget', type=int, default=50, help='actions per session')
    s.add_argument('--rounds', type=int, default=2, help='times the checker may refuse finish')
    s.add_argument('--http', type=int, metavar='PORT', help='serve over HTTP instead of stdio')
    s.set_defaults(fn=cmd_serve)
    v = sub.add_parser('verify', help="re-check a run folder's ledger and print its certificate")
    v.add_argument('run_dir')
    v.add_argument('--json', action='store_true')
    v.set_defaults(fn=cmd_verify)
    c = sub.add_parser('check', help='evaluate one check against a saved UI tree')
    c.add_argument('check')
    c.add_argument('--tree', required=True)
    c.set_defaults(fn=cmd_check)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == '__main__':
    sys.exit(main())
