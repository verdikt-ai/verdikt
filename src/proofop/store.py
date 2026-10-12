"""The evidence store: one folder per run, readable by the checker and by people.

    <run>/screens/NNNN.png        the screen at step NNNN
    <run>/screens/NNNN.tree.json  its UI tree (the evidence the checker reads)
    <run>/steps.jsonl             one line per step: screen, action, ledger event
    <run>/progress.json           the obligation ledger (events)
    <run>/certificate.json        written when the run finishes
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from proofop.drivers.base import Shot


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        (self.path / 'screens').mkdir(parents=True, exist_ok=True)
        self.step = 0
        self.events: list[dict] = []
        self.started = time.time()

    def _log(self, row: dict) -> None:
        with (self.path / 'steps.jsonl').open('a') as f:
            f.write(json.dumps({'step': self.step, 't': round(time.time() - self.started, 3), **row}) + '\n')

    def screen(self, shot: Shot) -> int:
        self.step += 1
        (self.path / 'screens' / f'{self.step:04d}.png').write_bytes(shot.png)
        (self.path / 'screens' / f'{self.step:04d}.tree.json').write_text(json.dumps(shot.nodes))
        self._log({'kind': 'screen', 'foreground': shot.foreground})
        return self.step

    def action(self, name: str, args: dict, result: str) -> None:
        self._log({'kind': 'action', 'name': name, 'args': args, 'result': result})

    def ledger(self, event: dict) -> None:
        self.events.append(event)
        (self.path / 'progress.json').write_text(json.dumps(self.events, indent=1))
        self._log({'kind': 'ledger', **event})

    def has_screen(self, step: int) -> bool:
        return (self.path / 'screens' / f'{int(step):04d}.tree.json').exists()

    def write(self, name: str, data: dict) -> None:
        (self.path / name).write_text(json.dumps(data, indent=1))
