"""iOS simulators over fb-idb: one idb_companion per simulator, verified to serve that simulator.

Needs `idb_companion` on PATH (brew install idb-companion) and the `fb-idb` Python package
(`pip install verdikt-core[ios]`).
"""
from __future__ import annotations

import asyncio
import json
import random
import socket
import subprocess
import threading
import time

from verdikt_core.drivers.base import Shot

KEY_ENTER = 40


def _free_port() -> int:
    # A random start: sessions started together must not probe the same port, or one session's
    # client ends up connected to another simulator's companion.
    start = 10882 + random.randrange(0, 4000)
    for port in range(start, start + 200):
        with socket.socket() as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    raise RuntimeError('no free port for idb_companion')


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) == 0


class IOSDriver:
    platform = 'iOS'

    def __init__(self, udid: str, companion: str = 'idb_companion', ready_timeout_s: float = 60, attempts: int = 3):
        from idb.common.types import TCPAddress  # noqa: F401  (fail early when fb-idb is missing)
        self.udid, self.companion, self.ready_timeout_s = udid, companion, ready_timeout_s
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.proc: subprocess.Popen | None = None
        self.client = None
        self._cm = None
        for _ in range(attempts):
            if self._call(self._connect()):
                return
            self._call(self._disconnect())
        raise RuntimeError(f'could not connect to a companion serving simulator {udid}')

    def _call(self, coro, timeout: float = 90):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=timeout)

    async def _connect(self) -> bool:
        from idb.common.types import TCPAddress
        from idb.grpc.client import Client
        port = _free_port()
        self.proc = subprocess.Popen([self.companion, '--udid', self.udid, '--grpc-port', str(port)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + self.ready_timeout_s
        while not await asyncio.to_thread(_port_open, port):
            if self.proc.poll() is not None or time.monotonic() > deadline:
                return False
            await asyncio.sleep(0.25)
        self._cm = Client.build(address=TCPAddress(host='localhost', port=port), logger=None)
        self.client = await self._cm.__aenter__()
        try:
            target = await self.client.describe()
        except Exception:  # noqa: BLE001
            return False
        return getattr(target, 'udid', None) == self.udid  # the companion behind this port must be ours

    async def _disconnect(self) -> None:
        if self._cm is not None:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        self._cm = self.client = None
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    async def _tree(self) -> list[dict]:
        try:
            from idb.common.types import AccessibilityInfoOptions  # fb-idb >= 1.2
        except ImportError:
            info = await self.client.accessibility_info(point=None, nested=False)
        else:
            info = await self.client.accessibility_info(None, AccessibilityInfoOptions(nested=False))
        parsed = json.loads(info.json)
        return parsed if isinstance(parsed, list) else [parsed]

    def capture(self) -> Shot:
        async def go():
            return await self._tree(), await self.client.screenshot()
        nodes, png = self._call(go())
        app = next((n for n in nodes if n.get('type') == 'Application'), {})
        frame = app.get('frame') or {}
        return Shot(png=png, nodes=nodes, width=int(frame.get('width', 0)), height=int(frame.get('height', 0)),
                    foreground=app.get('AXLabel') or '')

    def tap(self, x: int, y: int) -> None:
        self._call(self.client.tap(x=x, y=y, duration=None))

    def type_text(self, text: str) -> None:
        self._call(self.client.text(text))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 400) -> None:
        self._call(self.client.swipe(p_start=(x1, y1), p_end=(x2, y2), duration=duration_ms / 1000))

    def press(self, key: str) -> None:
        from idb.common.types import HIDButtonType
        key = key.lower()
        if key == 'enter':
            self._call(self.client.key(KEY_ENTER))
        elif key == 'home':
            self._call(self.client.button(button_type=HIDButtonType.HOME))
        else:
            raise ValueError("iOS keys: enter, home (there is no back key; use the app's back button)")

    def launch(self, app: str) -> None:
        self._call(self.client.launch(bundle_id=app, args=[], env={}, foreground_if_running=True))

    def close(self) -> None:
        try:
            self._call(self._disconnect(), timeout=20)
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
